"""Point-in-time membership projection (Story U1.4).

Projects the append-only ``membership_event`` log (joined to frozen resolutions)
into the ``universe_membership`` interval table — the read-model. The projection
is at the **CompositeFIGI level**: events for every ``raw_identifier`` that
resolves to the same FIGI are merged, so a mid-membership ticker rename stays one
continuous interval. ``rebuild_projection`` always re-derives from the *full
ordered log* (never incremental), so a late/out-of-order event is handled
deterministically.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from sym.universe.registry import CORRECT, JOIN, LEAVE


@dataclass(frozen=True)
class MembershipEvent:
    """One resolved membership event fed to the projector."""

    composite_figi: str
    change: str
    effective_date: date
    event_id: int
    raw_identifier: str | None = None
    source: str | None = None
    provenance: dict | None = None


def pair_corrections(
    events: Iterable[MembershipEvent],
) -> tuple[list[MembershipEvent], int, int, int]:
    """Annihilate each reverses-corrective with exactly its target event (pure).

    A ``correct`` event whose ``provenance.reverses`` names a change kind is a
    TOMBSTONE for the event matching ``(raw_identifier, change, effective_date)``
    — the same triple+date :func:`gating.reverse_change` validates before
    appending. Both rows are removed from the stream, so an event landing
    between the wrong change and its corrective can no longer invert the
    corrective's intent (ledger D3). Matching is per ``raw_identifier``, never
    per FIGI — two tokens resolving to one FIGI must not cross-annihilate.

    Corrective dispositions:

    * matched explicit corrective → PAIRED (both rows removed);
    * EXPLICIT but unmatched (names a target that isn't in the stream) → a data
      error; the corrective is DROPPED — inert, never mutating state via the
      context-dependent toggle this design exists to kill — and counted as
      DANGLING (recorded review decision, 2026-06-10);
    * no ``reverses`` provenance at all (legacy rows) → SURVIVES as a toggle
      event (the pre-U3.7 behavior), counted as a TOGGLE.

    Preconditions (both hold for log-sourced streams): the stream belongs to ONE
    universe (``universe_id`` is deliberately absent from the match key), and
    the DB dedupe key guarantees no duplicate ``(raw, change, date)`` targets —
    hand-built streams violating either get input-order-dependent matching.

    Returns ``(survivors, paired_count, toggle_count, dangling_count)``.
    """
    ordered = list(events)
    targets: dict[tuple, list[int]] = defaultdict(list)
    for i, e in enumerate(ordered):
        if e.change in (JOIN, LEAVE):
            targets[(e.raw_identifier, e.change, e.effective_date)].append(i)
    void: set[int] = set()
    paired = toggles = dangling = 0
    for i, e in enumerate(ordered):
        if e.change != CORRECT:
            continue
        provenance = e.provenance if isinstance(e.provenance, dict) else {}
        if "reverses" not in provenance:
            toggles += 1  # legacy provenance-less corrective: keeps toggle behavior
            continue
        reverses = provenance["reverses"]
        target_index = None
        if reverses in (JOIN, LEAVE) and e.raw_identifier is not None:
            for j in targets.get((e.raw_identifier, reverses, e.effective_date), ()):
                if j not in void:
                    target_index = j
                    break
        if target_index is None:
            void.add(i)  # dangling explicit corrective: inert, counted
            dangling += 1
        else:
            void.add(i)
            void.add(target_index)
            paired += 1
    survivors = [e for i, e in enumerate(ordered) if i not in void]
    return survivors, paired, toggles, dangling


@dataclass(frozen=True)
class Interval:
    valid_from: date
    valid_to: date | None
    raw_identifier: str | None = None
    source: str | None = None


def _intervals_for_figi(
    events: Sequence[MembershipEvent], counters: dict[str, int] | None = None
) -> list[Interval]:
    """Run the join/leave/correct state machine over one FIGI's ordered events.

    ``counters`` (optional) accumulates ``orphan_leaves`` — leaves with no open
    interval (a member whose join predates the log floor); tolerated, but surfaced
    so incompleteness is visible rather than silent.
    """
    ordered = sorted(events, key=lambda e: (e.effective_date, e.event_id))
    intervals: list[Interval] = []
    open_from: date | None = None
    open_raw: str | None = None
    open_source: str | None = None

    def close(at: date) -> None:
        nonlocal open_from, open_raw, open_source
        if open_from is not None and at > open_from:  # drop zero-length memberships
            intervals.append(Interval(open_from, at, open_raw, open_source))
        open_from = None

    for e in ordered:
        opening = e.change == JOIN or (e.change == CORRECT and open_from is None)
        closing = e.change == LEAVE or (e.change == CORRECT and open_from is not None)
        if opening and open_from is None:
            open_from, open_raw, open_source = e.effective_date, e.raw_identifier, e.source
        elif closing and open_from is not None:
            close(e.effective_date)
        elif e.change == LEAVE and counters is not None:
            counters["orphan_leaves"] = counters.get("orphan_leaves", 0) + 1

    if open_from is not None:
        intervals.append(Interval(open_from, None, open_raw, open_source))

    # Coalesce adjacent intervals (prev.valid_to == next.valid_from) into one --
    # this is what makes a FIGI-level ticker rename a single continuous interval.
    # The coalesced interval carries the LATEST segment's raw token: after a rename
    # the member's current identifier is the meaningful one (the accuracy gate
    # compares these tokens against fresh provider snapshots).
    coalesced: list[Interval] = []
    for iv in intervals:
        if coalesced and coalesced[-1].valid_to == iv.valid_from:
            prev = coalesced[-1]
            coalesced[-1] = Interval(prev.valid_from, iv.valid_to, iv.raw_identifier, iv.source)
        else:
            coalesced.append(iv)
    return coalesced


def project_membership(
    events: Iterable[MembershipEvent], counters: dict[str, int] | None = None
) -> dict[str, list[Interval]]:
    """Project events into per-FIGI membership intervals (pure, deterministic).

    Reverses-correctives are paired off against their targets FIRST (see
    :func:`pair_corrections`); only the survivors run the state machine.
    """
    survivors, paired, toggles, dangling = pair_corrections(events)
    if counters is not None:
        for key, n in (("paired_corrections", paired), ("toggle_corrections", toggles),
                       ("dangling_corrections", dangling)):
            if n:
                counters[key] = counters.get(key, 0) + n
    by_figi: dict[str, list[MembershipEvent]] = defaultdict(list)
    for e in survivors:
        by_figi[e.composite_figi].append(e)
    return {figi: _intervals_for_figi(evs, counters) for figi, evs in by_figi.items()}


def _membership_events(
    conn: psycopg.Connection, universe_id: str, through: int | None = None
) -> list[MembershipEvent]:
    """Resolved events for a universe (join to frozen resolutions; resolved only).

    ``through`` caps the result to events with ``event_id <= through`` — the
    log-version watermark used by reproducible snapshots (Story U1.6). ``None``
    (the default) reads the full log for the latest rebuild.
    """
    sql = """
        SELECT r.composite_figi, e.change, e.effective_date, e.event_id,
               e.raw_identifier, e.source, e.provenance
          FROM membership_event e
          JOIN universe_member_resolution r
            ON r.universe_id = e.universe_id AND r.raw_identifier = e.raw_identifier
         WHERE e.universe_id = %s
           AND r.resolution_status <> 'unresolved' AND r.composite_figi IS NOT NULL
    """
    params: list[object] = [universe_id]
    if through is not None:
        sql += " AND e.event_id <= %s"
        params.append(through)
    sql += " ORDER BY e.effective_date, e.event_id"
    rows = conn.execute(sql, params).fetchall()
    return [MembershipEvent(*row) for row in rows]


@dataclass
class ProjectionSummary:
    figis: int = 0
    intervals: int = 0
    excluded_unresolved: int = 0  # log members with no resolved FIGI — absent from the read-model
    orphan_leaves: int = 0  # leaves with no open interval (join predates the log floor)
    paired_corrections: int = 0  # reverses-correctives annihilated with their target (U3.7)
    toggle_corrections: int = 0  # legacy provenance-less correctives that ran as state toggles
    dangling_corrections: int = 0  # explicit correctives naming a missing target — dropped, inert


def _excluded_unresolved(conn: psycopg.Connection, universe_id: str) -> int:
    """Distinct log members the projection cannot place (unresolved/no FIGI)."""
    row = conn.execute(
        """
        SELECT count(DISTINCT e.raw_identifier)
          FROM membership_event e
          LEFT JOIN universe_member_resolution r
            ON r.universe_id = e.universe_id AND r.raw_identifier = e.raw_identifier
         WHERE e.universe_id = %s
           AND (r.raw_identifier IS NULL OR r.resolution_status = 'unresolved'
                OR r.composite_figi IS NULL)
        """,
        (universe_id,),
    ).fetchone()
    return row[0] if row else 0


def rebuild_projection(conn: psycopg.Connection, universe_id: str) -> ProjectionSummary:
    """Rebuild a universe's ``universe_membership`` from the full ordered log.

    Deterministic full rebuild (DELETE + re-INSERT in one transaction); the
    EXCLUDE constraint is the loud backstop if the projector ever overlaps.
    Members the projection must EXCLUDE (unresolved) are counted on the summary —
    silent disappearance from the read-model is the failure mode to avoid.
    """
    counters: dict[str, int] = {}
    projected = project_membership(_membership_events(conn, universe_id), counters)
    summary = ProjectionSummary(
        excluded_unresolved=_excluded_unresolved(conn, universe_id),
        orphan_leaves=counters.get("orphan_leaves", 0),
        paired_corrections=counters.get("paired_corrections", 0),
        toggle_corrections=counters.get("toggle_corrections", 0),
        dangling_corrections=counters.get("dangling_corrections", 0),
    )
    with conn.transaction():
        conn.execute("DELETE FROM universe_membership WHERE universe_id = %s", (universe_id,))
        for figi, intervals in projected.items():
            summary.figis += 1
            for iv in intervals:
                conn.execute(
                    """
                    INSERT INTO universe_membership
                        (universe_id, composite_figi, raw_identifier, valid_from, valid_to, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (universe_id, figi, iv.raw_identifier, iv.valid_from, iv.valid_to, iv.source),
                )
                summary.intervals += 1
    return summary
