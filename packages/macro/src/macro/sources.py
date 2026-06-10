"""Fetchers for public macro sources (no API key, stdlib only).

Each fetcher returns ``(series_meta, observations)`` tuples where ``series_meta`` is a dict
({series_id, source, name, geo, unit, frequency}) and ``observations`` is a list of
``(date, float)``. Pure I/O — callers persist. Network failures raise; partial/garbled
responses yield empty observations (never fabricated).
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import date

_UA = {"User-Agent": "qrp-macro/1.0 (personal research)"}
_TIMEOUT = 20.0


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (trusted hosts)
        return r.read()


# --- World Bank (annual indicators, JSON) ---------------------------------------------
WB_BASE = (
    "https://api.worldbank.org/v2/country/{geo}/indicator/{ind}"
    "?format=json&per_page=500&date=1990:{end_year}"
)


def fetch_worldbank(indicator: str, name: str, unit: str, geos: list[str]) -> list[tuple[dict, list]]:
    """One series per country. WB JSON = [meta, [obs...]]; obs.date is a year string."""
    out: list[tuple[dict, list]] = []
    for geo in geos:
        url = WB_BASE.format(geo=geo, ind=indicator, end_year=date.today().year)
        payload = json.loads(_get(url).decode("utf-8", "replace"))
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            continue
        geo_label = None
        obs: list[tuple[date, float]] = []
        for row in payload[1]:
            val = row.get("value")
            yr = row.get("date")
            geo_label = (row.get("country") or {}).get("value") or geo_label
            if val is None or not yr:
                continue
            obs.append((date(int(yr), 12, 31), float(val)))
        obs.sort()
        meta = {
            "series_id": f"WB:{indicator}:{geo}",
            "source": "worldbank",
            "name": name,
            "geo": geo_label or geo,
            "unit": unit,
            "frequency": "annual",
        }
        out.append((meta, obs))
    return out


# --- ECB Data Portal (CSV) ------------------------------------------------------------
ECB_BASE = "https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata"


def fetch_ecb(key: str, series_id: str, name: str, unit: str, frequency: str) -> tuple[dict, list]:
    """An ECB series key (e.g. FM/M.U2.EUR.4F.KR.MRR_FR.LEV). CSV has TIME_PERIOD,OBS_VALUE."""
    text = _get(ECB_BASE.format(key=key)).decode("utf-8", "replace")
    reader = csv.DictReader(io.StringIO(text))
    raw_obs: list[tuple[date, float]] = []
    for row in reader:
        period = (row.get("TIME_PERIOD") or "").strip()
        raw = (row.get("OBS_VALUE") or "").strip()
        if not period or not raw:
            continue
        try:
            d = _parse_period(period)
            raw_obs.append((d, float(raw)))
        except (ValueError, TypeError):
            continue
    raw_obs.sort()
    # A policy rate is a step function; a daily feed repeats the level every business day.
    # Keep only change-points (+ the first and last obs) so the stored series is meaningful.
    obs: list[tuple[date, float]] = []
    for i, (d, v) in enumerate(raw_obs):
        if i == 0 or i == len(raw_obs) - 1 or v != raw_obs[i - 1][1]:
            obs.append((d, v))
    meta = {
        "series_id": series_id,
        "source": "ecb",
        "name": name,
        "geo": "Euro area",
        "unit": unit,
        "frequency": frequency,
    }
    return meta, obs


def _parse_period(p: str) -> date:
    """ECB TIME_PERIOD: 'YYYY', 'YYYY-MM', or 'YYYY-MM-DD'."""
    parts = p.split("-")
    if len(parts) == 1:
        return date(int(parts[0]), 12, 31)
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), int(parts[1]), int(parts[2]))
