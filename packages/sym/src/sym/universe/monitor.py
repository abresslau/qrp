"""Daily maintenance monitor + liveness (Story U3.1, FR8/NFR2).

A per-index monitor that re-runs a universe's preferred provider, discovers
membership-change events, appends the genuinely-new ones to the log (idempotent —
re-running the same day is a no-op), re-resolves, and rebuilds the projection. It
records a run-log row per run and exposes liveness so a *frozen* universe is never
mistaken for a *stable* one:

* an empty or failed provider parse is recorded as an **error**, never "no change";
* ``last_successful_monitor`` / :func:`stale_monitors` drive the staleness alarm;
* a change's effective date can be aligned to the exchange calendar.

The gating/corroboration layer (U3.2) sits between "discovered" and "appended";
this story records discoveries directly (``applied``), leaving ``proposed`` at 0.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import psycopg

from sym.universe.events import append_change
from sym.universe.projection import rebuild_projection
from sym.universe.registry import (
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


@dataclass
class MonitorSummary:
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


def _resolver(conn: psycopg.Connection, kind: str, client: object | None):
    if kind == CUSTOM_LIST:
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
    today: date | None = None,
    lookback: timedelta = DEFAULT_MONITOR_LOOKBACK,
) -> MonitorSummary:
    """Re-run a universe's provider, append new changes, refresh the projection.

    Returns a :class:`MonitorSummary` and writes a ``universe_monitor_log`` row.
    An empty/failed provider is an ``error`` (never "no change"); discovered
    changes are appended directly (``applied``) — gating is layered in U3.2.
    """
    import sym.universe.providers  # noqa: F401  (ensure providers self-register)

    conn.autocommit = True
    today = today or date.today()
    row = conn.execute(
        "SELECT kind, config, source_pref FROM universe WHERE universe_id = %s", (universe_id,)
    ).fetchone()
    if row is None:
        raise UnknownUniverseError(f"unknown universe {universe_id!r}")
    kind, config, source_pref = row
    config = dict(config or {})
    provider_config = dict(config)
    if source_pref is not None and "source_pref" not in provider_config:
        provider_config["source_pref"] = source_pref

    try:
        provider = get_provider(kind, **provider_config)
        changes = list(provider.members(today - lookback, today))
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
    joiners = leavers = 0
    for ch in changes:
        if append_change(conn, universe_id, ch):  # True only if newly inserted
            if ch.change == JOIN:
                joiners += 1
            elif ch.change == LEAVE:
                leavers += 1

    if joiners or leavers:
        resolve_universe_members(conn, universe_id, _resolver(conn, kind, client))
        rebuild_projection(conn, universe_id)

    summary = MonitorSummary(
        universe_id,
        MONITOR_SUCCESS,
        source=source,
        joiners=joiners,
        leavers=leavers,
        applied=joiners + leavers,
    )
    summary.monitor_run_id = _write_monitor_log(conn, summary)
    return summary


def last_successful_monitor(conn: psycopg.Connection, universe_id: str) -> datetime | None:
    """The most recent successful monitor run for a universe (None if never)."""
    row = conn.execute(
        """
        SELECT max(run_at) FROM universe_monitor_log
         WHERE universe_id = %s AND status = %s
        """,
        (universe_id, MONITOR_SUCCESS),
    ).fetchone()
    return row[0] if row else None


def stale_monitors(
    conn: psycopg.Connection,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
    kinds: Sequence[str] = ("index",),
) -> list[tuple[str, datetime | None]]:
    """Monitorable universes whose last successful monitor is missing or too old.

    Returns ``(universe_id, last_success)`` pairs — ``last_success`` is None for a
    universe that has never had a successful monitor run.
    """
    from datetime import UTC

    now = now or datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT u.universe_id,
               (SELECT max(m.run_at) FROM universe_monitor_log m
                 WHERE m.universe_id = u.universe_id AND m.status = %s) AS last_success
          FROM universe u
         WHERE u.kind = ANY(%s)
         ORDER BY u.universe_id
        """,
        (MONITOR_SUCCESS, list(kinds)),
    ).fetchall()
    stale: list[tuple[str, datetime | None]] = []
    for universe_id, last_success in rows:
        if last_success is None or (now - last_success) > stale_after:
            stale.append((universe_id, last_success))
    return stale
