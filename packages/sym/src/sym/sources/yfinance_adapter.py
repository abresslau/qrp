"""yfinance source adapter (Story 2.2, NFR-8: personal-research-only).

Returns RAW OHLCV + explicit corporate actions. It requests ``auto_adjust=False``
and **discards the ``Adj Close`` column** — corporate-action factors come only
from yfinance's explicit ``Dividends`` / ``Stock Splits`` columns (HARD RULE,
AR-6). The vendor dependency (the ``history`` call) and the figi -> symbol
mapping are injected so the adapter is unit-tested without the network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from sym.sources.contract import (
    DividendEvent,
    OhlcvBar,
    OhlcvResult,
    SplitEvent,
    UnknownSymbolError,
    cumulative_split_factor,
)
from sym.sources.registry import register_source

SOURCE = "yfinance"


def _dec(value: Any) -> Decimal:
    """Convert a vendor float to Decimal via str (avoids binary-float artifacts)."""
    return Decimal(str(value))


def parse_history(frame: Any) -> tuple[list[OhlcvBar], list[SplitEvent], list[DividendEvent]]:
    """Split a yfinance history frame into RAW bars + explicit split/dividend events.

    Yahoo's ``Open/High/Low/Close/Volume`` are **split-adjusted at source** (the
    $43 you see for pre-2020 AAPL is 172/4), not the actual traded price. To honour
    the contract's "raw OHLCV" we un-split-adjust back to the real traded price
    using the EXPLICIT ``Stock Splits`` factors (HARD RULE, AR-6: factors from
    explicit records, never from a price ratio): ``raw_price = yahoo * factor`` and
    ``raw_volume = yahoo / factor``. The ``Adj Close`` column (additionally
    dividend-adjusted) is ignored entirely. ``Stock Splits``/``Dividends`` are 0 on
    non-event days; non-zero rows are the ex-date events.
    """
    splits: list[SplitEvent] = []
    dividends: list[DividendEvent] = []
    for index, row in frame.iterrows():
        ex_date = index.date()
        split_ratio = row.get("Stock Splits", 0) or 0
        if split_ratio:
            splits.append(SplitEvent(ex_date=ex_date, ratio=_dec(split_ratio)))
        dividend = row.get("Dividends", 0) or 0
        if dividend:
            dividends.append(DividendEvent(ex_date=ex_date, amount=_dec(dividend)))

    bars: list[OhlcvBar] = []
    for index, row in frame.iterrows():
        ex_date = index.date()
        factor = cumulative_split_factor(splits, ex_date)  # >1 before a later split
        bars.append(
            OhlcvBar(
                date=ex_date,
                open=_dec(row["Open"]) * factor,
                high=_dec(row["High"]) * factor,
                low=_dec(row["Low"]) * factor,
                close=_dec(row["Close"]) * factor,
                volume=int(_dec(row["Volume"]) / factor),
            )
        )
    return bars, splits, dividends


# Yahoo quotes some markets in a MINOR unit (UK pence, S. African cents, Israeli
# agorot) rather than the ISO currency. Normalize prices to the major ISO unit so
# the currency FK is clean and values are comparable.
_MINOR_UNITS = {
    "GBp": ("GBP", Decimal(100)),
    "GBX": ("GBP", Decimal(100)),
    "ZAc": ("ZAR", Decimal(100)),
    "ILA": ("ILS", Decimal(100)),
}


def _normalize_minor_units(
    currency: str, bars: list[OhlcvBar], dividends: list[DividendEvent]
) -> tuple[str, list[OhlcvBar], list[DividendEvent]]:
    if currency not in _MINOR_UNITS:
        return currency, bars, dividends
    major, divisor = _MINOR_UNITS[currency]
    bars = [
        replace(b, open=b.open / divisor, high=b.high / divisor,
                low=b.low / divisor, close=b.close / divisor)
        for b in bars
    ]
    dividends = [replace(d, amount=d.amount / divisor) for d in dividends]
    return major, bars, dividends


def _yf_history(symbol: str, start: date, end: date) -> Any:
    import yfinance as yf

    # yfinance's `end` is EXCLUSIVE; the OhlcvSource contract treats end as
    # inclusive, so add a day (otherwise the last session is silently dropped --
    # the false-gap seen in Story 2.3).
    return yf.Ticker(symbol).history(
        start=start, end=end + timedelta(days=1), auto_adjust=False, actions=True
    )


def _yf_currency(symbol: str) -> str:
    import yfinance as yf

    return yf.Ticker(symbol).fast_info["currency"]


class YFinanceSource:
    """``fetch_ohlcv`` backed by yfinance.

    ``symbol_for`` maps a CompositeFIGI to a Yahoo symbol; ``history`` /
    ``currency_for`` / ``clock`` are injectable for testing.
    """

    def __init__(
        self,
        symbol_for: Callable[[str], str | None],
        *,
        history: Callable[[str, date, date], Any] | None = None,
        currency_for: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._symbol_for = symbol_for
        self._history = history or _yf_history
        self._currency_for = currency_for or _yf_currency
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_ohlcv(self, figi: str, start: date, end: date) -> OhlcvResult:
        symbol = self._symbol_for(figi)
        if not symbol:
            raise UnknownSymbolError(f"no yfinance symbol for {figi}")
        frame = self._history(symbol, start, end)
        bars, splits, dividends = parse_history(frame)
        currency, bars, dividends = _normalize_minor_units(
            self._currency_for(symbol), bars, dividends
        )
        return OhlcvResult(
            figi=figi,
            currency=currency,
            bars=bars,
            source=SOURCE,
            retrieved_at=self._clock(),
            splits=splits,
            dividends=dividends,
        )


# MIC -> Yahoo symbol suffix. US listings have no suffix; others append a
# vendor-specific code. (Yahoo uses '-' for share classes: BRK.A -> BRK-A.)
YAHOO_SUFFIX = {
    "XNYS": "", "XNAS": "", "XASE": "", "ARCX": "",
    "XLON": ".L", "XPAR": ".PA", "XETR": ".DE", "XFRA": ".F", "XSWX": ".SW",
    "XTKS": ".T", "XHKG": ".HK", "XKRX": ".KS", "XTAI": ".TW", "XASX": ".AX",
    "XMAD": ".MC", "XAMS": ".AS", "XBRU": ".BR", "XMIL": ".MI", "XSTO": ".ST",
    "XCSE": ".CO", "XHEL": ".HE", "XOSL": ".OL", "XLIS": ".LS", "XWAR": ".WA",
    "XTSE": ".TO", "XNZE": ".NZ", "XJSE": ".JO", "XSES": ".SI", "XBOM": ".BO",
    "XNSE": ".NS", "XSHG": ".SS", "XSHE": ".SZ", "XMEX": ".MX", "BVMF": ".SA",
    "XTAE": ".TA",
}


def make_yahoo_symbol_resolver(conn: psycopg.Connection) -> Callable[[str], str | None]:
    """Build a figi -> Yahoo symbol resolver from the identity tables.

    Ticker comes from the currently-effective symbology; the suffix from the
    security's listing MIC. A MIC with no Yahoo mapping yields None (the figi is
    errored by the orchestration, never halting the run).
    """

    def resolve(figi: str) -> str | None:
        row = conn.execute(
            """
            SELECT y.symbol_value, s.mic
              FROM securities s
              JOIN security_symbology y
                ON y.composite_figi = s.composite_figi
               AND y.symbol_type = 'ticker'
               AND y.valid_to IS NULL
             WHERE s.composite_figi = %s
            """,
            (figi,),
        ).fetchone()
        if row is None:
            return None
        ticker, mic = row
        suffix = YAHOO_SUFFIX.get(mic.strip() if isinstance(mic, str) else mic)
        if suffix is None:
            return None
        return f"{ticker.replace('.', '-')}{suffix}"

    return resolve


# Self-register so the source is selectable by config key (AR-5). yfinance is a
# raw + explicit-factors source, so it is NOT adjusted-only.
register_source(SOURCE, YFinanceSource, adjusted_only=False)
