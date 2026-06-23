"""ECB euro-area yield-curve source adapters.

Two distinct ECB feeds, both served by the ECB Data Portal SDMX REST API as CSV
(``?format=csvdata``). Probed 2026-06-22:

  - **Yield Curve (YC)** — the euro-area AAA-rated government-bond spot curve, fitted with the
    Svensson model, published daily since 2004. One series per maturity; the maturity lives in
    the ``DATA_TYPE_FM`` dimension as a token like ``SR_10Y``. We enumerate the standard grid and
    fetch one series per tenor. country="EU", rate_type="spot".

  - **Long-term interest rate for convergence (IRS)** — the Maastricht 10-year benchmark government
    bond yield, monthly since 1986, one series per member state (``REF_AREA`` dimension). country
    is the member (FR/IT/ES), rate_type="yield", tenor=10y.

Both CSVs carry ``TIME_PERIOD`` (the observation date — daily ``YYYY-MM-DD`` for YC, monthly
``YYYY-MM`` for IRS) and ``OBS_VALUE`` (% per annum). ``TIME_PERIOD`` is the curve's
``as_of_date`` (for monthly periods we anchor to the first of the month), never the ingest date.

This module separates **parsing** (pure, testable, no network) from **downloading**.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

# Euro-area AAA spot curve: DATA_TYPE_FM maturity token → tenor in years.
YC_KEY = "B.U2.EUR.4F.G_N_A.SV_C_YM"
YC_TENORS: dict[str, float] = {
    "SR_3M": 0.25,
    "SR_6M": 0.5,
    "SR_9M": 0.75,
    "SR_1Y": 1.0,
    "SR_2Y": 2.0,
    "SR_3Y": 3.0,
    "SR_5Y": 5.0,
    "SR_7Y": 7.0,
    "SR_10Y": 10.0,
    "SR_15Y": 15.0,
    "SR_20Y": 20.0,
    "SR_30Y": 30.0,
}

# Long-term convergence rate series key template (one per member state via REF_AREA).
IRS_KEY_TMPL = "M.{cc}.L.L40.CI.0000.EUR.N.Z"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """ECB's CSV layout drifted from what the probe recorded (fail loud, never mis-map)."""


def _period_to_date(period: str) -> date:
    """ECB ``TIME_PERIOD`` → date. Daily is ``YYYY-MM-DD``; monthly ``YYYY-MM`` → first of month."""
    parts = period.split("-")
    if len(parts) == 3:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    raise CurveLayoutError(f"unrecognised TIME_PERIOD format: {period!r}")


def _parse_csv(
    text: str,
    *,
    country: str,
    curve_set: str,
    basis: str,
    rate_type: str,
    tenor: float,
) -> list[CurvePoint]:
    """Parse one ECB SDMX CSV (one series) into curve points. Pure (no network)."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "TIME_PERIOD" not in reader.fieldnames:
        raise CurveLayoutError(
            f"missing TIME_PERIOD column; got {reader.fieldnames}"
        )
    if "OBS_VALUE" not in reader.fieldnames:
        raise CurveLayoutError(f"missing OBS_VALUE column; got {reader.fieldnames}")
    out: list[CurvePoint] = []
    for row in reader:
        period = (row.get("TIME_PERIOD") or "").strip()
        raw = (row.get("OBS_VALUE") or "").strip()
        if not period or not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append(
            CurvePoint(
                country,
                "EUR",
                curve_set,
                basis,
                rate_type,
                round(tenor, 6),
                _period_to_date(period),
                value,
            )
        )
    return out


def _download(url: str, *, timeout: int = 120) -> str:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted ECB host)
        return resp.read().decode("utf-8")


def _period_params(start_date: date | None, end_date: date | None) -> str:
    parts: list[str] = ["format=csvdata"]
    if start_date is not None:
        parts.append(f"startPeriod={start_date.isoformat()}")
    if end_date is not None:
        parts.append(f"endPeriod={end_date.isoformat()}")
    return "&".join(parts)


class EcbYieldCurveSource:
    """Euro-area AAA government-bond Svensson spot curve (daily). ``country`` = ``EU``.

    Fetches one series per standard-grid tenor and concatenates them into a full curve. A single
    bad/empty tenor is tolerated (skipped) so a partial grid still loads; the loader's attempt-all
    driver plus the core-grid VERIFY guard catch a wholesale outage.
    """

    SOURCE = "ecb"
    COUNTRY = "EU"
    CURRENCY = "EUR"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        params = _period_params(start_date, end_date)
        out: list[CurvePoint] = []
        for token, tenor in YC_TENORS.items():
            url = f"{ECB_BASE}/YC/{YC_KEY}.{token}?{params}"
            text = _download(url)
            out.extend(
                _parse_csv(
                    text,
                    country="EU",
                    curve_set="govt",
                    basis="nominal",
                    rate_type="spot",
                    tenor=tenor,
                )
            )
        return out


class EcbLongTermRateSource:
    """Maastricht long-term (10y) government-bond yield for one euro-area member (monthly).

    Parameterised by ``country`` (FR/IT/ES/…): ``COUNTRY`` is set per-instance; ``CURRENCY`` and
    ``SOURCE`` stay class-level. Emits one point per month at tenor 10y, rate_type="yield".
    """

    SOURCE = "ecb"
    CURRENCY = "EUR"

    def __init__(self, country: str) -> None:
        self.COUNTRY = country

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        params = _period_params(start_date, end_date)
        key = IRS_KEY_TMPL.format(cc=self.COUNTRY)
        url = f"{ECB_BASE}/IRS/{key}?{params}"
        text = _download(url)
        return _parse_csv(
            text,
            country=self.COUNTRY,
            curve_set="govt",
            basis="nominal",
            rate_type="yield",
            tenor=10.0,
        )
