"""Bank of Canada Government-of-Canada benchmark-bond-yield source adapter.

The Bank of Canada Valet API publishes the *benchmark Government of Canada bond yields* group
(daily, % per annum) as JSON. Probed 2026-06-22:

  ``https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json``

The payload carries ``seriesDetail`` (series name → human label) and ``observations`` — a list of
``{"d": "YYYY-MM-DD", "<series>": {"v": "<value>"}}`` records. The nominal benchmark series are
``BD.CDN.<n>YR.DQ.YLD`` for n in 2/3/5/7/10 plus ``BD.CDN.LONG.DQ.YLD`` (a long-term ~30y proxy).
``BD.CDN.RRB.DQ.YLD`` is a Real Return Bond yield (real, not nominal) — excluded here.

This module separates **parsing** (pure, no network) from **downloading**.
"""

from __future__ import annotations

import json
from datetime import date
from urllib.request import Request, urlopen

from .base import CurvePoint

BOC_URL = "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json"

# Nominal GoC benchmark series → tenor in years. The long-term benchmark tracks ~30y.
SERIES_TENORS: dict[str, float] = {
    "BD.CDN.2YR.DQ.YLD": 2.0,
    "BD.CDN.3YR.DQ.YLD": 3.0,
    "BD.CDN.5YR.DQ.YLD": 5.0,
    "BD.CDN.7YR.DQ.YLD": 7.0,
    "BD.CDN.10YR.DQ.YLD": 10.0,
    "BD.CDN.LONG.DQ.YLD": 30.0,
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) QRP-rates/0.1"


class CurveLayoutError(RuntimeError):
    """BoC's Valet payload drifted from what the probe recorded (fail loud, never mis-map)."""


def parse_observations(payload: dict) -> list[CurvePoint]:
    """Parse a Valet JSON payload into nominal GoC benchmark yield points. Pure (no network)."""
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise CurveLayoutError("Valet payload has no 'observations' list")
    out: list[CurvePoint] = []
    for obs in observations:
        d_str = obs.get("d")
        if not isinstance(d_str, str):
            continue
        d = date.fromisoformat(d_str)
        for series, tenor in SERIES_TENORS.items():
            cell = obs.get(series)
            if not isinstance(cell, dict):
                continue
            v = cell.get("v")
            if v in (None, ""):
                continue
            out.append(
                CurvePoint("CA", "CAD", "govt", "nominal", "yield", tenor, d, float(v))
            )
    return out


def _download(url: str, *, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted BoC host)
        return resp.read()


class BocCurveSource:
    """Fetches + parses Bank of Canada benchmark GoC yields. ``SOURCE`` tags every stored row."""

    SOURCE = "boc"
    COUNTRY = "CA"
    CURRENCY = "CAD"

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]:
        payload = json.loads(_download(BOC_URL))
        pts = parse_observations(payload)
        if start_date is not None:
            pts = [p for p in pts if p.as_of_date >= start_date]
        if end_date is not None:
            pts = [p for p in pts if p.as_of_date <= end_date]
        return pts
