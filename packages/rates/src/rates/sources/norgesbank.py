"""Norway — Norges Bank SDMX government-rates source adapter.

Norges Bank publishes its data via an SDMX REST API. The ``GOVT_GENERIC_RATES`` dataset carries
daily generic Norwegian government interest rates (par-style benchmark yields, available since
~2019). We request CSV (easiest to parse), one tenor per series key or all via a wildcard:

  ``https://data.norges-bank.no/api/data/GOVT_GENERIC_RATES/B.<T>.GBON?format=csv&locale=en``

where ``<T>`` is a tenor token (3M/6M/12M/3Y/5Y/7Y/10Y). ``B`` is the (business-)daily frequency
and ``GBON`` the government-bond instrument. A wildcard key ``B..GBON`` returns every tenor at
once. The CSV is semicolon- or comma-delimited with a header row; the columns of interest are
``TIME_PERIOD`` (the observation date, ``YYYY-MM-DD``) and ``OBS_VALUE`` (the rate, **% per
annum**). Tenor tokens are read from a dimension column (``Tenor``/``TENOR``).

This module separates **parsing** (pure, testable, no network) from **downloading**, mirroring the
BoE / US Treasury adapters in this package.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

NB_BASE = "https://data.norges-bank.no/api/data/GOVT_GENERIC_RATES"

# Tenor token (as used in the SDMX key and the Tenor dimension) -> tenor in YEARS.
_TENORS: dict[str, float] = {
    "3M": 0.25,
    "6M": 0.5,
    "12M": 1.0,
    "3Y": 3.0,
    "5Y": 5.0,
    "7Y": 7.0,
    "10Y": 10.0,
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


def _find_key(fieldnames: list[str], *candidates: str) -> str | None:
    for cand in candidates:
        for f in fieldnames:
            if f == cand:
                return f
    for cand in candidates:
        for f in fieldnames:
            if f.lower() == cand.lower():
                return f
    return None


def parse_csv(csv_text: str) -> list[CurvePoint]:
    """Parse a Norges Bank SDMX CSV into curve points. Pure (no network).

    The delimiter is sniffed (semicolon or comma). Each data row needs a TIME_PERIOD date, an
    OBS_VALUE rate, and a recognizable tenor token in the tenor dimension column; rows missing any
    of these (or with an unknown tenor) are skipped, never invented.
    """
    out: list[CurvePoint] = []
    sample = csv_text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delimiter)
    if not reader.fieldnames:
        return out
    fields = list(reader.fieldnames)
    date_key = _find_key(fields, "TIME_PERIOD")
    value_key = _find_key(fields, "OBS_VALUE")
    # The dataset has BOTH a code column (``TENOR`` -> "3Y") and a display column (``Tenor`` ->
    # "3 years"); we want the code column whose values match the tenor tokens.
    tenor_key = _find_key(fields, "TENOR", "Tenor")
    if date_key is None or value_key is None or tenor_key is None:
        return out
    for row in reader:
        raw_date = (row.get(date_key) or "").strip()
        token = (row.get(tenor_key) or "").strip().upper()
        raw_val = (row.get(value_key) or "").strip()
        tenor = _TENORS.get(token)
        if not raw_date or tenor is None or not raw_val:
            continue
        try:
            d = date.fromisoformat(raw_date[:10])
            value = float(raw_val)
        except ValueError:
            continue
        out.append(
            CurvePoint(
                "NO", "NOK", "govt", "nominal", "yield", round(tenor, 6), d, value
            )
        )
    return out


def _download(url: str, *, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted norges-bank.no host)
        return resp.read()


class NorgesBankCurveSource:
    """Fetches + parses Norges Bank generic government rates. ``SOURCE`` tags every stored row."""

    SOURCE = "norgesbank"
    COUNTRY = "NO"
    CURRENCY = "NOK"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        params = ["format=csv", "locale=en"]
        if start_date is not None:
            params.append(f"startPeriod={start_date.isoformat()}")
        if end_date is not None:
            params.append(f"endPeriod={end_date.isoformat()}")
        query = "&".join(params)
        url = f"{NB_BASE}/B..GBON?{query}"
        csv_text = _download(url).decode("utf-8", "replace")
        pts = parse_csv(csv_text)
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
