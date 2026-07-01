"""Hong Kong Monetary Authority Exchange Fund Bills & Notes — DAILY yield-curve source adapter.

HKMA's monthly-statistical-bulletin ``efbn-yield-daily`` endpoint carries clean benchmark tenors
(7d..15y) but only refreshes when the monthly bulletin publishes — so it ran ~a month stale. The
``daily-monetary-statistics/efbn-indicative-price`` endpoint instead serves the **latest business
day** EFBN indicative curve (Reuters-calculated twice daily from Eligible Market Makers'
bid/ask quotes). Probed 2026-07-01:

  ``.../daily-monetary-statistics/efbn-indicative-price?segment=IndicativePrice``
  → ``{"header": {...}, "result": {"records": [{"end_of_date","term","yield","price",...}]}}``

The ``IndicativePrice`` segment gives one row per standard term — ``1W 1M 3M 6M 9M 12M 2 YR`` —
as a % p.a. ``yield`` on ``end_of_date``. This is the FRESH source; the trade-off (per the sourcing
decision) is it only reaches ~2y — HKMA has no on-the-run EFN beyond ~3y, so the old bulletin's
5/7/10/15y benchmark points have no daily equivalent and are dropped. Because the API serves only
the latest business day, history accrues forward one day per run (older bulletin rows already stored
remain untouched). Parsing (pure, per-record) is separated from the network fetch.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import CurvePoint

HKMA_URL = (
    "https://api.hkma.gov.hk/public/market-data-and-statistics"
    "/daily-monetary-statistics/efbn-indicative-price"
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"
# Term label -> tenor in YEARS. Accepts "1W"/"3M"/"12M"/"2 YR"/"2YR"/"2Y" (case/space-insensitive).
_TERM_RE = re.compile(r"^\s*(\d+)\s*(W|M|Y|YR)\s*$", re.IGNORECASE)


class CurveLayoutError(RuntimeError):
    """HKMA's record layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _term_to_years(term: str | None) -> float | None:
    """'1W'->7/365, '3M'->0.25, '12M'->1.0, '2 YR'->2.0. Unknown/blank -> None (skipped)."""
    m = _TERM_RE.match(term or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).upper()
    if unit == "W":
        return round(n * 7 / 365, 6)
    if unit == "M":
        return round(n / 12, 6)
    return float(n)  # 'Y' / 'YR'


def parse_records(records: list[dict]) -> list[CurvePoint]:
    """Turn efbn-indicative-price ``IndicativePrice`` records into HK nominal curve points. Pure.

    A record with no parseable ``term`` or a null ``yield`` is skipped; a record with no
    ``end_of_date`` is a layout drift (fail loud). May emit nothing (weekends/holidays return no
    records) — the caller decides whether an empty result is acceptable."""
    out: list[CurvePoint] = []
    for rec in records:
        raw = rec.get("end_of_date")
        if not raw:
            raise CurveLayoutError(f"record has no 'end_of_date' date field: {sorted(rec)}")
        tenor = _term_to_years(rec.get("term"))
        y = rec.get("yield")
        if tenor is None or y is None or y == "":
            continue
        d = datetime.strptime(raw, "%Y-%m-%d").date()
        out.append(CurvePoint("HK", "HKD", "govt", "nominal", "yield", tenor, d, float(y)))
    return out


def _fetch(*, timeout: int) -> list[dict]:
    qs = urlencode({"segment": "IndicativePrice"})
    req = Request(f"{HKMA_URL}?{qs}", headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted HKMA host)
        payload = json.load(resp)
    header = payload.get("header") or {}
    if not header.get("success", False):
        raise CurveLayoutError(f"HKMA API error: {header}")
    return payload.get("result", {}).get("records", [])


class HkmaCurveSource:
    """Fetches + parses the HKMA EFBN daily indicative curve. ``SOURCE`` tags every stored row."""

    SOURCE = "hkma"
    COUNTRY = "HK"
    CURRENCY = "HKD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        pts = parse_records(_fetch(timeout=120))
        # The API serves the latest business day only; honour an explicit window if given.
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
