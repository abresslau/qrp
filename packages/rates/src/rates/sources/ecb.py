"""ECB euro-area yield-curve source adapters.

Two distinct ECB feeds, both served by the ECB Data Portal SDMX REST API as CSV
(``?format=csvdata``). Probed 2026-06-22:

  - **Yield Curve (YC)** — the euro-area government-bond curve, fitted with the Svensson model,
    published daily since 2004. Two universes live under the ``REF_AREA``-coded key: AAA-rated
    central governments (``G_N_A``, the benchmark → curve_set ``govt``) and ALL euro-area central
    governments (``G_N_C`` → curve_set ``govt_all``; the AAA−all spread is a credit/risk premium).
    Each publishes three rate types in the ``DATA_TYPE_FM`` dimension — spot (``SR_*``),
    instantaneous forward (``IF_*``) and par (``PY_*``) — over a standard grid (token ``SR_10Y``).
    We fetch one series per (universe, rate type, tenor) and concatenate. country="EU".

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

# Euro-area Svensson yield curves: two universes (REF_AREA-coded key) × three rate types × the grid.
YC_KEYS: dict[str, str] = {
    "govt": "B.U2.EUR.4F.G_N_A.SV_C_YM",      # AAA-rated central govts — the benchmark
    "govt_all": "B.U2.EUR.4F.G_N_C.SV_C_YM",  # all euro-area central govts
}
# rate_type → DATA_TYPE_FM token prefix: spot / instantaneous-forward / par.
YC_RATE_TOKENS: dict[str, str] = {"spot": "SR", "forward": "IF", "par": "PY"}
# maturity token → tenor in years.
YC_GRID: dict[str, float] = {
    "3M": 0.25, "6M": 0.5, "9M": 0.75, "1Y": 1.0, "2Y": 2.0, "3Y": 3.0,
    "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "15Y": 15.0, "20Y": 20.0, "30Y": 30.0,
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
    """Euro-area government-bond Svensson curves (daily). ``country`` = ``EU``.

    Fetches one series per (universe ``govt``/``govt_all``, rate type spot/forward/par, grid tenor)
    and concatenates them into the full curve set. A single bad/empty/unavailable series is
    tolerated (skipped) so a partial grid still loads — covering a transport error (OSError/HTTP), a
    garbled
    body (a 200 with an HTML/maintenance page → CurveLayoutError) or a non-UTF-8 response
    (UnicodeDecodeError). But if EVERY series fails (a wholesale outage or a layout drift), fetch
    raises rather than silently returning nothing.
    """

    SOURCE = "ecb"
    COUNTRY = "EU"
    CURRENCY = "EUR"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        params = _period_params(start_date, end_date)
        out: list[CurvePoint] = []
        attempts = 0
        failures = 0
        for curve_set, key in YC_KEYS.items():
            for rate_type, prefix in YC_RATE_TOKENS.items():
                for token, tenor in YC_GRID.items():
                    attempts += 1
                    url = f"{ECB_BASE}/YC/{key}.{prefix}_{token}?{params}"
                    try:
                        text = _download(url)
                        out.extend(
                            _parse_csv(
                                text,
                                country="EU",
                                curve_set=curve_set,
                                basis="nominal",
                                rate_type=rate_type,
                                tenor=tenor,
                            )
                        )
                    except (OSError, ValueError, CurveLayoutError):
                        # tolerate ONE bad series (transport error / garbled-200 body / bad decode)
                        # so a partial grid still loads; a wholesale failure is caught below.
                        failures += 1
                        continue
        if attempts and failures == attempts:
            raise CurveLayoutError(
                f"all {attempts} ECB yield-curve series failed to load "
                "— wholesale outage or SDMX layout drift"
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
