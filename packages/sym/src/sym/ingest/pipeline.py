"""Three-phase load orchestration (Story 2.5, FR-6 / AR-13).

Drives the source adapter (Story 2.2) + atomic writer (Story 2.3/2.4) across the
active universe in one of two modes (the unified `sym load` CLI maps its flags onto
these via :func:`plan_load` — see Story 2.11):

* ``fill``     — add only missing bars. *Forward* (the daily case): only sessions
                 since each cursor, so a second fill mutates nothing (`sym load`).
                 *Gap-aware* (``gap_aware=True``): re-fetch from an explicit floor to
                 fill history below the stored cursor too (`sym load --start_date`).
* ``overwrite`` — re-fetch and REPLACE the stored bars in an explicit window, other
                 dates untouched (the empty-fetch guard skips the delete if the
                 re-fetch is empty). (`sym load --overwrite --start_date`.)

Each security loads in its own durable transaction (``conn.autocommit = True`` so a
per-figi ``conn.transaction()`` is a top-level commit, never a savepoint) and a
single failure is marked ``error`` and skipped — the cursor never advances without
rows, and one bad name never halts the run.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg

from sym.ingest.prices import expected_trading_days, ingest_result
from sym.sources.contract import OhlcvResult

# The two load modes. `fill` adds only missing bars (forward from each cursor for the daily
# `load`, or gap-aware from an explicit floor for `load --start_date`); `overwrite` re-fetches
# and REPLACES the stored bars in an explicit window (`load --overwrite --start_date …`).
FILL = "fill"
OVERWRITE = "overwrite"

DEFAULT_FLOOR = date(1990, 1, 1)
# A faithful re-fetch reproduces stored raw exactly; anything past this relative
# gap is a genuine source-side correction, not float noise.
DIVERGENCE_TOLERANCE = Decimal("0.001")


def compute_window(
    mode: str,
    cursor_date: date | None,
    *,
    floor: date,
    end_date: date | None,
    gap_aware: bool = False,
    floor_reached: date | None = None,
    overwrite_start_date: date | None = None,
) -> tuple[date, date] | None:
    """The [start_date, end_date] sessions to fetch for one security, or None to skip it.

    ``end_date`` is the latest available session (from the calendar, not the clock).

    A ``fill`` is either **forward** (the daily case: only the new tail since the
    cursor) or **gap-aware** (a backfill from an explicit floor). The forward cursor
    only tracks the *latest* loaded session, so a name first loaded from a late
    start_date (e.g. an index member loaded from its membership-join date) looks
    "complete" even though its history below the earliest stored bar was never
    fetched — so ``gap_aware`` re-examines history. ``floor_reached`` records the
    deepest floor a prior gap-aware fill actually requested; it skips a name only
    when ``floor_reached <= floor`` (we already asked at least this deep and got
    whatever exists — even if the data starts at a later IPO) AND the cursor is
    current. Otherwise it re-fetches ``[floor, end_date]`` and immutable ingestion
    inserts only the missing bars.
    """
    if end_date is None:
        return None
    if mode == OVERWRITE:
        # Explicit operator-chosen window; cursor-independent (we WANT to re-fetch even
        # when current). `end_date` is already clamped to the latest session <= end_date.
        if overwrite_start_date is None or overwrite_start_date > end_date:
            return None
        return (overwrite_start_date, end_date)
    if mode != FILL:
        raise ValueError(f"unknown load mode {mode!r}")
    if gap_aware:
        if floor > end_date:
            return None
        is_current = cursor_date is not None and cursor_date >= end_date
        reached_floor = floor_reached is not None and floor_reached <= floor
        if is_current and reached_floor:
            return None  # already fetched down to (at least) this floor and current
        return (floor, end_date)
    # Forward fill (daily): only the new tail since the cursor.
    if cursor_date is not None and cursor_date >= end_date:
        return None  # up-to-date -> skip (resume + idempotency: a second fill mutates nothing)
    start_date = cursor_date + timedelta(days=1) if cursor_date is not None else floor
    if start_date > end_date:
        return None
    return (start_date, end_date)


def plan_load(*, start_date: date | None, overwrite: bool) -> tuple[str, bool]:
    """The ``(mode, gap_aware)`` implied by the unified `sym load` flags.

    ``overwrite`` → ``(OVERWRITE, False)`` — re-fetch and replace the window (requires an
    explicit ``start_date``, caller-validated). Otherwise it is a ``FILL``: an explicit
    ``start_date`` → gap-aware backfill from that floor; no ``start_date`` → forward from
    each cursor (the daily case).
    """
    if overwrite:
        return OVERWRITE, False
    return FILL, start_date is not None


def fetch_with_retry(
    source: object,
    figi: str,
    start_date: date,
    end_date: date,
    *,
    retries: int = 3,
    base: float = 1.0,
    cap: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> OhlcvResult:
    """Fetch with capped exponential backoff + jitter, then re-raise (AR-13 429)."""
    if retries < 1:
        raise ValueError(f"retries must be >= 1, got {retries}")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return source.fetch_ohlcv(figi, start_date, end_date)
        except Exception as exc:  # noqa: BLE001 - transient vendor/network failures
            last = exc
            if attempt < retries - 1:
                delay = min(base * (2**attempt), cap)
                sleep(delay + delay * 0.1 * attempt)  # mild jitter, deterministic
    assert last is not None
    raise last


@dataclass
class LoadSummary:
    """What a load run did across the universe."""

    mode: str
    attempted: int = 0
    loaded: int = 0
    skipped: int = 0
    errored: int = 0
    rows: int = 0
    flags: int = 0
    gaps: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    run_id: int | None = None

    @property
    def status(self) -> str:
        """``partial`` if any figi errored, else ``success`` (FR-8)."""
        return "partial" if self.errored else "success"


def read_active_with_cursor(
    conn: psycopg.Connection,
) -> list[tuple[str, str, date | None]]:
    """Active securities with their listing MIC and last-loaded cursor (DB state)."""
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.mic, p.cursor_date
          FROM securities s
          LEFT JOIN pipeline_backfill_progress p ON p.composite_figi = s.composite_figi
         WHERE s.status = 'active'
         ORDER BY s.composite_figi
        """
    ).fetchall()
    return [
        (figi, mic.strip() if isinstance(mic, str) else mic, cursor)
        for figi, mic, cursor in rows
    ]


def floor_reached_for(conn: psycopg.Connection, figi: str) -> date | None:
    """The deepest history floor a prior successful backfill covered (None if unknown)."""
    row = conn.execute(
        "SELECT floor_reached_date FROM pipeline_backfill_progress WHERE composite_figi = %s",
        (figi,),
    ).fetchone()
    return row[0] if row else None


def record_floor_reached(conn: psycopg.Connection, figi: str, floor: date) -> None:
    """Record that a successful backfill covered down to ``floor`` (keep the deepest)."""
    conn.execute(
        """
        UPDATE pipeline_backfill_progress
           SET floor_reached_date = LEAST(COALESCE(floor_reached_date, %s), %s)
         WHERE composite_figi = %s
        """,
        (floor, floor, figi),
    )


def latest_session_for(conn: psycopg.Connection, mic: str, as_of_date: date) -> date | None:
    """Latest current-calendar session for ``mic`` on or before ``as_of_date`` (not the clock)."""
    row = conn.execute(
        """
        SELECT max(tc.session_date)
          FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current AND tc.mic = %s AND tc.session_date <= %s
        """,
        (mic, as_of_date),
    ).fetchone()
    return row[0] if row else None


def _mark_error(conn: psycopg.Connection, figi: str, source: str, detail: str) -> None:
    """Mark a security errored WITHOUT advancing its cursor (AR-13)."""
    conn.execute(
        """
        INSERT INTO pipeline_backfill_progress (composite_figi, source, status, detail)
        VALUES (%s, %s, 'error', %s)
        ON CONFLICT (composite_figi) DO UPDATE
            SET status = 'error', detail = EXCLUDED.detail, source = EXCLUDED.source
        """,
        (figi, source, detail[:500]),
    )


def _delete_prices_range(conn: psycopg.Connection, figi: str, start_date: date, end_date: date) -> None:
    """Discard stored raw bars for one figi in [start_date, end_date].

    The one explicit override of the immutable ``ON CONFLICT DO NOTHING`` write (Story 2.10
    overwrite), scoped to an operator-chosen window so a re-fetch can *replace* a bad bar
    (e.g. a provisional same-day pull) instead of being skipped.
    """
    conn.execute(
        "DELETE FROM prices_raw WHERE composite_figi = %s AND session_date BETWEEN %s AND %s",
        (figi, start_date, end_date),
    )


def _write_run_log(
    conn: psycopg.Connection,
    summary: LoadSummary,
    *,
    source: str,
    started_at: datetime,
    finished_at: datetime,
) -> int:
    """Write one run-level log record (FR-8) and return its run_id."""
    # Cap the joined detail: an uncapped vendor traceback could blow the column limit
    # and lose the whole run record at the finish line.
    detail = ("; ".join(f"{figi}: {msg}" for figi, msg in summary.errors[:5]) or None)
    if detail is not None:
        detail = detail[:2000]
    row = conn.execute(
        """
        INSERT INTO pipeline_run_log
            (mode, source, started_at, finished_at, attempted, loaded, skipped,
             errored, rows_written, anomaly_flags, gaps, status, detail, triggered_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING run_id
        """,
        (
            summary.mode, source, started_at, finished_at, summary.attempted,
            summary.loaded, summary.skipped, summary.errored, summary.rows,
            summary.flags, summary.gaps, summary.status, detail,
            # WHO caused this run (Story O.2): the Operate executor sets
            # SYM_TRIGGERED_BY=qrp-job:<id>; NULL = a manual CLI run.
            os.environ.get("SYM_TRIGGERED_BY"),
        ),
    ).fetchone()
    return row[0]


def run_load(
    conn: psycopg.Connection,
    source: object,
    mode: str,
    *,
    as_of_date: date,
    gap_aware: bool = False,
    overwrite_start_date: date | None = None,
    floor: date = DEFAULT_FLOOR,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    securities: Sequence[tuple[str, str, date | None]] | None = None,
    floor_for: Callable[[str], date | None] | None = None,
    end_cap_for: Callable[[str], date | None] | None = None,
) -> LoadSummary:
    """Load a security set in ``mode``; one durable transaction per figi.

    ``gap_aware`` makes a ``FILL`` re-examine history below the cursor (a backfill);
    omit it for the daily forward fill. By default loads the active master
    (``read_active_with_cursor``). Universe-driven ingestion (Story U4) passes its own
    ``securities`` selection plus:
      * ``floor_for(figi)`` — the per-figi backfill floor (a joiner's membership
        ``valid_from``, so its prior history is backfilled over its window);
      * ``end_cap_for(figi)`` — caps the fetch end_date (a leaver's exit date), so a name
        that left the universe stops fetching past its departure.
    """
    if overwrite_start_date is not None and mode != OVERWRITE:
        raise ValueError(f"overwrite_start_date is only valid for mode={OVERWRITE!r}, not {mode!r}")
    conn.autocommit = True  # per-figi commits must be top-level + durable (Story 2.4 finding)
    source_name = getattr(source, "SOURCE", "unknown")
    summary = LoadSummary(mode=mode)
    started_at = now()

    if securities is None:
        securities = read_active_with_cursor(conn)
    if limit is not None:
        if limit < 0:
            raise ValueError(f"limit must be >= 0, got {limit}")  # [:-n] would drop the tail
        securities = securities[:limit]

    for figi, mic, cursor in securities:
        summary.attempted += 1
        end_date = latest_session_for(conn, mic, as_of_date)
        if end_cap_for is not None:
            cap = end_cap_for(figi)
            if cap is not None and (end_date is None or cap < end_date):
                end_date = cap
        fig_floor = (floor_for(figi) if floor_for is not None else None) or floor
        reached = floor_reached_for(conn, figi) if gap_aware else None
        window = compute_window(
            mode, cursor, floor=fig_floor, end_date=end_date, gap_aware=gap_aware,
            floor_reached=reached, overwrite_start_date=overwrite_start_date,
        )
        if window is None:
            summary.skipped += 1
            continue
        start_date, end_date = window
        try:
            # Fetch AND ingest are isolated: a constraint/currency failure in the
            # write must mark one figi errored, not halt the run (AC #3).
            result = fetch_with_retry(source, figi, start_date, end_date, sleep=sleep)
            if mode == OVERWRITE and not result.bars:
                # Empty fetch: do NOT delete. Replacing good stored data with nothing is the one
                # outcome overwrite must never produce — a vendor gap must not destroy history.
                summary.skipped += 1
                continue
            expected = expected_trading_days(conn, mic, start_date, end_date)
            if mode == OVERWRITE:
                # Replace ONLY the span the re-fetch actually covered (clamped to the fetched
                # min/max): deleting the full requested window against a partial fetch would
                # destroy bars the vendor didn't return. Stale review-flags and gap rows for
                # the replaced span go with it (they describe the deleted data), and the
                # cursor is re-derived from what is actually stored (GREATEST alone could
                # leave it stranded past the data). Atomic, only AFTER a non-empty fetch.
                fetched_dates = [b.date for b in result.bars]
                del_start = max(start_date, min(fetched_dates))
                del_end = min(end_date, max(fetched_dates))
                with conn.transaction():
                    _delete_prices_range(conn, figi, del_start, del_end)
                    conn.execute(
                        "DELETE FROM prices_review WHERE composite_figi = %s "
                        "AND session_date BETWEEN %s AND %s",
                        (figi, del_start, del_end),
                    )
                    conn.execute(
                        "DELETE FROM price_gaps WHERE composite_figi = %s "
                        "AND session_date BETWEEN %s AND %s",
                        (figi, del_start, del_end),
                    )
                    result_summary = ingest_result(conn, result, expected_sessions=expected)
                    conn.execute(
                        "UPDATE pipeline_backfill_progress SET cursor_date = "
                        "(SELECT max(session_date) FROM prices_raw WHERE composite_figi = %s) "
                        "WHERE composite_figi = %s",
                        (figi, figi),
                    )
            else:
                result_summary = ingest_result(conn, result, expected_sessions=expected)
        except Exception as exc:  # noqa: BLE001 - isolate one figi's failure
            _mark_error(conn, figi, source_name, str(exc))
            summary.errored += 1
            summary.errors.append((figi, str(exc)))
            continue
        summary.loaded += 1
        summary.rows += result_summary.bars_written
        summary.flags += len(result_summary.flags)
        summary.gaps += len(result_summary.gaps)
        if gap_aware and result.bars:
            # We requested down to `start_date` and got data — that floor is covered;
            # record it so a later same-floor backfill skips this name. A fully EMPTY
            # response is NOT recorded: it can be a vendor outage that returns empty
            # instead of raising, and marking the floor would convert a one-day hiccup
            # into permanently-skipped history.
            record_floor_reached(conn, figi, start_date)

    summary.run_id = _write_run_log(
        conn, summary, source=source_name, started_at=started_at, finished_at=now()
    )
    return summary


def detect_divergences(
    stored: dict[date, Decimal],
    bars: Sequence,
    *,
    tolerance: Decimal = DIVERGENCE_TOLERANCE,
) -> list[tuple[date, Decimal, Decimal, Decimal]]:
    """Stored raw close vs re-fetched, for dates we already have.

    Returns (session_date, stored, fetched, relative_diff) beyond ``tolerance``.
    A date absent from ``stored`` is new data (a fill's job), not a divergence.
    """
    divergences: list[tuple[date, Decimal, Decimal, Decimal]] = []
    for bar in bars:
        prior = stored.get(bar.date)
        if prior is None or prior == 0:
            continue
        relative = abs(bar.close - prior) / prior
        if relative > tolerance:
            divergences.append((bar.date, prior, bar.close, relative))
    return divergences


def _read_stored_closes(
    conn: psycopg.Connection, figi: str, start_date: date, end_date: date
) -> dict[date, Decimal]:
    rows = conn.execute(
        """
        SELECT session_date, close FROM prices_raw
         WHERE composite_figi = %s AND session_date BETWEEN %s AND %s
        """,
        (figi, start_date, end_date),
    ).fetchall()
    return {session_date: close for session_date, close in rows}


def _flag_divergence(
    conn: psycopg.Connection,
    figi: str,
    divergence: tuple[date, Decimal, Decimal, Decimal],
    source: str,
) -> None:
    """Record an audit divergence as a reviewable flag (never overwrites the price)."""
    session_date, stored, fetched, relative = divergence
    conn.execute(
        # flag_type stays 'sweep_divergence': it is a DB-constrained enum value
        # (prices_review_flag_type_chk); the operator-facing command is now `sym audit`.
        """
        INSERT INTO prices_review
            (composite_figi, session_date, flag_type, detail, pct_move, source)
        VALUES (%s, %s, 'sweep_divergence', %s, %s, %s)
        ON CONFLICT (composite_figi, session_date, flag_type) DO UPDATE
            SET detail = EXCLUDED.detail,
                pct_move = EXCLUDED.pct_move, source = EXCLUDED.source
            WHERE NOT prices_review.reviewed
        """,
        (figi, session_date, f"audit: stored {stored} vs re-fetched {fetched}", relative, source),
    )


# `sym audit` (was `sweep`): re-fetch the trailing window and flag where the vendor now
# disagrees with stored raw — a read-only drift check, never an overwrite.
AUDIT = "audit"
AUDIT_LOOKBACK_DAYS = 90


def run_audit(
    conn: psycopg.Connection,
    source: object,
    *,
    as_of_date: date,
    lookback_days: int = AUDIT_LOOKBACK_DAYS,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> LoadSummary:
    """Re-fetch the trailing window per security and report source-side corrections.

    Immutable (AR-10): stored prices are never overwritten — divergences are
    flagged in ``prices_review`` for review. One durable transaction per figi,
    error-isolated; the run is logged (``mode='audit'``).
    """
    conn.autocommit = True
    source_name = getattr(source, "SOURCE", "unknown")
    summary = LoadSummary(mode=AUDIT)
    started_at = now()
    start_date = as_of_date - timedelta(days=lookback_days)

    for figi, _mic, _cursor in read_active_with_cursor(conn):
        summary.attempted += 1
        try:
            result = fetch_with_retry(source, figi, start_date, as_of_date, sleep=sleep)
            stored = _read_stored_closes(conn, figi, start_date, as_of_date)
            divergences = detect_divergences(stored, result.bars)
            for divergence in divergences:
                _flag_divergence(conn, figi, divergence, source_name)
            summary.loaded += 1
            summary.flags += len(divergences)
        except Exception as exc:  # noqa: BLE001 - isolate one figi's failure
            summary.errored += 1
            summary.errors.append((figi, str(exc)))

    summary.run_id = _write_run_log(
        conn, summary, source=source_name, started_at=started_at, finished_at=now()
    )
    return summary
