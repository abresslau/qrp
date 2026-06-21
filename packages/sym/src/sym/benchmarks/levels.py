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
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

import psycopg

from sym.benchmarks.msci import msci_xref_value
from sym.identity.instrument import INDEX, SRC_MSCI, SRC_YAHOO, ensure_instrument

DEFAULT_START = date(1990, 1, 1)


@dataclass(frozen=True)
class Benchmark:
    name: str
    currency_code: str
    yahoo_symbol: str | None = None
    msci_code: str | None = None
    # Return variant for an MSCI entry (PR/NR/GR). Drives the variant-encoded `msci` xref
    # (`<code>:<VARIANT>`) so the registry reconciles with `sym msci-pull` — same instrument per
    # variant, no bare-code stub. Yahoo-only benchmarks leave this None.
    variant: str | None = None
    # Geographic region for the World-Equity-Indices board: Americas | EMEA | Asia-Pacific | Global.
    region: str | None = None


def benchmark_xrefs(b: Benchmark) -> dict[str, str]:
    """The external-id xrefs for a benchmark's instrument identity. The MSCI xref is
    variant-encoded when a variant is set (reconciling with the pull); a bare code is only used
    for a legacy MSCI entry without a variant."""
    xrefs: dict[str, str] = {}
    if b.yahoo_symbol:
        xrefs[SRC_YAHOO] = b.yahoo_symbol
    if b.msci_code:
        xrefs[SRC_MSCI] = msci_xref_value(b.msci_code, b.variant) if b.variant else b.msci_code
    return xrefs


# Headline benchmarks. Each published series is its OWN index (instrument) — the
# name distinguishes price vs total-return (e.g. "S&P 500" vs "S&P 500 (Total
# Return)"). MSCI-only entries (no yahoo) create the instrument + msci xref and
# defer level loading to a file import.
BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark("S&P 500", "USD", yahoo_symbol="^GSPC", region="Americas"),
    Benchmark("S&P 500 (Total Return)", "USD", yahoo_symbol="^SP500TR", region="Americas"),
    Benchmark("S&P MidCap 400", "USD", yahoo_symbol="^MID", region="Americas"),
    Benchmark("S&P SmallCap 600", "USD", yahoo_symbol="^SP600", region="Americas"),
    Benchmark("Nasdaq Composite", "USD", yahoo_symbol="^IXIC", region="Americas"),
    Benchmark("Dow Jones Industrial Average", "USD", yahoo_symbol="^DJI", region="Americas"),
    Benchmark("Russell 2000", "USD", yahoo_symbol="^RUT", region="Americas"),
    Benchmark("EURO STOXX 50", "EUR", yahoo_symbol="^STOXX50E", region="EMEA"),
    Benchmark("FTSE 100", "GBP", yahoo_symbol="^FTSE", region="EMEA"),
    Benchmark("DAX (Total Return)", "EUR", yahoo_symbol="^GDAXI", region="EMEA"),
    Benchmark("CAC 40", "EUR", yahoo_symbol="^FCHI", region="EMEA"),
    Benchmark("IBEX 35", "EUR", yahoo_symbol="^IBEX", region="EMEA"),
    Benchmark("FTSE MIB", "EUR", yahoo_symbol="FTSEMIB.MI", region="EMEA"),
    Benchmark("AEX", "EUR", yahoo_symbol="^AEX", region="EMEA"),
    Benchmark("SMI (Swiss Market Index)", "CHF", yahoo_symbol="^SSMI", region="EMEA"),
    Benchmark("Nikkei 225", "JPY", yahoo_symbol="^N225", region="Asia-Pacific"),
    Benchmark("IBOVESPA", "BRL", yahoo_symbol="^BVSP", region="Americas"),
    # MSCI World Net — no Yahoo; levels come from `sym msci-pull` (or a file import). variant="NR"
    # → msci xref 990100:NETR, the SAME instrument the pull creates (no bare-code stub on re-seed).
    Benchmark(
        "MSCI World (Net Total Return)", "USD", msci_code="990100", variant="NR", region="Global"
    ),
)

# Region resolution for the World-Equity-Indices board (data-driven, reused by the API). MSCI
# aggregates → "Global"; otherwise the registry's region by name, else a currency fallback.
_REGION_BY_NAME = {b.name: b.region for b in BENCHMARKS if b.region}
_AMER = "Americas"
_EMEA = "EMEA"
_APAC = "Asia-Pacific"
_REGION_BY_CCY = {
    "USD": _AMER, "BRL": _AMER, "CAD": _AMER, "MXN": _AMER, "ARS": _AMER,
    "EUR": _EMEA, "GBP": _EMEA, "CHF": _EMEA, "SEK": _EMEA, "NOK": _EMEA, "DKK": _EMEA,
    "ZAR": _EMEA,
    "JPY": _APAC, "HKD": _APAC, "KRW": _APAC, "AUD": _APAC,
    "CNY": _APAC, "INR": _APAC, "SGD": _APAC, "TWD": _APAC, "NZD": _APAC,
}


def region_for(name: str | None, currency: str | None = None) -> str:
    """Region for an index by name (MSCI aggregates → Global; registry map), with a currency
    fallback for unknown names. Always returns one of Americas | EMEA | Asia-Pacific | Global."""
    if name and name.strip().upper().startswith("MSCI"):
        return "Global"
    by_ccy = _REGION_BY_CCY.get((currency or "").upper())
    return _REGION_BY_NAME.get(name or "") or by_ccy or "Global"


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
        # Vendor failures RAISE (the loader counts them as errors) — swallowing them as []
        # made an outage indistinguishable from "this index has no data".
        hist = yf.Ticker(symbol).history(start=start.isoformat(), auto_adjust=False)
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
    errors: int = 0  # vendor fetch raised (distinct from "no data")
    failures: list[str] = field(default_factory=list)


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
        xrefs = benchmark_xrefs(b)
        sym_id = ensure_instrument(
            conn, INDEX, name=b.name, currency_code=b.currency_code, xrefs=xrefs
        )
        summary.instruments += 1
        if not b.yahoo_symbol:
            summary.deferred += 1
            continue
        try:
            series = source.levels(b.yahoo_symbol, start)
        except Exception as exc:  # noqa: BLE001 — isolate one benchmark's vendor failure
            summary.errors += 1
            summary.failures.append(f"{b.yahoo_symbol}: {str(exc)[:160]}")
            continue
        # Drop today's row: intraday it is a PROVISIONAL close, and the immutable insert
        # would block the final close forever. The final close lands on the next run.
        today = date.today()
        series = [(d, lv) for d, lv in series if d < today]
        if not series:
            summary.gaps += 1
            continue
        # One transaction per benchmark: an interrupt never leaves a half-written series.
        with conn.transaction():
            for d, level in series:
                if _upsert_level(conn, sym_id, d, level, source.SOURCE):
                    summary.levels_written += 1
    return summary
