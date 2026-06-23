"""Hong Kong Monetary Authority Exchange Fund Bills & Notes yield-curve source adapter.

HKMA publishes a daily EFBN yield curve via its open JSON API (no key, free). Probed 2026-06-22:

  ``.../monthly-statistical-bulletin/efbn/efbn-yield-daily``
  → ``{"header": {...}, "result": {"datasize": N, "records": [{...}]}}``

Each record is one trading day. Bill yields are keyed ``efb_<n>d`` (days: 7/30/91/182/273/364) and
note yields ``efn_<n>y`` (years: 2/3/4/5/7/10/15); the curve's date is ``end_of_day``. Values are
% per annum; missing tenors come back ``null`` and are skipped.

The API is paginated and sorted by date DESCENDING. ``datasize`` reflects the *returned* page size
(it equals ``pagesize``), NOT the grand total — so we page on ``offset`` until a page returns fewer
than ``pagesize`` rows. Parsing (pure, per-record) is separated from the network paging loop.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import CurvePoint

HKMA_URL = (
    "https://api.hkma.gov.hk/public/market-data-and-statistics"
    "/monthly-statistical-bulletin/efbn/efbn-yield-daily"
)

# Field name → tenor in YEARS. Bills are quoted in days, notes in years.
TENOR_MAP: dict[str, float] = {
    "efb_7d": 7 / 365,
    "efb_30d": 30 / 365,
    "efb_91d": 91 / 365,
    "efb_182d": 182 / 365,
    "efb_273d": 273 / 365,
    "efb_364d": 364 / 365,
    "efn_2y": 2.0,
    "efn_3y": 3.0,
    "efn_4y": 4.0,
    "efn_5y": 5.0,
    "efn_7y": 7.0,
    "efn_10y": 10.0,
    "efn_15y": 15.0,
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"
_PAGE = 100


class CurveLayoutError(RuntimeError):
    """HKMA's record layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _parse_record(rec: dict) -> list[CurvePoint]:
    """Turn one EFBN daily record into curve points. Pure (no network)."""
    raw = rec.get("end_of_day")
    if not raw:
        raise CurveLayoutError(f"record has no 'end_of_day' date field: {sorted(rec)}")
    d = datetime.strptime(raw, "%Y-%m-%d").date()
    out: list[CurvePoint] = []
    for field, tenor in TENOR_MAP.items():
        v = rec.get(field)
        if v is None or v == "":
            continue
        out.append(
            CurvePoint(
                "HK", "HKD", "govt", "nominal", "yield", round(tenor, 6), d, float(v)
            )
        )
    return out


def _fetch_page(offset: int, *, timeout: int) -> list[dict]:
    qs = urlencode({"offset": offset, "pagesize": _PAGE})
    req = Request(f"{HKMA_URL}?{qs}", headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted HKMA host)
        payload = json.load(resp)
    header = payload.get("header") or {}
    if not header.get("success", False):
        raise CurveLayoutError(f"HKMA API error: {header}")
    return payload.get("result", {}).get("records", [])


class HkmaCurveSource:
    """Fetches + parses the HKMA EFBN daily yield curve. ``SOURCE`` tags every stored row."""

    SOURCE = "hkma"
    COUNTRY = "HK"
    CURRENCY = "HKD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        out: list[CurvePoint] = []
        offset = 0
        while True:
            records = _fetch_page(offset, timeout=120)
            if not records:
                break
            for rec in records:
                out.extend(_parse_record(rec))
            if len(records) < _PAGE:
                break
            offset += _PAGE
            # Records are date-DESC; once the whole page predates start_date we can stop paging.
            if start_date is not None:
                last = records[-1].get("end_of_day")
                if last and datetime.strptime(last, "%Y-%m-%d").date() < start_date:
                    break
        if start_date is not None:
            out = [p for p in out if p.as_of_date >= start_date]
        if end_date is not None:
            out = [p for p in out if p.as_of_date <= end_date]
        return out
