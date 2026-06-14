"""Market-data series for the macro layer: commodities + market indices, via yfinance.

Kept separate from ``sources.py`` (stdlib-only HTTP fetchers) because it pulls a third-party
client. Returns the same ``(meta, obs)`` shape the ingest contract expects, source-tagged
``market``. These are the commodity (Brent/gold/grains) and market (Bovespa/S&P/DXY) inputs a
macro desk reads alongside the official statistics — Kinea's "energy + AI commodities" spine.

In this environment yfinance ``.history()`` returns simulated-2026 daily bars (see the env
notes); a no-data ticker yields an empty series and is dropped, never faked.
"""

from __future__ import annotations

import math
from datetime import date


def _history(ticker: str, start: str) -> list[tuple[date, float]]:
    """Daily (date, close) for a yfinance ticker since ``start``. Isolated for test seams.
    ``auto_adjust=False`` keeps the raw close (these are futures/indices, not split equities)."""
    import yfinance as yf  # lazy: keep module import cheap and optional

    df = yf.Ticker(ticker).history(start=start, auto_adjust=False)
    if df is None or len(df) == 0 or "Close" not in df:
        return []
    return [(ts.date(), float(v)) for ts, v in df["Close"].items()]


def fetch_yfinance(
    ticker: str,
    series_id: str,
    name: str,
    unit: str,
    geo: str,
    scale: float = 1.0,
    start: str = "2000-01-01",
) -> tuple[dict, list]:
    """One market series (commodity future or index) as (meta, observations). Non-finite
    closes (a NaN bar) are skipped, never faked; ``scale`` is a labelled unit conversion."""
    raw = _history(ticker, start)
    obs = sorted({d: v * scale for d, v in raw if math.isfinite(v)}.items())
    meta = {
        "series_id": series_id,
        "source": "market",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": "daily",
    }
    return meta, obs
