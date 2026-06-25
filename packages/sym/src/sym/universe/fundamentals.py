"""Fundamentals input — historical market cap + shares outstanding (Story U5.1).

Populates `fundamentals` as a **historical series** (SCD-style, keyed
`(composite_figi, as_of_date)`): one row per shares-outstanding *change*, with
market cap = the security's raw close on that date × shares. Shares history comes
from yfinance ``get_shares_full`` (US-first; behind a fakeable Protocol so the
loader is testable without the network). A missing series is a flagged gap, never
faked. Point-in-time market cap for any date is `close(≤date) × shares(≤date)` —
the criteria screen (U5.2) recomputes it, so it is never stale.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import psycopg

DEFAULT_HISTORY_START = date(1990, 1, 1)


class SharesHistorySource(Protocol):
    """Yields a security's (date, shares_outstanding) history (empty if unavailable)."""

    SOURCE: str

    def shares_history(self, composite_figi: str) -> list[tuple[date, Decimal]]: ...


class YFinanceSharesHistorySource:
    """Historical shares outstanding from yfinance ``get_shares_full`` (throttled)."""

    SOURCE = "yfinance"

    def __init__(
        self,
        symbol_for: Callable[[str], str | None],
        *,
        start: date = DEFAULT_HISTORY_START,
        min_interval: float = 0.4,
    ) -> None:
        self._symbol_for = symbol_for
        self._start = start
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def shares_history(self, composite_figi: str) -> list[tuple[date, Decimal]]:
        symbol = self._symbol_for(composite_figi)
        if not symbol:
            return []
        import math

        import yfinance as yf

        self._throttle()
        try:
            series = yf.Ticker(symbol).get_shares_full(start=self._start.isoformat(), end=None)
        except Exception:  # noqa: BLE001 - vendor flakiness is a gap, not a crash
            return []
        if series is None or len(series) == 0:
            return []
        out: list[tuple[date, Decimal]] = []
        for ts, value in series.items():
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            try:
                out.append((ts.date(), Decimal(str(int(value)))))
            except (ValueError, TypeError):
                continue  # non-numeric vendor cell — skip the point, not the security
        return out


def dedupe_changes(series: Sequence[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    """Collapse a (date, value) series to change-points (keep the first + each change).

    Same-date duplicates (vendors emit them) collapse deterministically to the LAST
    value for the date — plain ``sorted`` would pick a winner by value, which is
    arbitrary and made re-runs nondeterministic.
    """
    by_date: dict[date, Decimal] = {}
    for d, v in series:
        by_date[d] = v  # last write wins per date (input order = vendor order)
    out: list[tuple[date, Decimal]] = []
    last: Decimal | None = None
    for d in sorted(by_date):
        v = by_date[d]
        if v != last:
            out.append((d, v))
            last = v
    return out


@dataclass
class FundamentalsSummary:
    attempted: int = 0       # securities
    loaded: int = 0          # securities with >= 1 shares observation
    gaps: int = 0            # securities with no shares history (flagged, not faked)
    rows: int = 0            # fundamentals rows written


def _close_on_or_before(conn: psycopg.Connection, figi: str, d: date) -> Decimal | None:
    row = conn.execute(
        "SELECT close FROM prices_raw WHERE composite_figi = %s AND session_date <= %s "
        "ORDER BY session_date DESC LIMIT 1",
        (figi, d),
    ).fetchone()
    return row[0] if row else None


def _currency_map(conn: psycopg.Connection, figis: Sequence[str]) -> dict[str, str | None]:
    rows = conn.execute(
        "SELECT composite_figi, currency_code FROM securities WHERE composite_figi = ANY(%s)",
        (list(figis),),
    ).fetchall()
    return {figi: ccy for figi, ccy in rows}


def _upsert_row(
    conn: psycopg.Connection,
    figi: str,
    effective_date: date,
    market_cap_lcy: Decimal | None,
    shares: Decimal | None,
    currency_code: str | None,
    source: str,
) -> None:
    conn.execute(
        """
        INSERT INTO fundamentals
            (composite_figi, as_of_date, market_cap_lcy, shares_outstanding,
             currency_code, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (composite_figi, as_of_date) DO UPDATE
            SET market_cap_lcy = EXCLUDED.market_cap_lcy,
                shares_outstanding = EXCLUDED.shares_outstanding,
                currency_code = EXCLUDED.currency_code, source = EXCLUDED.source
        """,
        (figi, effective_date, market_cap_lcy, shares, currency_code, source),
    )


def load_fundamentals_history(
    conn: psycopg.Connection,
    source: SharesHistorySource,
    figis: Sequence[str],
) -> FundamentalsSummary:
    """Populate the historical shares + market-cap series for ``figis``.

    For each shares change-point, market cap = the raw close on/before that date ×
    shares (so each stored row's market cap is correct for its own date). A security
    with no shares history is counted as a gap (no fabricated value).
    """
    conn.autocommit = True
    currency = _currency_map(conn, figis)
    summary = FundamentalsSummary()
    for figi in figis:
        summary.attempted += 1
        series = dedupe_changes(source.shares_history(figi))
        if not series:
            summary.gaps += 1
            continue
        summary.loaded += 1
        ccy = currency.get(figi)
        for effective_date, shares in series:
            close = _close_on_or_before(conn, figi, effective_date)
            market_cap_lcy = close * shares if close is not None else None
            _upsert_row(conn, figi, effective_date, market_cap_lcy, shares, ccy, source.SOURCE)
            summary.rows += 1
    return summary


def recompute_market_cap_usd(conn: psycopg.Connection, fx_conn: psycopg.Connection) -> int:
    """(Re)populate ``fundamentals.market_cap_usd`` = market_cap restated to USD (returns rows set).

    Set-based, repeatable, reconstructable: for each row, USD = ``market_cap_lcy`` for USD rows,
    else ``market_cap_lcy / rate`` where ``rate`` is the latest USD-base rate (per-USD) with
    ``as_of_date <= the row's date`` and within the FX outage cap (so a currency with no FX cover on
    the date stays NULL — including a previously-converted row whose inputs no longer qualify:
    the recompute NULLs it rather than leaving a stale conversion in place). This mirrors the
    Python ``fx.resolve``/``convert`` semantics (kept in sync with ``OUTAGE_CAP_DAYS``); run it
    after a fundamentals load and/or an FX load.

    Cross-DB: FX lives in its own database now. The set-based join is per-row/per-date (each
    fundamentals row needs the rate as-of ITS date), so a single latest-rate map won't do. We fetch
    the USD-base observations for exactly the currencies present in ``fundamentals`` from the fx DB,
    materialise them into a sym-side TEMP table (local — NO cross-DB join), and run the IDENTICAL
    LATERAL update against it. ``fundamentals.market_cap_usd`` stays a sym column.
    """
    from fx.resolve import OUTAGE_CAP_DAYS

    conn.autocommit = True
    currencies = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT currency_code FROM fundamentals "
            "WHERE currency_code IS NOT NULL AND currency_code <> 'USD'"
        ).fetchall()
    ]
    fx_rows = (
        fx_conn.execute(
            "SELECT quote_currency, as_of_date, rate FROM fx.fx_rate "
            "WHERE base_currency = 'USD' AND quote_currency = ANY(%s)",
            (currencies,),
        ).fetchall()
        if currencies
        else []
    )
    # Local temp table (this connection/session). DROP-first guards a leftover from a crashed run;
    # under autocommit a TEMP table persists across statements until dropped / session end.
    conn.execute("DROP TABLE IF EXISTS _fx_rate_tmp")
    conn.execute(
        "CREATE TEMP TABLE _fx_rate_tmp (quote_currency CHAR(3), as_of_date DATE, rate NUMERIC)"
    )
    if fx_rows:
        with conn.cursor() as cur, cur.copy(
            "COPY _fx_rate_tmp (quote_currency, as_of_date, rate) FROM STDIN"
        ) as copy:
            for row in fx_rows:
                copy.write_row(row)
    conn.execute("CREATE INDEX ON _fx_rate_tmp (quote_currency, as_of_date)")
    result = conn.execute(
        """
        UPDATE fundamentals f SET market_cap_usd = sub.usd
          FROM (
            SELECT f2.composite_figi, f2.as_of_date,
                   CASE WHEN f2.market_cap_lcy IS NULL THEN NULL
                        WHEN f2.currency_code = 'USD' THEN f2.market_cap_lcy
                        WHEN r.rate IS NOT NULL AND r.rate > 0
                             AND f2.as_of_date - r.as_of_date <= %s
                            THEN f2.market_cap_lcy / r.rate
                        ELSE NULL  -- no usable rate: NULL, never a stale prior conversion
                   END AS usd
              FROM fundamentals f2
              LEFT JOIN LATERAL (
                  SELECT rate, as_of_date FROM _fx_rate_tmp
                   WHERE quote_currency = f2.currency_code
                     AND as_of_date <= f2.as_of_date
                   ORDER BY as_of_date DESC LIMIT 1
              ) r ON TRUE
          ) sub
         WHERE f.composite_figi = sub.composite_figi AND f.as_of_date = sub.as_of_date
           AND f.market_cap_usd IS DISTINCT FROM sub.usd
        """,
        (OUTAGE_CAP_DAYS,),
    )
    conn.execute("DROP TABLE IF EXISTS _fx_rate_tmp")
    return result.rowcount


def _filter_to_master(conn: psycopg.Connection, figis: list[str]) -> list[str]:
    """The subset of ``figis`` present in sym's securities master (sorted)."""
    if not figis:
        return []
    rows = conn.execute(
        "SELECT composite_figi FROM securities WHERE composite_figi = ANY(%s)", (figis,)
    ).fetchall()
    return sorted(r[0] for r in rows)


def resolved_member_figis(
    conn: psycopg.Connection, u_conn: psycopg.Connection, universe_id: str
) -> list[str]:
    """Resolved member figis of a universe that exist in the master (cross-DB roster-fetch).

    ``u_conn`` is the universe DB (the resolved roster); ``conn`` is sym (the securities master)."""
    resolved = [
        r[0]
        for r in u_conn.execute(
            "SELECT DISTINCT composite_figi FROM universe_member_resolution "
            "WHERE universe_id = %s AND resolution_status = 'resolved' "
            "AND composite_figi IS NOT NULL",
            (universe_id,),
        ).fetchall()
    ]
    return _filter_to_master(conn, resolved)


def all_resolved_member_figis(conn: psycopg.Connection, u_conn: psycopg.Connection) -> list[str]:
    """Deduped union of resolved member figis across **all** universes (cross-DB roster-fetch)."""
    resolved = [
        r[0]
        for r in u_conn.execute(
            "SELECT DISTINCT composite_figi FROM universe_member_resolution "
            "WHERE resolution_status = 'resolved' AND composite_figi IS NOT NULL"
        ).fetchall()
    ]
    return _filter_to_master(conn, resolved)
