"""Daily maintenance monitor + liveness (Story U3.1, FR8/NFR2).

A per-index monitor that re-runs a universe's preferred provider, discovers
membership-change events (including leaves derived by diffing a source-declared
snapshot against currently-open members), STAGES them through the gating layer
(U3.2: churn threshold, persistence, corroboration), and promotes the ones that
have earned it to the append-only log — then re-resolves and rebuilds the
projection. It records a run-log row per run and exposes liveness so a *frozen*
universe is never mistaken for a *stable* one:

* an empty or failed provider parse is recorded as an **error**, never "no change";
* a run whose churn trips the gate is recorded as **gated** (operator review);
* ``last_successful_monitor`` / :func:`stale_monitors` drive the staleness alarm;
* a change's effective date can be aligned to the exchange calendar.

Discoveries are NEVER appended directly: ``proposed`` counts what was staged this
run, ``applied`` counts proposals promoted to the log (Story U3.5).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import psycopg

from sym.universe.gating import stage_and_promote
from sym.universe.membership_diff import diff_identifier_sets
from sym.universe.projection import MembershipEvent, pair_corrections, rebuild_projection
from sym.universe.registry import (
    CORRECT,
    CRITERIA,
    CUSTOM_LIST,
    JOIN,
    LEAVE,
    MembershipChange,
    UnknownUniverseError,
    get_provider,
)
from sym.universe.resolution import (
    make_local_resolve_fn,
    make_openfigi_resolve_fn,
    resolve_universe_members,
)

# How far back a monitor run looks for dated changes (the seed already captured
# deep history; the monitor only needs the recent tail). Constituent snapshots are
# unaffected — they always emit current members (idempotent append).
DEFAULT_MONITOR_LOOKBACK = timedelta(days=400)
# A universe whose last successful monitor is older than this is "stale".
DEFAULT_STALE_AFTER = timedelta(days=4)

MONITOR_SUCCESS = "success"
MONITOR_GATED = "gated"
MONITOR_ERROR = "error"
# Statuses that prove the monitor is ALIVE (fetched + parsed): a gated run is a
# healthy monitor doing its job, not a frozen one — it must not trip staleness.
MONITOR_LIVE_STATUSES = (MONITOR_SUCCESS, MONITOR_GATED)


@dataclass
class MonitorSummary:
    """One monitor run's outcome.

    ``joiners``/``leavers`` count DISCOVERED changes this run (staged, not
    necessarily applied); ``proposed`` = proposals staged or bumped;
    ``applied`` = proposals promoted to the event log.
    """

    universe_id: str
    status: str
    source: str | None = None
    joiners: int = 0
    leavers: int = 0
    proposed: int = 0
    applied: int = 0
    detail: str | None = None
    monitor_run_id: int | None = None


def _latest_session_on_or_before(conn: psycopg.Connection, mic: str, d: date) -> date | None:
    row = conn.execute(
        """
        SELECT max(tc.session_date)
          FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current AND tc.mic = %s AND tc.session_date <= %s
        """,
        (mic, d),
    ).fetchone()
    return row[0] if row else None


def snap_to_sessions(
    changes: Iterable[MembershipChange], session_for: Callable[[date], date | None]
) -> list[MembershipChange]:
    """Snap each change's effective date to ``session_for(date)`` (pure).

    A change reported effective on a non-trading day (or with TZ skew) is aligned
    back to the latest session on/before it. A date whose ``session_for`` is None
    (no prior session) is left unchanged.
    """
    aligned: list[MembershipChange] = []
    cache: dict[date, date | None] = {}
    for ch in changes:
        if ch.effective_date not in cache:
            cache[ch.effective_date] = session_for(ch.effective_date)
        session = cache[ch.effective_date]
        if session is not None and session != ch.effective_date:
            aligned.append(replace(ch, effective_date=session))
        else:
            aligned.append(ch)
    return aligned


def align_changes(
    conn: psycopg.Connection, changes: Iterable[MembershipChange], mic: str
) -> list[MembershipChange]:
    """Snap change effective dates to the ``mic`` exchange calendar (DB-backed)."""
    return snap_to_sessions(
        changes, lambda d: _latest_session_on_or_before(conn, mic, d)
    )


def _write_monitor_log(conn: psycopg.Connection, summary: MonitorSummary) -> int:
    row = conn.execute(
        """
        INSERT INTO universe_monitor_log
            (universe_id, source, joiners, leavers, proposed, applied, status, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING monitor_run_id
        """,
        (
            summary.universe_id, summary.source, summary.joiners, summary.leavers,
            summary.proposed, summary.applied, summary.status, summary.detail,
        ),
    ).fetchone()
    return row[0]


def _open_tokens(conn: psycopg.Connection, universe_id: str) -> set[str]:
    """Tokens currently open per the log — SAME state machine as the projection.

    (U3.7) Replays the full ordered event list through
    :func:`projection.pair_corrections` and the join/leave/toggle machine at the
    raw-token level (resolution-independent), so the monitor's idempotency guard
    and leaver diff agree with the projector about what a corrective means — a
    reversed leave reads OPEN here, exactly as it does in ``universe_membership``.
    The previous latest-change-wins shortcut read it closed, making the two state
    machines contradict each other from the first reversal on. A full-log fetch
    per run is fine at current scale (≲ a few thousand events per universe).

    This set is also the snapshot-source idempotency guard: a constituents
    snapshot re-states every member on every run with a fresh as-of date, and
    the dedupe key includes the effective date — without it, each daily monitor
    would re-stage the whole membership as 'new joiners' daily.
    """
    rows = conn.execute(
        """
        SELECT raw_identifier, change, effective_date, event_id, provenance
          FROM membership_event
         WHERE universe_id = %s
         ORDER BY effective_date, event_id
        """,
        (universe_id,),
    ).fetchall()
    events = [
        MembershipEvent("", change, effective, event_id, raw, None, provenance)
        for raw, change, effective, event_id, provenance in rows
    ]
    survivors, _paired, _toggles = pair_corrections(events)
    open_tokens: set[str] = set()
    for e in sorted(survivors, key=lambda e: (e.effective_date, e.event_id)):
        if e.change == JOIN:
            open_tokens.add(e.raw_identifier)
        elif e.change == LEAVE:
            open_tokens.discard(e.raw_identifier)
        elif e.change == CORRECT:  # unmatched/legacy corrective: per-token toggle
            if e.raw_identifier in open_tokens:
                open_tokens.discard(e.raw_identifier)
            else:
                open_tokens.add(e.raw_identifier)
    return open_tokens


def _resolver(conn: psycopg.Connection, kind: str, client: object | None):
    if kind in (CUSTOM_LIST, CRITERIA):
        return make_local_resolve_fn(conn)
    if client is None:
        from sym.identity.figi import HttpOpenFigiClient

        client = HttpOpenFigiClient(api_key=os.environ.get("OPENFIGI_API_KEY"), max_retries=6)
    return make_openfigi_resolve_fn(conn, client)


def run_monitor(
    conn: psycopg.Connection,
    universe_id: str,
    *,
    client: object | None = None,
    as_of_date: date | None = None,
    lookback: timedelta = DEFAULT_MONITOR_LOOKBACK,
) -> MonitorSummary:
    """Re-run a universe's provider, stage discoveries through gating, promote.

    Returns a :class:`MonitorSummary` and writes a ``universe_monitor_log`` row.
    An empty/failed provider is an ``error`` (never "no change"). Discovered
    changes — provider events plus leaves derived from a source-declared snapshot
    — are staged as proposals (U3.2 gating); only proposals that have persisted
    or gathered corroboration are promoted to the log, after which the projection
    is rebuilt. A churn-gated run reports status ``gated``.
    """
    import sym.universe.providers  # noqa: F401  (ensure providers self-register)

    conn.autocommit = True
    row = conn.execute(
        "SELECT kind, config, source_pref FROM universe WHERE universe_id = %s", (universe_id,)
    ).fetchone()
    if row is None:
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")
    kind, config, source_pref = row
    config = dict(config or {})
    if as_of_date is None:
        # Prefer the latest exchange session over the host clock (local-tz skew near
        # midnight would stamp events on a non-session date) when a calendar is set.
        as_of_date = date.today()
        mic = config.get("calendar_mic")
        if mic:
            as_of_date = _latest_session_on_or_before(conn, mic, as_of_date) or as_of_date
    provider_config = dict(config)
    if source_pref is not None and "source_pref" not in provider_config:
        provider_config["source_pref"] = source_pref
    # A criteria provider evaluates a rule against the DB (parity with refresh —
    # without the connection the provider constructor raises and the universe is
    # unmonitorable).
    if kind == CRITERIA:
        provider_config["conn"] = conn

    try:
        provider = get_provider(kind, **provider_config)
        changes = list(provider.members(as_of_date - lookback, as_of_date))
    except Exception as exc:  # noqa: BLE001 - any provider failure is a loud error row
        summary = MonitorSummary(universe_id, MONITOR_ERROR, detail=str(exc)[:500])
        summary.monitor_run_id = _write_monitor_log(conn, summary)
        return summary

    if not changes:
        # An empty parse is an error, NEVER silently "no change" (NFR2).
        summary = MonitorSummary(
            universe_id, MONITOR_ERROR, detail="provider produced no changes (empty/garbled)"
        )
        summary.monitor_run_id = _write_monitor_log(conn, summary)
        return summary

    calendar_mic = config.get("calendar_mic")
    if calendar_mic:
        changes = align_changes(conn, changes, calendar_mic)

    source = changes[0].source.split(":")[0]
    # Idempotency vs snapshot re-statement: a join for an already-open member (or a
    # leave for a not-open one) is the provider re-stating current membership with a
    # fresh date, not a change — staging it would mint phantom proposals daily and
    # make the joiner/leaver counts meaningless.
    open_tokens = _open_tokens(conn, universe_id)
    discovered: list[MembershipChange] = []
    for ch in changes:
        if ch.change == JOIN and ch.raw_identifier in open_tokens:
            continue
        if ch.change == LEAVE and ch.raw_identifier not in open_tokens:
            continue
        discovered.append(ch)

    # Leaver derivation (U3.5): only a source that DECLARED a full current snapshot
    # lets absence mean departure — open members missing from it become leave
    # candidates. No declaration (a dated-history feed) means no derivation:
    # absence from an event list says nothing about membership.
    # An empty declared snapshot is treated like no declaration — "every member
    # left" must never be inferred from an empty parse (sources declare None for
    # empty, but the guard is deliberate either way).
    snapshot = getattr(provider, "last_snapshot_tokens", None)
    if snapshot:
        # A genuine leaver can arrive twice in one run: as a dated provider event
        # AND as absence from the snapshot (the FMP shape). Count it once.
        already_leaving = {ch.raw_identifier for ch in discovered if ch.change == LEAVE}
        derived = diff_identifier_sets(
            open_tokens, set(snapshot), as_of_date, changes[0].source
        )
        discovered.extend(
            ch for ch in derived
            if ch.change == LEAVE and ch.raw_identifier not in already_leaving
        )

    joiners = sum(1 for ch in discovered if ch.change == JOIN)
    leavers = sum(1 for ch in discovered if ch.change == LEAVE)

    # Two-stage application (U3.2, wired here): discoveries are staged as proposals
    # — churn-gated, promoted only on persistence/corroboration — never appended
    # directly. Promotion runs even with zero discoveries so yesterday's proposals
    # graduate on schedule.
    staged, promoted = stage_and_promote(
        conn, universe_id, discovered,
        current_count=len(open_tokens), as_of_date=as_of_date,
    )
    if promoted:
        resolve_universe_members(conn, universe_id, _resolver(conn, kind, client))
        rebuild_projection(conn, universe_id)

    summary = MonitorSummary(
        universe_id,
        MONITOR_GATED if staged.surprising else MONITOR_SUCCESS,
        source=source,
        joiners=joiners,
        leavers=leavers,
        proposed=staged.staged + staged.updated,
        applied=promoted,
    )
    summary.monitor_run_id = _write_monitor_log(conn, summary)
    return summary


def last_successful_monitor(conn: psycopg.Connection, universe_id: str) -> datetime | None:
    """The most recent LIVE monitor run for a universe (None if never).

    "Live" = the provider fetched and parsed (``success`` or ``gated``) — a
    churn-gated run pending operator review is a working monitor, not a frozen
    one, and must not double-alarm as stale. Only ``error`` runs don't count.
    """
    row = conn.execute(
        """
        SELECT max(run_at) FROM universe_monitor_log
         WHERE universe_id = %s AND status = ANY(%s)
        """,
        (universe_id, list(MONITOR_LIVE_STATUSES)),
    ).fetchone()
    return row[0] if row else None


def stale_monitors(
    conn: psycopg.Connection,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
    kinds: Sequence[str] = ("index",),
) -> list[tuple[str, datetime | None]]:
    """Monitorable universes whose last LIVE monitor run is missing or too old.

    Returns ``(universe_id, last_success)`` pairs — ``last_success`` is None for a
    universe that has never had a live (``success``/``gated``) monitor run; a
    gated run counts as alive (see :func:`last_successful_monitor`).
    """
    from datetime import UTC

    now = now or datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT u.universe_id,
               (SELECT max(m.run_at) FROM universe_monitor_log m
                 WHERE m.universe_id = u.universe_id AND m.status = ANY(%s)) AS last_success
          FROM universe u
         WHERE u.kind = ANY(%s)
         ORDER BY u.universe_id
        """,
        (list(MONITOR_LIVE_STATUSES), list(kinds)),
    ).fetchall()
    stale: list[tuple[str, datetime | None]] = []
    for universe_id, last_success in rows:
        if last_success is None or (now - last_success) > stale_after:
            stale.append((universe_id, last_success))
    return stale
