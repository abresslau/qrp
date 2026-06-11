"""Fetchers for public macro sources (no API key, stdlib only).

Each fetcher returns ``(series_meta, observations)`` tuples where ``series_meta`` is a dict
({series_id, source, name, geo, unit, frequency}) and ``observations`` is a list of
``(date, float)``. Pure I/O — callers persist. Network failures raise; partial/garbled
responses yield empty observations (never fabricated).

Monthly dating convention: SDMX-style ``YYYY-MM`` periods (ECB, OECD, Eurostat) are dated
first-of-month by ``_parse_period``; FiscalData rows keep the source's own ``record_date``
as-is (month-END for the monthly ``avg_interest_rates`` dataset). The ``obs_date`` is the
source-stated observation date, not a normalised period key.
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.error
import urllib.request
from datetime import date

_UA = {"User-Agent": "qrp-macro/1.0 (personal research)"}
_TIMEOUT = 20.0


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (trusted hosts)
        return r.read()


def _parse_period(p: str) -> date:
    """SDMX TIME_PERIOD: 'YYYY' (→ Dec 31), 'YYYY-MM' (→ 1st), or 'YYYY-MM-DD'.

    Anything else raises (quarterly/weekly forms like '2025-Q1' fail at int(); a >3-part
    string is rejected rather than silently truncated to its first three parts).
    """
    parts = p.split("-")
    if len(parts) > 3:
        raise ValueError(f"unsupported TIME_PERIOD {p!r}")
    if len(parts) == 1:
        return date(int(parts[0]), 12, 31)
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _finite(raw: str | float) -> float:
    """``float()`` that REFUSES NaN/Infinity (raises ValueError like any garbled value).

    Postgres DOUBLE PRECISION would happily store them, but the API's JSON encoder
    (``allow_nan=False``) cannot serialize them — one bad vendor cell would 500 every
    macro endpoint. Non-finite is treated as garbled: skipped, never stored.
    """
    v = float(raw)
    if not math.isfinite(v):
        raise ValueError(f"non-finite value {raw!r}")
    return v


# --- World Bank (annual indicators, JSON) ---------------------------------------------
WB_BASE = (
    "https://api.worldbank.org/v2/country/{geo}/indicator/{ind}"
    "?format=json&per_page=500&date=1990:{end_year}"
)


def fetch_worldbank(
    indicator: str, name: str, unit: str, geos: list[str]
) -> list[tuple[dict, list]]:
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


# --- SDMX-CSV (shared by the ECB Data Portal and OECD: TIME_PERIOD/OBS_VALUE columns) ---


def parse_sdmx_csv(text: str, ref_area: str | None = None) -> list[tuple[date, float]]:
    """Parse SDMX-CSV rows (TIME_PERIOD, OBS_VALUE) into sorted ``(date, value)`` pairs.

    Garbled/partial rows are skipped, never invented. ``ref_area`` (when given AND the CSV
    carries a REF_AREA column) drops rows for other areas — a guard against a wildcard key
    accidentally merging countries into one series.
    """
    reader = csv.DictReader(io.StringIO(text))
    obs: list[tuple[date, float]] = []
    for row in reader:
        if ref_area is not None and "REF_AREA" in row and (row.get("REF_AREA") or "") != ref_area:
            continue
        period = (row.get("TIME_PERIOD") or "").strip()
        raw = (row.get("OBS_VALUE") or "").strip()
        if not period or not raw:
            continue
        try:
            obs.append((_parse_period(period), _finite(raw)))
        except (ValueError, TypeError):
            continue
    obs.sort()
    return obs


# --- ECB Data Portal (SDMX-CSV) ---------------------------------------------------------
ECB_BASE = "https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata"


def fetch_ecb(key: str, series_id: str, name: str, unit: str, frequency: str) -> tuple[dict, list]:
    """An ECB series key (e.g. FM/M.U2.EUR.4F.KR.MRR_FR.LEV). CSV has TIME_PERIOD,OBS_VALUE."""
    text = _get(ECB_BASE.format(key=key)).decode("utf-8", "replace")
    raw_obs = parse_sdmx_csv(text)
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


# --- OECD SDMX (monthly CPI, SDMX-CSV; same TIME_PERIOD/OBS_VALUE shape as ECB) ---------
OECD_CPI_BASE = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/"
    "{geo}.M.N.CPI.PA._T.N.GY?startPeriod=1990-01&format=csvfile"
)


def fetch_oecd_cpi(geo: str) -> tuple[dict, list]:
    """OECD CPI YoY (%, monthly) for one REF_AREA (ISO-3). Key: <GEO>.M.N.CPI.PA._T.N.GY.

    An area the flow doesn't serve gets HTTP 404 ``NoRecordsFound`` (verified live) —
    mapped to empty observations so the caller's no-data rule omits the series (never
    faked, and not reported as a failure). Other HTTP errors still raise.
    """
    try:
        text = _get(OECD_CPI_BASE.format(geo=geo)).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # NoRecordsFound: the flow has no data for this area
            text = ""
        else:
            raise
    obs = parse_sdmx_csv(text, ref_area=geo)
    meta = {
        "series_id": f"OECD:CPI:{geo}",
        "source": "oecd",
        "name": "CPI inflation (YoY, monthly)",
        "geo": geo,
        "unit": "% per year",
        "frequency": "monthly",
    }
    return meta, obs


# --- US Treasury FiscalData (JSON, paginated; values arrive as strings) -----------------
FISCALDATA_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


def fetch_fiscaldata_rows(endpoint: str, fields: str, page_size: int = 10000) -> list[dict]:
    """All data rows from a FiscalData dataset, driven by the response's ``meta.total-pages``.

    A short-page heuristic alone would silently truncate to one page if the server ever
    caps ``page[size]`` below the requested value — so the authoritative page count is
    used when present (it reflects the server's ACTUAL pagination), with short-page as
    the fallback only when ``meta`` is absent. A response without a ``data`` key is an
    error (FiscalData error envelope), never end-of-stream. ``fields`` trims the payload
    server-side. Numeric values arrive as STRINGS (e.g. ``"3.690"``) — callers parse.
    """
    if page_size < 1:
        raise ValueError(f"page_size must be >= 1, got {page_size}")
    rows: list[dict] = []
    page = 1
    while True:
        url = (
            f"{FISCALDATA_BASE}{endpoint}?fields={fields}"
            f"&page%5Bsize%5D={page_size}&page%5Bnumber%5D={page}&sort=record_date"
        )
        payload = json.loads(_get(url).decode("utf-8", "replace"))
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"fiscaldata {endpoint}: response has no 'data' (page {page})")
        batch = payload["data"] or []
        rows.extend(r for r in batch if isinstance(r, dict))
        total_pages = (payload.get("meta") or {}).get("total-pages")
        if isinstance(total_pages, int):
            if page >= total_pages:
                return rows
        elif len(batch) < page_size:  # no meta: fall back to the short-page heuristic
            return rows
        page += 1


def _fiscaldata_obs(rows: list[dict], value_field: str) -> list[tuple[date, float]]:
    """(record_date, value_field) pairs; rows with missing/garbled values skipped."""
    obs: list[tuple[date, float]] = []
    for r in rows:
        d_raw = (r.get("record_date") or "").strip()
        v_raw = (r.get(value_field) or "").strip()
        if not d_raw or not v_raw:
            continue
        try:
            obs.append((date.fromisoformat(d_raw), _finite(v_raw)))
        except (ValueError, TypeError):
            continue
    obs.sort()
    return obs


def fetch_fiscaldata_debt() -> tuple[dict, list]:
    """US total public debt outstanding (daily, 'Debt to the Penny'), scaled to USD trillions.

    Scaling is a labelled unit conversion (raw dollars ~3.9e13 are unreadable on every
    surface), not a transformation of the data.
    """
    rows = fetch_fiscaldata_rows(
        "/v2/accounting/od/debt_to_penny", "record_date,tot_pub_debt_out_amt"
    )
    obs = [(d, v / 1e12) for d, v in _fiscaldata_obs(rows, "tot_pub_debt_out_amt")]
    meta = {
        "series_id": "UST:DEBT",
        "source": "fiscaldata",
        "name": "US total public debt outstanding",
        "geo": "United States",
        "unit": "USD trillions",
        "frequency": "daily",
    }
    return meta, obs


# Marketable security classes carried as separate series (the dataset interleaves them).
_UST_SECURITIES: dict[str, str] = {
    "Treasury Bills": "BILLS",
    "Treasury Notes": "NOTES",
    "Treasury Bonds": "BONDS",
}


def fetch_fiscaldata_avg_rates() -> list[tuple[dict, list]]:
    """US Treasury average interest rates (monthly, month-end record_date), one series per
    marketable class (Bills/Notes/Bonds). Non-marketable and unknown classes are ignored."""
    rows = fetch_fiscaldata_rows(
        "/v2/accounting/od/avg_interest_rates",
        "record_date,security_type_desc,security_desc,avg_interest_rate_amt",
    )
    by_sec: dict[str, list[dict]] = {sec: [] for sec in _UST_SECURITIES}
    for r in rows:
        if (r.get("security_type_desc") or "").strip() != "Marketable":
            continue
        sec = (r.get("security_desc") or "").strip()
        if sec in by_sec:
            by_sec[sec].append(r)
    out: list[tuple[dict, list]] = []
    for sec, key in _UST_SECURITIES.items():
        meta = {
            "series_id": f"UST:AVG_RATE:{key}",
            "source": "fiscaldata",
            "name": f"US Treasury avg interest rate — {sec.removeprefix('Treasury ')}",
            "geo": "United States",
            "unit": "%",
            "frequency": "monthly",
        }
        out.append((meta, _fiscaldata_obs(by_sec[sec], "avg_interest_rate_amt")))
    return out


# --- Eurostat (JSON-stat 2.0) ------------------------------------------------------------
EUROSTAT_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "{code}?format=JSON&lang=en&sinceTimePeriod={since}{filters}"
)


def fetch_eurostat(
    code: str,
    filters: dict[str, str],
    series_id: str,
    name: str,
    unit: str,
    since: str = "1996-01",
) -> tuple[dict, list]:
    """One pinned series from a Eurostat JSON-stat 2.0 dataset.

    Supports ONLY the single-series shape: every non-time dimension must be pinned to
    exactly one category by ``filters`` (asserted — a loose or invalid pin raises so the
    misconfiguration is attributed per-series, not silently merged/omitted). With that
    shape the sparse flat ``value`` index equals the time index. Missing periods are
    simply absent — skipped, never filled.
    """
    qs = "".join(f"&{k}={v}" for k, v in filters.items())
    payload = json.loads(
        _get(EUROSTAT_BASE.format(code=code, since=since, filters=qs)).decode("utf-8", "replace")
    )
    dims: list[str] = payload.get("id") or []
    sizes: list[int] = payload.get("size") or []
    for dim, size in zip(dims, sizes, strict=True):  # mismatched id/size = malformed payload
        if dim != "time" and size != 1:
            raise ValueError(
                f"eurostat {code}: dimension {dim!r} not pinned to one category (size {size})"
            )
    time_index = payload.get("dimension", {}).get("time", {}).get("category", {}).get("index", {})
    value = payload.get("value") or {}
    # JSON-stat 2.0 also permits ARRAY encodings for `value` and `category.index`; this
    # parser supports only the object form Eurostat serves — refuse the rest loudly so a
    # format change is attributed per-series instead of crashing with an AttributeError.
    if not isinstance(time_index, dict):
        raise ValueError(
            f"eurostat {code}: unsupported time category.index encoding "
            f"({type(time_index).__name__}); only the object form is supported"
        )
    if not isinstance(value, dict):
        raise ValueError(
            f"eurostat {code}: unsupported 'value' encoding ({type(value).__name__}); "
            "only the object form is supported"
        )
    pos_to_period = {pos: period for period, pos in time_index.items()}
    obs: list[tuple[date, float]] = []
    for k, v in value.items():
        if v is None:
            continue
        try:
            obs.append((_parse_period(pos_to_period[int(k)]), _finite(v)))
        except (KeyError, ValueError, TypeError):
            continue
    obs.sort()
    geo_labels = (
        payload.get("dimension", {}).get("geo", {}).get("category", {}).get("label", {})
    )
    geo = next(iter(geo_labels.values()), None) or filters.get("geo")
    meta = {
        "series_id": series_id,
        "source": "eurostat",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": "monthly",
    }
    return meta, obs
