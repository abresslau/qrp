"""Sweden — Riksbank SWEA API government-bond-yield source adapter.

Sveriges Riksbank publishes Swedish data through the SWEA REST API. Government benchmark bond
yields are exposed as per-series observation feeds (no API key, free):

  ``https://api.riksbank.se/swea/v1/Observations/<seriesId>/<fromDate>[/<toDate>]``

``fromDate``/``toDate`` are ``YYYY-MM-DD``. The response is a JSON array of
``{"date": "YYYY-MM-DD", "value": <num>}`` rows, values in **% per annum**. We loop the four
benchmark government bond series (2y/5y/7y/10y), mapping each series id to its tenor in years.

This module separates **parsing** (pure, testable, no network) from **downloading**, mirroring the
BoE / US Treasury adapters in this package.
"""

from __future__ import annotations

import json
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

SWEA_BASE = "https://api.riksbank.se/swea/v1/Observations"

# Government bond benchmark series id -> tenor in YEARS.
_SERIES: dict[str, float] = {
    "SEGVB2YC": 2.0,
    "SEGVB5YC": 5.0,
    "SEGVB7YC": 7.0,
    "SEGVB10YC": 10.0,
}

# SWEA's earliest sensible default window start when no start_date is given.
_DEFAULT_FROM = "1987-01-01"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


def parse_observations(json_text: str, tenor: float) -> list[CurvePoint]:
    """Parse one SWEA series' observation array into curve points. Pure (no network).

    Each element is ``{"date": "YYYY-MM-DD", "value": <num>}``; rows with a missing/blank/garbled
    date or a non-numeric value are skipped, never invented.
    """
    out: list[CurvePoint] = []
    rows = json.loads(json_text)
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = (row.get("date") or "").strip() if isinstance(row.get("date"), str) else ""
        if not raw_date:
            continue
        try:
            d = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        value = row.get("value")
        if not isinstance(value, (int, float)):
            continue
        out.append(
            CurvePoint(
                "SE", "SEK", "govt", "nominal", "yield", round(tenor, 6), d, float(value)
            )
        )
    return out


def _download(url: str, *, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted riksbank.se host)
        return resp.read()


class RiksbankCurveSource:
    """Fetches + parses Riksbank SWEA government bond yields. ``SOURCE`` tags every stored row."""

    SOURCE = "riksbank"
    COUNTRY = "SE"
    CURRENCY = "SEK"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        from_str = start_date.isoformat() if start_date is not None else _DEFAULT_FROM
        pts: list[CurvePoint] = []
        for series_id, tenor in _SERIES.items():
            url = f"{SWEA_BASE}/{series_id}/{from_str}"
            if end_date is not None:
                url = f"{url}/{end_date.isoformat()}"
            json_text = _download(url).decode("utf-8", "replace")
            pts.extend(parse_observations(json_text, tenor))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
