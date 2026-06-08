"""Benchmark registry + index-level sourcing (Benchmark epic, B2).

A small, data-driven registry of headline benchmarks maps each to a Yahoo symbol
(and/or an MSCI code) and a return **variant**. ``load_index_levels`` ensures the
instrument identity (``ensure_instrument`` kind=index with yahoo/msci xrefs) and
upserts its level series into ``index_levels`` (immutable). The Yahoo source is
behind a fakeable Protocol; MSCI-only benchmarks get an instrument + ``msci`` xref
but their levels are loaded from a downloaded file (deferred).

Variant notes (deliberate, not all "PR"): Yahoo's ``^SP500TR`` and ``^GDAXI`` are
*total-return* indexes (GTR); ``^BVSP`` (IBOVESPA) is total-return in BRL; MSCI
World is typically tracked Net (NTR). Mislabelling a variant silently corrupts
alpha, so each is set explicitly.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import psycopg

from sym.identity.instrument import INDEX, SRC_MSCI, SRC_YAHOO, ensure_instrument

DEFAULT_START = date(1990, 1, 1)


@dataclass(frozen=True)
class Benchmark:
    name: str
    currency_code: str
    yahoo_symbol: str | None = None
    msci_code: str | None = None


# Headline benchmarks. Each published series is its OWN index (instrument) — the
# name distinguishes price vs total-return (e.g. "S&P 500" vs "S&P 500 (Total
# Return)"). MSCI-only entries (no yahoo) create the instrument + msci xref and
# defer level loading to a file import.
BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark("S&P 500", "USD", yahoo_symbol="^GSPC"),
    Benchmark("S&P 500 (Total Return)", "USD", yahoo_symbol="^SP500TR"),
    Benchmark("S&P MidCap 400", "USD", yahoo_symbol="^MID"),
    Benchmark("S&P SmallCap 600", "USD", yahoo_symbol="^SP600"),
    Benchmark("Nasdaq Composite", "USD", yahoo_symbol="^IXIC"),
    Benchmark("Dow Jones Industrial Average", "USD", yahoo_symbol="^DJI"),
    Benchmark("Russell 2000", "USD", yahoo_symbol="^RUT"),
    Benchmark("EURO STOXX 50", "EUR", yahoo_symbol="^STOXX50E"),
    Benchmark("FTSE 100", "GBP", yahoo_symbol="^FTSE"),
    Benchmark("DAX (Total Return)", "EUR", yahoo_symbol="^GDAXI"),
    Benchmark("CAC 40", "EUR", yahoo_symbol="^FCHI"),
    Benchmark("IBEX 35", "EUR", yahoo_symbol="^IBEX"),
    Benchmark("FTSE MIB", "EUR", yahoo_symbol="FTSEMIB.MI"),
    Benchmark("AEX", "EUR", yahoo_symbol="^AEX"),
    Benchmark("SMI (Swiss Market Index)", "CHF", yahoo_symbol="^SSMI"),
    Benchmark("Nikkei 225", "JPY", yahoo_symbol="^N225"),
    Benchmark("IBOVESPA", "BRL", yahoo_symbol="^BVSP"),
    Benchmark("MSCI World (Net Total Return)", "USD", msci_code="990100"),  # no Yahoo; MSCI file
)


class IndexLevelSource(Protocol):
    """Yields a symbol's (session_date, level) close series from ``start``."""

    SOURCE: str

    def levels(self, symbol: str, start: date) -> list[tuple[date, Decimal]]: ...


class YahooIndexLevelSource:
    """Index closes from yfinance (throttled)."""

    SOURCE = "yahoo"

    def __init__(self, *, min_interval: float = 0.3) -> None:
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def levels(self, symbol: str, start: date) -> list[tuple[date, Decimal]]:
        import math

        import yfinance as yf

        self._throttle()
        try:
            hist = yf.Ticker(symbol).history(start=start.isoformat(), auto_adjust=False)
        except Exception:  # noqa: BLE001 - vendor flakiness is a gap, not a crash
            return []
        if hist is None or len(hist) == 0 or "Close" not in hist:
            return []
        out: list[tuple[date, Decimal]] = []
        for ts, close in hist["Close"].items():
            if close is None or (isinstance(close, float) and math.isnan(close)) or close <= 0:
                continue
            out.append((ts.date(), Decimal(str(close))))
        return out


@dataclass
class LevelsSummary:
    instruments: int = 0
    levels_written: int = 0
    deferred: int = 0  # MSCI-only (instrument created, levels not yet loaded)
    gaps: int = 0  # yahoo returned nothing


def _upsert_level(
    conn: psycopg.Connection, sym_id: int, d: date, level: Decimal, source: str
) -> bool:
    row = conn.execute(
        """
        INSERT INTO index_levels (sym_id, session_date, level, source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (sym_id, session_date) DO NOTHING
        RETURNING sym_id
        """,
        (sym_id, d, level, source),
    ).fetchone()
    return row is not None


def load_index_levels(
    conn: psycopg.Connection,
    source: IndexLevelSource,
    benchmarks: Sequence[Benchmark] = BENCHMARKS,
    *,
    start: date = DEFAULT_START,
) -> LevelsSummary:
    """Ensure each benchmark's instrument identity and load its level series.

    MSCI-only benchmarks (no Yahoo symbol) get an instrument + ``msci`` xref but
    their levels are deferred to a file import. Yahoo levels are immutable-upserted.
    """
    conn.autocommit = True
    summary = LevelsSummary()
    for b in benchmarks:
        xrefs: dict[str, str] = {}
        if b.yahoo_symbol:
            xrefs[SRC_YAHOO] = b.yahoo_symbol
        if b.msci_code:
            xrefs[SRC_MSCI] = b.msci_code
        sym_id = ensure_instrument(
            conn, INDEX, name=b.name, currency_code=b.currency_code, xrefs=xrefs
        )
        summary.instruments += 1
        if not b.yahoo_symbol:
            summary.deferred += 1
            continue
        series = source.levels(b.yahoo_symbol, start)
        if not series:
            summary.gaps += 1
            continue
        for d, level in series:
            if _upsert_level(conn, sym_id, d, level, source.SOURCE):
                summary.levels_written += 1
    return summary
