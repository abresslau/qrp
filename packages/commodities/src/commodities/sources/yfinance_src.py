"""yfinance continuous front-month source (the v1 Tier-A primary).

Probed 2026-06-23: Yahoo's ``<root>=F`` tickers return the raw, non-back-adjusted continuous
front-month series — daily OHLCV + Volume, history from ~2000, no open interest. Rawness matches
the package's store-raw / PIT principle (the roll discontinuities live IN the series; we never
back-adjust on store). ``yfinance`` is imported lazily so the gateway/router don't need it.

One commodity per fetch loop iteration; a single failing ticker is the loader's concern (attempt-all
is per source, and ``fetch`` here raises only on a wholesale failure).
"""

from __future__ import annotations

import math
import sys
from datetime import date

from ..universe import UNIVERSE, Commodity
from .base import PricePoint

SERIES_TYPE = "continuous_front"


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _history(ticker: str, start_date: date | None, end_date: date | None):
    import yfinance as yf  # lazy: only the ingest path needs yfinance, not the gateway

    t = yf.Ticker(ticker)
    if start_date is None:
        df = t.history(period="max", interval="1d", auto_adjust=False)
    else:
        # yfinance `end` is exclusive — bump by a day so end_date itself is included.
        end = None if end_date is None else end_date.isoformat()
        df = t.history(start=start_date.isoformat(), end=end, interval="1d", auto_adjust=False)
    return df


class YFinanceCommoditySource:
    """Fetches Yahoo continuous front-month OHLCV+Volume for the (Tier-A) commodity universe."""

    SOURCE = "yfinance"

    def __init__(self, commodities: list[Commodity] | None = None) -> None:
        self._commodities = commodities if commodities is not None else UNIVERSE

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[PricePoint]:
        out: list[PricePoint] = []
        for c in self._commodities:
            df = _history(c.yahoo, start_date, end_date)
            if df is None or len(df) == 0:
                continue
            kept = 0
            for ts, row in df.iterrows():
                d = ts.date()
                if start_date is not None and d < start_date:
                    continue
                if end_date is not None and d > end_date:
                    continue
                settle = _num(row.get("Close"))
                if settle is None:
                    continue  # a blank/holiday row — skip, never invent
                kept += 1
                out.append(
                    PricePoint(
                        commodity_code=c.code,
                        series_type=SERIES_TYPE,
                        as_of_date=d,
                        settle=settle,
                        open=_num(row.get("Open")),
                        high=_num(row.get("High")),
                        low=_num(row.get("Low")),
                        volume=_num(row.get("Volume")),
                    )
                )
            if kept == 0:
                # A non-empty frame yielded zero usable rows — a yfinance column-shape change
                # (MultiIndex) or an all-NaN Close. Fail loud: silence would drop a whole
                # commodity, looking identical to "no data".
                print(
                    f"WARNING: {c.code} ({c.yahoo}): fetched {len(df)} rows but kept 0 "
                    "(no usable Close — column shape changed or all-NaN?)",
                    file=sys.stderr,
                )
        return out
