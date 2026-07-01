"""OECD long-term interest rate (10y government bond) source adapter.

A fallback 10-year sovereign benchmark for countries whose native daily curve is unavailable — in
particular **CH**, whose only free daily source (the SNB ``rendoblid`` spot curve) was discontinued
at 2025-07-31 (the monthly ``rendoblim`` and the ``rendopar`` NSS params stop on the same date). The
OECD publishes the standard "long-term interest rate" (the ~10y government bond yield, % p.a.)
monthly via its SDMX Data Explorer. Probed 2026-07-01 (CHE latest = 2026-05, 0.44%):

  ``.../OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/{geo}.M.IRLT.PA.....?format=csvfile``  (SDMX-CSV)

Same ``TIME_PERIOD``/``OBS_VALUE`` shape as the ECB/Eurostat feeds. It is monthly (a single 10y
point, NOT a fitted curve). Unlike the ECB long-term rate (anchored to the first of the month), a
monthly period here is anchored to the **last day of the month** — the long-term rate is a period
observation, and month-end dating keeps a ~1-month-lagged monthly series inside the staleness
cadence window rather than reading ~2 months old on day one. Emitted as ``basis='nominal'``,
``rate_type='yield'``, tenor 10 — distinct from the SNB ``spot`` rows, so the two coexist without a
key collision. Parsing (pure, testable) is separated from the network fetch.
"""

from __future__ import annotations

import calendar
import csv
import io
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

_OECD_URL_TMPL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
    "{geo}.M.IRLT.PA.....?startPeriod=1990-01&format=csvfile"
)
_TENOR = 10.0
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """The OECD SDMX-CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _month_end(period: str) -> date | None:
    """SDMX monthly ``YYYY-MM`` → the last calendar day of that month; anything else → None."""
    parts = period.split("-")
    if len(parts) != 2:
        return None
    try:
        y, m = int(parts[0]), int(parts[1])
        return date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError):
        return None


def parse_ltir(text: str, *, country: str, currency: str) -> list[CurvePoint]:
    """Parse the OECD IRLT SDMX-CSV into monthly 10y nominal-yield points. Pure (no network)."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "TIME_PERIOD" not in reader.fieldnames \
            or "OBS_VALUE" not in reader.fieldnames:
        raise CurveLayoutError(f"missing TIME_PERIOD/OBS_VALUE columns; got {reader.fieldnames}")
    out: list[CurvePoint] = []
    for row in reader:
        # defend against a widened key returning other measures (only IRLT is the long-term rate)
        if (row.get("MEASURE") or "IRLT").strip() != "IRLT":
            continue
        d = _month_end((row.get("TIME_PERIOD") or "").strip())
        raw = (row.get("OBS_VALUE") or "").strip()
        if d is None or not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append(CurvePoint(country, currency, "govt", "nominal", "yield", _TENOR, d, value))
    return out


class OecdLtirCurveSource:
    """Fetches + parses the OECD long-term (10y) interest rate for a country. ``SOURCE`` tags rows.

    Parameterised: ``COUNTRY`` (ISO-2, store key) + ``CURRENCY`` are per-instance; ``geo`` is the
    OECD ISO-3 ``REF_AREA`` (CH→CHE). ``SOURCE`` stays class-level.
    """

    SOURCE = "oecd"

    def __init__(self, *, country: str, geo: str, currency: str) -> None:
        self.COUNTRY = country
        self.CURRENCY = currency
        self._geo = geo

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        req = Request(_OECD_URL_TMPL.format(geo=self._geo), headers={"User-Agent": _UA})
        with urlopen(req, timeout=120) as resp:  # noqa: S310 (trusted OECD host)
            text = resp.read().decode("utf-8", "replace")
        pts = parse_ltir(text, country=self.COUNTRY, currency=self.CURRENCY)
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
