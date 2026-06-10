"""Sanity-gating, corroboration, and reversible audit (Story U3.2, AR-9 two-stage).

Monitor-discovered changes are not trusted blindly. They are *staged* as
proposals, and only promoted to the append-only event log when they earn it:

* **sanity-gating** — a run whose churn exceeds a guard threshold is flagged for
  review (``reason='churn_threshold'``), never auto-applied (a bad parse or
  vandalised source can't silently rewrite a universe);
* **corroboration / persistence** — an ordinary change must persist N days OR be
  confirmed by a second source before it is recorded;
* **reversible audit** — a change later found wrong is reversed by an *appended*
  corrective (``change='correct'``) event, never a destructive edit.

The staging table (``membership_proposal``) is mutable; the event log it feeds
stays append-only.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from sym.universe.events import append_change
from sym.universe.registry import CORRECT, POLL_BOUNDED, MembershipChange

# Defaults (tunable). Churn above this fraction of current membership is gated.
DEFAULT_CHURN_THRESHOLD = 0.10
DEFAULT_PERSIST_DAYS = 2
DEFAULT_MIN_CORROBORATIONS = 2

REASON_CHURN = "churn_threshold"
REASON_PERSIST = "awaiting_persistence"

PENDING = "pending"
CONFIRMED = "confirmed"
REJECTED = "rejected"


# --- pure decision logic ----------------------------------------------------


def churn_ratio(change_count: int, current_count: int) -> float:
    """Discovered-changes as a fraction of current membership (≥1 denominator)."""
    return change_count / max(current_count, 1)


def is_surprising(
    change_count: int, current_count: int, threshold: float = DEFAULT_CHURN_THRESHOLD
) -> bool:
    """True if this run's churn exceeds the guard threshold (→ gate for review)."""
    return churn_ratio(change_count, current_count) > threshold


def is_promotable(
    reason: str,
    first_seen: date,
    last_seen: date,
    corroboration_count: int,
    *,
    persist_days: int = DEFAULT_PERSIST_DAYS,
    min_corroborations: int = DEFAULT_MIN_CORROBORATIONS,
) -> bool:
    """Whether a pending proposal may be auto-promoted to the event log.

    Churn-gated proposals always need an operator (never auto-promote). Others
    promote once they have persisted ``persist_days`` — meaning the change was
    STILL BEING SEEN at the end of the window (``last_seen``), not merely first
    sighted N days ago (a one-shot vendor glitch never re-seen must not
    auto-promote by aging alone) — or gathered ``min_corroborations`` distinct
    sources.
    """
    if reason == REASON_CHURN:
        return False
    persisted = (last_seen - first_seen).days >= persist_days
    corroborated = corroboration_count >= min_corroborations
    return persisted or corroborated


# --- staging (DB) -----------------------------------------------------------


@dataclass
class StageSummary:
    staged: int = 0
    updated: int = 0
    surprising: bool = False  # this run tripped the churn gate (everything held for review)


def stage_changes(
    conn: psycopg.Connection,
    universe_id: str,
    changes: Iterable[MembershipChange],
    *,
    as_of_date: date,
    surprising: bool,
) -> StageSummary:
    """Upsert discovered changes into the proposal staging table.

    First sighting inserts a pending proposal (``first_seen=as_of_date``); a repeat
    sighting bumps ``seen_count``/``last_seen`` and records the source as a
    corroboration (a *different* source seeing the same change is what
    corroboration means). Surprising runs stamp ``reason='churn_threshold'``.

    A POLL_BOUNDED re-sighting matches its pending proposal by the
    ``(universe, raw_identifier, change)`` TRIPLE — its effective date shifts with
    every poll, so the quad dedupe key alone would mint a new proposal row daily
    and persistence would never accrue. EXACT-dated changes keep the quad key.
    """
    reason = REASON_CHURN if surprising else REASON_PERSIST
    summary = StageSummary(surprising=surprising)
    for ch in changes:
        if ch.effective_date_precision == POLL_BOUNDED:
            touched = conn.execute(
                """
                UPDATE membership_proposal
                   SET last_seen_date = %s,
                       seen_count = seen_count + 1,
                       corroborating_sources = CASE
                           WHEN corroborating_sources @> %s THEN corroborating_sources
                           ELSE corroborating_sources || %s END
                 WHERE universe_id = %s AND raw_identifier = %s
                   AND change = %s AND status = 'pending'
                RETURNING proposal_id
                """,
                (
                    as_of_date, Jsonb([ch.source]), Jsonb([ch.source]),
                    universe_id, ch.raw_identifier, ch.change,
                ),
            ).fetchone()
            if touched is not None:
                summary.updated += 1
                continue
        inserted = conn.execute(
            """
            INSERT INTO membership_proposal
                (universe_id, raw_identifier, change, effective_date,
                 effective_date_precision, source, first_seen_date, last_seen_date,
                 corroborating_sources, status, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
            ON CONFLICT (universe_id, raw_identifier, change, effective_date) DO NOTHING
            RETURNING proposal_id
            """,
            (
                universe_id, ch.raw_identifier, ch.change, ch.effective_date,
                ch.effective_date_precision, ch.source, as_of_date, as_of_date,
                Jsonb([ch.source]), reason,
            ),
        ).fetchone()
        if inserted is not None:
            summary.staged += 1
            continue
        # Already staged: bump persistence + record a corroborating source. The count
        # reflects rows actually touched — a re-sighting of an already-DECIDED
        # (confirmed/rejected) proposal matches nothing and must not report as updated.
        touched = conn.execute(
            """
            UPDATE membership_proposal
               SET last_seen_date = %s,
                   seen_count = seen_count + 1,
                   corroborating_sources = CASE
                       WHEN corroborating_sources @> %s THEN corroborating_sources
                       ELSE corroborating_sources || %s END
             WHERE universe_id = %s AND raw_identifier = %s
               AND change = %s AND effective_date = %s AND status = 'pending'
            RETURNING proposal_id
            """,
            (
                as_of_date, Jsonb([ch.source]), Jsonb([ch.source]),
                universe_id, ch.raw_identifier, ch.change, ch.effective_date,
            ),
        ).fetchone()
        if touched is not None:
            summary.updated += 1
    return summary


def _corroboration_count(corroborating_sources: object) -> int:
    return len(corroborating_sources) if isinstance(corroborating_sources, list) else 0


def promote_ready_proposals(
    conn: psycopg.Connection,
    universe_id: str,
    *,
    as_of_date: date,
    persist_days: int = DEFAULT_PERSIST_DAYS,
    min_corroborations: int = DEFAULT_MIN_CORROBORATIONS,
) -> int:
    """Append pending proposals that have earned promotion; mark them confirmed.

    Returns the number promoted. Churn-gated proposals are skipped (operator-only).
    Promotion appends to the event log (idempotent) then sets ``status=confirmed``.
    """
    rows = conn.execute(
        """
        SELECT proposal_id, raw_identifier, change, effective_date,
               effective_date_precision, source, reason, first_seen_date, last_seen_date,
               corroborating_sources
          FROM membership_proposal
         WHERE universe_id = %s AND status = 'pending'
        """,
        (universe_id,),
    ).fetchall()
    promoted = 0
    for (pid, raw, change, eff, precision, source, reason, first_seen, last_seen, corr) in rows:
        if not is_promotable(
            reason, first_seen, last_seen or first_seen, _corroboration_count(corr),
            persist_days=persist_days, min_corroborations=min_corroborations,
        ):
            continue
        append_change(
            conn, universe_id,
            MembershipChange(raw, change, eff, source, precision),
            provenance={"promoted_from_proposal": pid, "reason": reason},
        )
        conn.execute(
            """
            UPDATE membership_proposal
               SET status = 'confirmed', decided_at = now(), decided_by = 'auto'
             WHERE proposal_id = %s
            """,
            (pid,),
        )
        promoted += 1
    return promoted


def pending_proposals(conn: psycopg.Connection, universe_id: str | None = None) -> list[dict]:
    """Pending proposals (optionally for one universe) for the review digest."""
    sql = (
        "SELECT proposal_id, universe_id, raw_identifier, change, effective_date, "
        "source, first_seen_date, seen_count, corroborating_sources, reason "
        "FROM membership_proposal WHERE status = 'pending'"
    )
    params: list[object] = []
    if universe_id is not None:
        sql += " AND universe_id = %s"
        params.append(universe_id)
    sql += " ORDER BY universe_id, effective_date, raw_identifier"
    cols = [
        "proposal_id", "universe_id", "raw_identifier", "change", "effective_date",
        "source", "first_seen_date", "seen_count", "corroborating_sources", "reason",
    ]
    return [dict(zip(cols, row, strict=True)) for row in conn.execute(sql, params).fetchall()]


def _resolve_and_rebuild(conn: psycopg.Connection, universe_id: str) -> None:
    """Re-project after an append so the change becomes VISIBLE (U3.5, AC 4/5).

    An appended event only exists in the log until ``universe_membership`` is
    rebuilt — without this, a confirm/reverse "succeeds" but ``sym universe show``
    keeps serving the old membership. Resolution is local-only (no network): the
    affected tokens are almost always already-resolved members; a genuinely new
    token resolves on the next refresh.
    """
    # Imported lazily: resolution/projection import the registry, and a module-level
    # import here would create a cycle once they grow gating-aware.
    from sym.universe.projection import rebuild_projection
    from sym.universe.resolution import make_local_resolve_fn, resolve_universe_members

    resolve_universe_members(conn, universe_id, make_local_resolve_fn(conn))
    rebuild_projection(conn, universe_id)


def _proposal(conn: psycopg.Connection, proposal_id: int) -> tuple | None:
    return conn.execute(
        """
        SELECT universe_id, raw_identifier, change, effective_date,
               effective_date_precision, source, status
          FROM membership_proposal WHERE proposal_id = %s
        """,
        (proposal_id,),
    ).fetchone()


def confirm_proposal(conn: psycopg.Connection, proposal_id: int, *, by: str = "operator") -> bool:
    """Operator confirm: append the change to the log, mark the proposal confirmed."""
    row = _proposal(conn, proposal_id)
    if row is None or row[6] != PENDING:
        return False
    universe_id, raw, change, eff, precision, source, _status = row
    append_change(
        conn, universe_id, MembershipChange(raw, change, eff, source, precision),
        provenance={"confirmed_proposal": proposal_id, "by": by},
    )
    conn.execute(
        "UPDATE membership_proposal SET status='confirmed', decided_at=now(), decided_by=%s "
        "WHERE proposal_id = %s",
        (by, proposal_id),
    )
    _resolve_and_rebuild(conn, universe_id)
    return True


def reject_proposal(conn: psycopg.Connection, proposal_id: int, *, by: str = "operator") -> bool:
    """Operator reject: record the rejection (never appended to the log)."""
    row = _proposal(conn, proposal_id)
    if row is None or row[6] != PENDING:
        return False
    conn.execute(
        "UPDATE membership_proposal SET status='rejected', decided_at=now(), decided_by=%s "
        "WHERE proposal_id = %s",
        (by, proposal_id),
    )
    return True


def reverse_change(
    conn: psycopg.Connection,
    universe_id: str,
    raw_identifier: str,
    change: str,
    effective_date: date,
    *,
    source: str = "review",
    by: str = "operator",
    detail: str | None = None,
) -> bool:
    """Reverse a recorded change by appending a corrective ``correct`` event.

    A ``correct`` event at the wrong change's effective date toggles the interval
    state machine (closing a wrongly-opened membership, or re-opening a wrongly-
    closed one) — a reversible, appended audit trail, never a destructive edit.
    Returns True if the corrective was newly appended.
    """
    appended = append_change(
        conn, universe_id,
        MembershipChange(raw_identifier, CORRECT, effective_date, source),
        provenance={"reverses": change, "by": by, "detail": detail},
    )
    if appended:
        _resolve_and_rebuild(conn, universe_id)
    return appended


def stage_and_promote(
    conn: psycopg.Connection,
    universe_id: str,
    changes: Sequence[MembershipChange],
    *,
    current_count: int,
    as_of_date: date,
    threshold: float = DEFAULT_CHURN_THRESHOLD,
    persist_days: int = DEFAULT_PERSIST_DAYS,
    min_corroborations: int = DEFAULT_MIN_CORROBORATIONS,
) -> tuple[StageSummary, int]:
    """Stage discovered changes (gating on churn) then promote the ready ones."""
    surprising = is_surprising(len(changes), current_count, threshold)
    staged = stage_changes(conn, universe_id, changes, as_of_date=as_of_date, surprising=surprising)
    promoted = 0
    if not surprising:
        promoted = promote_ready_proposals(
            conn, universe_id, as_of_date=as_of_date,
            persist_days=persist_days, min_corroborations=min_corroborations,
        )
    return staged, promoted
