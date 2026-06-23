"""US Treasury daily par-yield curve source adapter.

The US Treasury publishes its daily nominal par yield curve (the CMT/constant-maturity series)
as an Atom/XML feed on the resource center — NOT on the fiscaldata JSON API. One request returns
one calendar year: ``?data=daily_treasury_yield_curve&field_tdr_date_value=<YYYY>`` yields one
``<entry>`` per business day, each carrying NEW_DATE plus ``BC_<TENOR>`` par-rate columns in
**% per annum**. No API key. History goes back to 1990 (early years omit the short/long tenors —
1M/2M arrived 2001-07, 4M arrived 2022-10, 20Y has a 1987-2006 gap — those cells are simply absent
and skipped, never invented).

This module separates **parsing** (pure, testable, no network) from **downloading**, mirroring the
BoE adapter and the macro package's Treasury parser (reimplemented standalone — ``rates`` is a peer
of ``macro`` and must not import from it).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

TREASURY_PAR_YIELD_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

# Atom + Microsoft ADO dataservices namespaces used by the feed.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_D_NS = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"

# BC_<TENOR> property tag -> tenor in YEARS. Sub-year tenors are exact fractions (1M = 1/12).
_TENORS: dict[str, float] = {
    "BC_1MONTH": 1 / 12,
    "BC_2MONTH": 2 / 12,
    "BC_3MONTH": 0.25,
    "BC_4MONTH": 4 / 12,
    "BC_6MONTH": 0.5,
    "BC_1YEAR": 1.0,
    "BC_2YEAR": 2.0,
    "BC_3YEAR": 3.0,
    "BC_5YEAR": 5.0,
    "BC_7YEAR": 7.0,
    "BC_10YEAR": 10.0,
    "BC_20YEAR": 20.0,
    "BC_30YEAR": 30.0,
}


def _finite(raw: str) -> float:
    """``float()`` that REFUSES NaN/Infinity — a non-finite cell is garbled, skipped not stored."""
    v = float(raw)
    if not math.isfinite(v):
        raise ValueError(f"non-finite value {raw!r}")
    return v


def parse_par_yield(xml_text: str) -> list[CurvePoint]:
    """Parse one year's Treasury par-yield Atom feed into curve points. Pure (no network).

    One ``<entry>`` per business day; NEW_DATE is the observation date (an ISO datetime, taken
    date-only). A missing/blank/garbled tenor cell is skipped for that day (a tenor with no history
    yet, or a holiday gap), never invented.
    """
    out: list[CurvePoint] = []
    root = ET.fromstring(xml_text)
    for entry in root.iter(f"{_ATOM_NS}entry"):
        node = entry.find(f".//{_D_NS}NEW_DATE")
        if node is None or not (node.text or "").strip():
            continue
        try:
            d = date.fromisoformat((node.text or "").strip()[:10])
        except ValueError:
            continue
        for tag, tenor in _TENORS.items():
            cell = entry.find(f".//{_D_NS}{tag}")
            raw = (cell.text or "").strip() if cell is not None else ""
            if not raw:
                continue
            try:
                value = _finite(raw)
            except (ValueError, TypeError):
                continue
            out.append(
                CurvePoint(
                    "US", "USD", "govt", "nominal", "par", round(tenor, 6), d, value
                )
            )
    return out


def _download(url: str, *, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted treasury.gov host)
        return resp.read()


class UsTreasuryCurveSource:
    """Fetches + parses the US Treasury daily par-yield curve. ``SOURCE`` tags every stored row."""

    SOURCE = "ustreasury"
    COUNTRY = "US"
    CURRENCY = "USD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        end_year = (end_date or date.today()).year
        start_year = max(1990, start_date.year) if start_date is not None else 1990
        pts: list[CurvePoint] = []
        for year in range(start_year, end_year + 1):
            xml_text = _download(TREASURY_PAR_YIELD_BASE.format(year=year)).decode(
                "utf-8", "replace"
            )
            pts.extend(parse_par_yield(xml_text))
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
