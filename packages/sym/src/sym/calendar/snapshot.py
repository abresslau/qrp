"""Snapshot exchange_calendars into the versioned ``trading_calendar`` table (Story 2.1, AR-4).

The returns engine must read trading days from a stable, versioned DB table -- never
the live library -- so window anchoring is reproducible and ``calendar_version`` can
participate in ``fact_returns.input_hash`` (AR-7). This module mirrors the
``classification/gics.py`` shape: the external dependency sits behind a
:class:`CalendarSource` protocol, the decision logic is a pure :func:`plan_snapshot`,
and :func:`apply_snapshot` does the writes one transaction per exchange.

Versioning (AC #3): ``content_hash = sha256(library_version + ordered sessions)`` per
MIC. A re-snapshot whose hash matches the current version is a no-op; a differing hash
inserts a NEW ``calendar_version`` and flips the prior ``is_current`` off. Prior
versions and their session rows are never mutated -- immutable history, so a
``fact_returns`` row stays reproducible against the calendar it was computed under.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import psycopg

# Equity history rarely needs sessions before this; clamped per-calendar anyway.
DEFAULT_START = date(1990, 1, 1)

# plan outcomes
NEW = "new"
UNCHANGED = "unchanged"
UNKNOWN_MIC = "unknown_mic"
EMPTY = "empty"


def content_hash(library_version: str, sessions: Sequence[date]) -> str:
    """Deterministic hash of a MIC's snapshot: library version + ordered session dates.

    Identical inputs always hash identically (idempotent re-snapshot); any change to
    the session set -- or the library version -- yields a different hash (new version).
    """
    digest = hashlib.sha256()
    digest.update(library_version.encode("utf-8"))
    for session in sessions:
        digest.update(b"\x00")
        digest.update(session.isoformat().encode("ascii"))
    return digest.hexdigest()


class CalendarSource(Protocol):
    """Supplies trading sessions per MIC, isolating the exchange_calendars dependency."""

    @property
    def library_version(self) -> str: ...

    def sessions(self, mic: str, start: date, end: date) -> list[date] | None:
        """Open trading days for ``mic`` in ``[start, end]``, or None if the MIC is unknown."""
        ...


class ExchangeCalendarsSource:
    """Trading sessions from the ``exchange_calendars`` library, keyed by ISO MIC.

    A MIC the library doesn't know returns ``None`` (the loader records it rather than
    failing). Requested bounds are clamped to each calendar's available range.
    """

    def __init__(self) -> None:
        import exchange_calendars as xcals

        self._xcals = xcals
        self._known = set(xcals.get_calendar_names())

    @property
    def library_version(self) -> str:
        return self._xcals.__version__

    def sessions(self, mic: str, start: date, end: date) -> list[date] | None:
        if mic not in self._known:
            return None
        import pandas as pd

        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        cal = self._calendar_within_bounds(mic, start_ts, end_ts)
        if cal is None:
            return None
        lo = max(start_ts, cal.first_session)
        hi = min(end_ts, cal.last_session)
        if lo > hi:
            return []
        return [ts.date() for ts in cal.sessions_in_range(lo, hi)]

    @staticmethod
    def _bound(calendar_cls: Any, name: str) -> Any:
        """A calendar class's hard ``bound_min``/``bound_max`` Timestamp, or None."""
        getter = getattr(calendar_cls, name, None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:  # noqa: BLE001 - treat an unavailable bound as unbounded
            return None

    def _calendar_within_bounds(self, mic: str, start_ts, end_ts):
        """Instantiate a calendar over the widest window the library actually supports.

        exchange_calendars defaults a calendar to only ~20 years, so start/end must
        be passed explicitly or long-window returns (10Y/20Y/30Y) would have no
        calendar. Each calendar also has hard ``bound_min``/``bound_max`` (e.g. XTKS
        from 1997, XBOM only through 2026). Clamp the requested window to those true
        bounds -- NOT the library's 20-year default -- so we get the full available
        history (the Story 2.1 fix: XTKS/XSHG/XBOM stopped at 2006 before this).
        """
        get = self._xcals.get_calendar
        try:
            default = get(mic)  # the 20-year default window always instantiates
        except Exception:  # noqa: BLE001
            return None
        calendar_cls = type(default)
        bound_min = self._bound(calendar_cls, "bound_min")
        bound_max = self._bound(calendar_cls, "bound_max")
        lo = start_ts if bound_min is None else max(start_ts, bound_min)
        hi = end_ts if bound_max is None else min(end_ts, bound_max)
        # Try the bound-clamped window; if a bound still trips, relax the offending
        # side. NEVER fall back to the bare 20-year default ({}): a truncated
        # calendar hashes differently and would be minted as a NEW current version,
        # silently demoting the full-history one. Total failure -> None (recorded
        # as a failed MIC), per this docstring's own promise.
        for kwargs in ({"start": lo, "end": hi}, {"start": lo}, {"end": hi}):
            try:
                return get(mic, **kwargs)
            except ValueError:
                continue
        return None


@dataclass(frozen=True)
class CalendarSnapshot:
    """The planned outcome for one MIC (no DB writes yet)."""

    mic: str
    outcome: str
    library_version: str | None = None
    content_hash: str | None = None
    sessions: tuple[date, ...] = ()


@dataclass
class SnapshotSummary:
    """What a snapshot run did across the requested MICs."""

    requested: int = 0
    versions_written: int = 0
    unchanged: int = 0
    unknown_mic: int = 0
    empty: int = 0
    failed: int = 0
    sessions_written: int = 0
    unknown_mics: list[str] = field(default_factory=list)


def plan_snapshot(
    source: CalendarSource,
    mics: Sequence[str],
    *,
    start: date,
    end: date,
    current_hashes: dict[str, str],
) -> list[CalendarSnapshot]:
    """Classify each MIC against the stored current hashes (pure; no DB writes).

    ``current_hashes`` maps a MIC to the ``content_hash`` of its currently-effective
    version. A MIC whose freshly-computed hash matches is ``unchanged``; otherwise
    ``new``. Unknown / empty MICs are flagged without raising.
    """
    library_version = source.library_version
    plans: list[CalendarSnapshot] = []
    for mic in mics:
        sessions = source.sessions(mic, start, end)
        if sessions is None:
            plans.append(CalendarSnapshot(mic, UNKNOWN_MIC))
            continue
        if not sessions:
            plans.append(CalendarSnapshot(mic, EMPTY))
            continue
        chash = content_hash(library_version, sessions)
        outcome = UNCHANGED if current_hashes.get(mic) == chash else NEW
        plans.append(
            CalendarSnapshot(mic, outcome, library_version, chash, tuple(sessions))
        )
    return plans


def read_current_hashes(conn: psycopg.Connection, mics: Sequence[str]) -> dict[str, str]:
    """Map each MIC to its currently-effective version's ``content_hash`` (if any)."""
    rows = conn.execute(
        """
        SELECT mic, content_hash
          FROM trading_calendar_version
         WHERE is_current
           AND mic = ANY(%s)
        """,
        (list(mics),),
    ).fetchall()
    return {mic: chash for mic, chash in rows}


def _write_sessions(
    conn: psycopg.Connection, calendar_version: int, mic: str, sessions: Sequence[date]
) -> None:
    """Bulk-load a version's sessions via COPY (fast for the ~10k rows/exchange)."""
    with conn.cursor() as cur:
        with cur.copy(
            "COPY trading_calendar (calendar_version, mic, session_date) FROM STDIN"
        ) as copy:
            for session in sessions:
                copy.write_row((calendar_version, mic, session))


def apply_snapshot(
    conn: psycopg.Connection, plans: Sequence[CalendarSnapshot]
) -> SnapshotSummary:
    """Persist the planned snapshots: one transaction per MIC, error-isolated.

    Only ``new`` plans write: the prior current version (if any) is flipped to
    ``is_current = FALSE``, a fresh version row is inserted, and its sessions are
    COPYed in. ``unchanged`` / ``unknown_mic`` / ``empty`` are counted only. A single
    MIC's failure is rolled back, counted, and never halts the rest.
    """
    summary = SnapshotSummary(requested=len(plans))
    for plan in plans:
        if plan.outcome == UNCHANGED:
            summary.unchanged += 1
            continue
        if plan.outcome == UNKNOWN_MIC:
            summary.unknown_mic += 1
            summary.unknown_mics.append(plan.mic)
            continue
        if plan.outcome == EMPTY:
            summary.empty += 1
            continue
        try:
            with conn.transaction():
                # Serialize per MIC: when no prior version row exists there is nothing
                # for the UPDATE to lock, and two concurrent first snapshots would both
                # insert is_current=TRUE (every is_current join then becomes ambiguous).
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('calendar_snapshot_' || %s))",
                    (plan.mic,),
                )
                conn.execute(
                    """
                    UPDATE trading_calendar_version
                       SET is_current = FALSE
                     WHERE mic = %s
                       AND is_current
                    """,
                    (plan.mic,),
                )
                row = conn.execute(
                    """
                    INSERT INTO trading_calendar_version
                        (mic, library_version, content_hash,
                         session_count, first_session_date, last_session_date, is_current)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                    RETURNING calendar_version
                    """,
                    (
                        plan.mic,
                        plan.library_version,
                        plan.content_hash,
                        len(plan.sessions),
                        plan.sessions[0],
                        plan.sessions[-1],
                    ),
                ).fetchone()
                calendar_version = row[0]
                _write_sessions(conn, calendar_version, plan.mic, plan.sessions)
                summary.versions_written += 1
                summary.sessions_written += len(plan.sessions)
        except psycopg.Error:
            summary.failed += 1
    return summary


def snapshot_calendars(
    conn: psycopg.Connection,
    source: CalendarSource,
    mics: Sequence[str],
    *,
    start: date = DEFAULT_START,
    end: date,
) -> SnapshotSummary:
    """Snapshot each MIC's calendar into ``trading_calendar``, versioning on drift."""
    current = read_current_hashes(conn, mics)
    plans = plan_snapshot(source, mics, start=start, end=end, current_hashes=current)
    return apply_snapshot(conn, plans)


def read_exchange_mics(conn: psycopg.Connection) -> list[str]:
    """All MICs in the exchange reference table (the snapshot scope)."""
    rows = conn.execute("SELECT mic FROM exchange ORDER BY mic").fetchall()
    return [mic for (mic,) in rows]


def current_calendar_version(conn: psycopg.Connection, mic: str) -> int | None:
    """The currently-effective ``calendar_version`` for an exchange (DB is the read source)."""
    row = conn.execute(
        "SELECT calendar_version FROM trading_calendar_version WHERE mic = %s AND is_current",
        (mic,),
    ).fetchone()
    return row[0] if row else None


def is_trading_day(conn: psycopg.Connection, mic: str, day: date) -> bool:
    """Whether ``day`` is an open session on ``mic`` per its current calendar version."""
    row = conn.execute(
        """
        SELECT 1
          FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current
           AND tc.mic = %s
           AND tc.session_date = %s
        """,
        (mic, day),
    ).fetchone()
    return row is not None
