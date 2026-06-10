"""Atomic raw-price + factor ingestion (Story 2.3, FR-5/NFR-2/3/6).

Takes an :class:`~sym.sources.contract.OhlcvResult` from a source adapter and
persists it per security: raw OHLCV into ``prices_raw``, explicit splits/dividends
into ``corporate_actions``, missing trading days into ``price_gaps``, and the
per-figi cursor/status into ``pipeline_backfill_progress`` — all in ONE transaction
per figi (NFR-6). History is immutable by default (AR-10): every insert is
``ON CONFLICT DO NOTHING``, so a re-run is a true no-op. Invalid vendor bars are
flagged and excluded, never written; missing prices are logged, never forward-filled.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import psycopg

from sym.ingest.anomaly import PriceFlag, detect_anomalies
from sym.sources.contract import OhlcvBar, OhlcvResult


def validate_bar(bar: OhlcvBar) -> tuple[bool, str | None]:
    """Reject structurally corrupt vendor bars (NFR-2). Returns (ok, reason)."""
    if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
        return False, "non-positive price"
    if bar.high < bar.low:
        return False, "high < low"
    if bar.high < bar.open or bar.high < bar.close or bar.low > bar.open or bar.low > bar.close:
        return False, "OHLC out of [low, high]"
    if bar.volume < 0:
        return False, "negative volume"
    return True, None


def detect_gaps(expected_sessions: set[date], bar_dates: set[date]) -> list[date]:
    """Interior open trading days with no price (NFR-3) — reported, never filled.

    A gap is only meaningful *within the security's observed trading life*: an
    open exchange session on or after its first bar that returned no price. Days
    before the first observed bar are NOT gaps — the security simply was not
    listed yet (the backfill window floors at 1990, but most names IPO'd far
    later). If the window returned no bars at all we emit nothing: we cannot tell
    "not listed yet" from "vendor outage" without history, and fabricating a gap
    per session would bury the real holes (this collapsed a 63k-row log to ~200).
    """
    if not bar_dates:
        return []
    first = min(bar_dates)
    return sorted(d for d in expected_sessions - bar_dates if d >= first)


@dataclass
class IngestSummary:
    """What an ingest of one security wrote.

    ``bars_written``/``actions_written`` count rows that actually LANDED — an
    ``ON CONFLICT DO NOTHING`` skip is not a write, so a re-run over existing
    history honestly reports zero (and the run log can tell a no-op from a load).
    """

    figi: str
    source: str
    bars_written: int = 0
    actions_written: int = 0
    gaps: list[date] = field(default_factory=list)
    rejected: list[tuple[date, str]] = field(default_factory=list)
    flags: list[PriceFlag] = field(default_factory=list)
    cursor_date: date | None = None
    error: str | None = None  # set when the figi's ingest failed (batch isolation)


def expected_trading_days(
    conn: psycopg.Connection, mic: str, start: date, end: date
) -> set[date]:
    """Open sessions for ``mic`` in ``[start, end]`` from the current trading calendar."""
    rows = conn.execute(
        """
        SELECT tc.session_date
          FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current
           AND tc.mic = %s
           AND tc.session_date BETWEEN %s AND %s
        """,
        (mic, start, end),
    ).fetchall()
    return {row[0] for row in rows}


def _insert_bar(conn: psycopg.Connection, figi: str, bar: OhlcvBar, result: OhlcvResult) -> bool:
    """Insert one raw bar; True only when a row actually landed (ON CONFLICT skips)."""
    row = conn.execute(
        """
        INSERT INTO prices_raw
            (composite_figi, session_date, open, high, low, close, volume,
             currency_code, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (composite_figi, session_date) DO NOTHING
        RETURNING composite_figi
        """,
        (
            figi, bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume,
            result.currency, result.source,
        ),
    ).fetchone()
    return row is not None


def _insert_action(
    conn: psycopg.Connection,
    figi: str,
    *,
    ex_date: date,
    action_type: str,
    value: object,
    currency: str | None,
    source: str,
) -> bool:
    row = conn.execute(
        """
        INSERT INTO corporate_actions
            (composite_figi, ex_date, action_type, value, currency_code, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (composite_figi, ex_date, action_type) DO NOTHING
        RETURNING composite_figi
        """,
        (figi, ex_date, action_type, value, currency, source),
    ).fetchone()
    return row is not None


def ingest_result(
    conn: psycopg.Connection,
    result: OhlcvResult,
    *,
    expected_sessions: set[date] | None = None,
) -> IngestSummary:
    """Persist one security's OhlcvResult atomically (NFR-6).

    Valid raw bars, explicit splits/dividends, detected gaps, and the cursor/status
    advance all commit in a single transaction. A failure rolls the whole figi-batch
    back and the cursor never advances. Invalid bars are excluded and reported in
    ``rejected``; missing trading days are logged in ``price_gaps``, not filled.
    """
    figi = result.figi
    summary = IngestSummary(figi=figi, source=result.source)

    valid: list[OhlcvBar] = []
    seen_dates: set[date] = set()
    for bar in result.bars:
        ok, reason = validate_bar(bar)
        if ok and bar.date in seen_dates:
            # Two bars for one date: DO NOTHING would silently keep the first and drop
            # the conflict — surface it instead of letting it vanish.
            ok, reason = False, "duplicate date in vendor payload"
        if ok:
            seen_dates.add(bar.date)
            valid.append(bar)
        else:
            summary.rejected.append((bar.date, reason or "invalid"))

    with conn.transaction():
        summary.bars_written = sum(_insert_bar(conn, figi, bar, result) for bar in valid)

        summary.actions_written = sum(
            _insert_action(
                conn, figi, ex_date=split.ex_date, action_type="split",
                value=split.ratio, currency=None, source=result.source,
            )
            for split in result.splits
        ) + sum(
            _insert_action(
                conn, figi, ex_date=dividend.ex_date, action_type="dividend",
                value=dividend.amount, currency=result.currency, source=result.source,
            )
            for dividend in result.dividends
        )

        if expected_sessions is not None:
            summary.gaps = detect_gaps(expected_sessions, {bar.date for bar in valid})
            for gap in summary.gaps:
                conn.execute(
                    """
                    INSERT INTO price_gaps (composite_figi, session_date, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (composite_figi, session_date) DO NOTHING
                    """,
                    (figi, gap, result.source),
                )

        # Stage-1 anomaly annotation (AR-9 / NFR-1): flag suspect prices that DID
        # land, in the same transaction. Idempotent; never clobber a human review.
        # Seed the jump check with the last STORED bar before this batch — the daily
        # forward fill fetches one bar, so without the seed it would never be compared.
        prior_bar = None
        first_new = min((b.date for b in valid), default=None)
        if first_new is not None:
            row = conn.execute(
                "SELECT session_date, close FROM prices_raw "
                "WHERE composite_figi = %s AND session_date < %s "
                "ORDER BY session_date DESC LIMIT 1",
                (figi, first_new),
            ).fetchone()
            prior_bar = (row[0], row[1]) if row else None
        summary.flags = detect_anomalies(valid, result.splits, expected_sessions, prior_bar)
        for flag in summary.flags:
            conn.execute(
                """
                INSERT INTO prices_review
                    (composite_figi, session_date, flag_type, detail, pct_move, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (composite_figi, session_date, flag_type) DO UPDATE
                    SET detail = EXCLUDED.detail,
                        pct_move = EXCLUDED.pct_move,
                        source = EXCLUDED.source
                    WHERE NOT prices_review.reviewed
                """,
                (
                    figi, flag.session_date, flag.flag_type, flag.detail,
                    flag.pct_move, result.source,
                ),
            )

        summary.cursor_date = max((bar.date for bar in valid), default=None)
        conn.execute(
            """
            INSERT INTO pipeline_backfill_progress
                (composite_figi, source, cursor_date, status)
            VALUES (%s, %s, %s, 'ok')
            ON CONFLICT (composite_figi) DO UPDATE
                SET cursor_date = GREATEST(
                        pipeline_backfill_progress.cursor_date, EXCLUDED.cursor_date
                    ),
                    status = 'ok',
                    source = EXCLUDED.source
            """,
            (figi, result.source, summary.cursor_date),
        )

    return summary


_FLAG_TYPES = frozenset({"price_jump", "price_on_non_trading_day", "sweep_divergence"})


def resolve_review(
    conn: psycopg.Connection,
    composite_figi: str,
    session_date: date,
    *,
    resolution: str,
    flag_type: str | None = None,
) -> bool:
    """Confirm or reject a flagged price (a review action, never an ingestion drop).

    A legitimate large move is ``confirmed`` (it stays and will materialize once the
    Epic 3 gate sees it reviewed); a genuine bad tick is ``rejected``. Returns True
    if a flag row was updated.
    """
    if resolution not in ("confirmed", "rejected"):
        raise ValueError(f"resolution must be 'confirmed' or 'rejected', got {resolution!r}")
    if flag_type is not None and flag_type not in _FLAG_TYPES:
        raise ValueError(f"unknown flag_type {flag_type!r} (known: {sorted(_FLAG_TYPES)})")
    if flag_type is None:
        # Flags coexist per type (S.1): one verdict stamped onto EVERY finding
        # at the date would be the clobber relocated — refuse ambiguity.
        open_count = conn.execute(
            "SELECT count(*) FROM prices_review "
            "WHERE composite_figi = %s AND session_date = %s AND NOT reviewed",
            (composite_figi, session_date),
        ).fetchone()[0]
        if open_count > 1:
            raise ValueError(
                f"{open_count} open flags at {composite_figi}/{session_date} — "
                "pass flag_type to resolve ONE finding"
            )
    sql = (
        "UPDATE prices_review "
        "   SET reviewed = TRUE, resolution = %s, reviewed_at = now() "
        " WHERE composite_figi = %s AND session_date = %s"
    )
    params: list[object] = [resolution, composite_figi, session_date]
    if flag_type is not None:
        sql += " AND flag_type = %s"
        params.append(flag_type)
    sql += " RETURNING composite_figi"
    updated = conn.execute(sql, params).fetchone()
    return updated is not None


def ingest_results(
    conn: psycopg.Connection, results: Sequence[OhlcvResult]
) -> list[IngestSummary]:
    """Ingest several securities, each in its own transaction.

    One bad figi is rolled back and skipped; it never halts the rest.
    """
    summaries: list[IngestSummary] = []
    for result in results:
        try:
            summaries.append(ingest_result(conn, result))
        except Exception as exc:  # noqa: BLE001 — isolate ANY per-figi failure, and say so
            summaries.append(
                IngestSummary(figi=result.figi, source=result.source, error=str(exc)[:200])
            )
    return summaries
