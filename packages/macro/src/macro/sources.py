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
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

_UA = {"User-Agent": "qrp-macro/1.0 (personal research)"}
_TIMEOUT = 20.0


def _get(url: str, timeout: float = _TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (trusted hosts)
        return r.read()


def _get_retry(url: str, timeout: float = 45.0, attempts: int = 4) -> bytes:
    """``_get`` with backoff for slow/throttled hosts (BCB returns 429/5xx on bursts and is
    occasionally slow on deep-history windows). Retries on timeout and transient HTTP/URL
    errors; a 404 (no data in window) propagates so callers can treat it as empty."""
    delay = 1.5
    for i in range(attempts):
        try:
            return _get(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 or exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
            last = exc
        if i < attempts - 1:
            time.sleep(delay)
            delay *= 2
    raise last


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
    indicator: str, name: str, unit: str, geos: list[str], scale: float = 1.0
) -> list[tuple[dict, list]]:
    """One series per country. WB JSON = [meta, [obs...]]; obs.date is a year string.

    ``scale`` is a labelled unit conversion (e.g. 1e-6 with unit "millions" for population
    head-counts — the UST:DEBT trillions precedent), not a transformation of the data.
    """
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
            obs.append((date(int(yr), 12, 31), float(val) * scale))
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


# --- US Treasury Daily Par Yield Curve (home.treasury.gov XML Atom feed) -----------------
# The par yield curve is NOT on the fiscaldata.treasury.gov JSON API — it is published as
# an Atom/XML feed on the Treasury resource center. ?data=daily_treasury_yield_curve with
# field_tdr_date_value=<YYYY> returns one <entry> per business day for that year; each
# entry's <m:properties> carries NEW_DATE plus BC_<TENOR> par rate columns. No API key.
TREASURY_PAR_YIELD_BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

# Atom + Microsoft ADO dataservices namespaces used by the feed.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_D_NS = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"

# The two tenors a macro desk lives on (2s10s). BC_<TENOR> is the par yield column name.
_PAR_TENORS: dict[str, tuple[str, str]] = {
    # series_id suffix -> (XML property tag, human label)
    "3M": ("BC_3MONTH", "3-month"),
    "2Y": ("BC_2YEAR", "2-year"),
    "10Y": ("BC_10YEAR", "10-year"),
    "30Y": ("BC_30YEAR", "30-year"),
}


def parse_treasury_par_yield(xml_text: str) -> dict[str, list[tuple[date, float]]]:
    """Parse the Treasury par-yield Atom feed into ``{tenor_suffix: [(date, rate)]}``.

    One <entry> per business day; NEW_DATE is the observation date (an ISO datetime,
    taken date-only). A missing/blank/garbled tenor cell is skipped for that day (a fresh
    tenor with no history yet, or a holiday gap), never invented. Returns sorted pairs.
    """
    out: dict[str, list[tuple[date, float]]] = {suffix: [] for suffix in _PAR_TENORS}
    root = ET.fromstring(xml_text)
    for entry in root.iter(f"{_ATOM_NS}entry"):
        props = entry.find(f".//{_D_NS}NEW_DATE")
        if props is None or not (props.text or "").strip():
            continue
        try:
            d = date.fromisoformat((props.text or "").strip()[:10])
        except ValueError:
            continue
        for suffix, (tag, _label) in _PAR_TENORS.items():
            cell = entry.find(f".//{_D_NS}{tag}")
            raw = (cell.text or "").strip() if cell is not None else ""
            if not raw:
                continue
            try:
                out[suffix].append((d, _finite(raw)))
            except (ValueError, TypeError):
                continue
    for suffix in out:
        out[suffix].sort()
    return out


def fetch_treasury_par_yield(start_year: int = 1990) -> list[tuple[dict, list]]:
    """US Treasury par yield curve 2Y & 10Y (daily), one series per tenor.

    The feed is per-year, so this fetches each year from ``start_year`` to the current
    year and concatenates. A year with no published data yields an empty feed (no entries)
    and simply contributes nothing — never faked. Returns ``(meta, observations)`` per tenor.
    """
    per_tenor: dict[str, list[tuple[date, float]]] = {suffix: [] for suffix in _PAR_TENORS}
    for year in range(start_year, date.today().year + 1):
        xml_text = _get(TREASURY_PAR_YIELD_BASE.format(year=year)).decode("utf-8", "replace")
        for suffix, obs in parse_treasury_par_yield(xml_text).items():
            per_tenor[suffix].extend(obs)
    out: list[tuple[dict, list]] = []
    for suffix, (_tag, label) in _PAR_TENORS.items():
        obs = per_tenor[suffix]
        obs.sort()
        meta = {
            "series_id": f"UST:PAR_YIELD:{suffix}",
            "source": "treasury",
            "name": f"US Treasury par yield — {label}",
            "geo": "United States",
            "unit": "%",
            "frequency": "daily",
        }
        out.append((meta, obs))
    return out


# --- BCB SGS (Banco Central do Brasil — Sistema Gerenciador de Séries Temporais) --------
# Open JSON REST, no API key. Range queries are capped at ~10 years server-side, so history
# is fetched in decade windows and concatenated. `valor` is a string with a '.' decimal; an
# empty `valor` is a genuine gap (skipped, never faked). The BCB returns HTTP 406 to a
# default library User-Agent — the module-wide custom UA in `_get` avoids it.
BCB_SGS_BASE = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
    "?formato=json&dataInicial={start}&dataFinal={end}"
)


def _parse_br_date(s: str) -> date:
    """BCB SGS dates are dd/MM/yyyy (monthly series are dated to the 1st)."""
    d, m, y = s.split("/")
    return date(int(y), int(m), int(d))


def _bcb_get_json(url: str, attempts: int = 4):
    """Fetch + JSON-parse a BCB SGS window, retrying transient non-JSON responses.

    Beyond the HTTP/timeout retries in ``_get_retry``, the BCB sometimes returns a 200 with
    an HTML throttling/error page that ``json.loads`` rejects — retry those with backoff
    rather than failing the whole series on a transient hiccup. A 404 means no data in the
    window (returns ``[]``); a persistent decode failure re-raises (attributed, not silent)."""
    delay = 1.5
    last: Exception | None = None
    for i in range(attempts):
        try:
            body = _get_retry(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:  # 200 + HTML error page (transient throttle)
            last = exc
            if i < attempts - 1:
                time.sleep(delay)
                delay *= 2
    raise last


def fetch_bcb_sgs(
    code: int,
    series_id: str,
    name: str,
    unit: str,
    frequency: str,
    geo: str = "Brazil",
    scale: float = 1.0,
    start_year: int = 1990,
    compress_steps: bool = False,
) -> tuple[dict, list]:
    """One BCB SGS series by numeric code, fetched in ≤10-year windows and concatenated.

    ``scale`` is a labelled unit conversion (the UST:DEBT trillions precedent), e.g. 1e-9 to
    store an R$-thousand money aggregate as R$ trillions, or 1e-3 to store a USD-million
    reserves series as USD billions — never a transformation of the data. ``compress_steps``
    keeps only change-points (plus the first and last obs) for a step-function series like
    the Selic target, so a daily feed repeating the same level every business day stores as
    a meaningful step series (the ECB policy-rate precedent).
    """
    raw: list[tuple[date, float]] = []
    this_year = date.today().year
    start = start_year
    while start <= this_year:
        chunk_end = min(start + 9, this_year)
        url = BCB_SGS_BASE.format(code=code, start=f"01/01/{start}", end=f"31/12/{chunk_end}")
        payload = _bcb_get_json(url)
        if isinstance(payload, list):
            for row in payload:
                d_raw = (row.get("data") or "").strip()
                v_raw = (row.get("valor") or "").strip()
                if not d_raw or not v_raw:
                    continue
                try:
                    raw.append((_parse_br_date(d_raw), _finite(v_raw) * scale))
                except (ValueError, TypeError):
                    continue
        start = chunk_end + 1
    obs = sorted(dict(raw).items())  # dedupe inclusive decade boundaries, then sort
    if compress_steps:
        obs = [
            (d, v)
            for i, (d, v) in enumerate(obs)
            if i == 0 or i == len(obs) - 1 or v != obs[i - 1][1]
        ]
    meta = {
        "series_id": series_id,
        "source": "bcb",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": frequency,
    }
    return meta, obs


# --- US BLS (Bureau of Labor Statistics — CPI, unemployment, payrolls) -------------------
# Public API v1, no key (FRED is blocked in-env; BLS fills the US gap). v1 caps a request at
# ~10 years, so history is fetched in decade windows. Response: Results.series[0].data =
# [{year, period:'M01'..'M12'|'M13'(annual avg, skipped), value}]. Values are strings.
BLS_BASE = "https://api.bls.gov/publicAPI/v1/timeseries/data/{series}"


def fetch_bls(
    series: str, series_id: str, name: str, unit: str, geo: str = "United States",
    start_year: int = 2005,
) -> tuple[dict, list]:
    """One BLS monthly series, fetched in ≤10-year windows. Monthly periods (M01-M12) are
    dated to the 1st; the M13 annual average is skipped; garbled values are skipped."""
    raw: dict[date, float] = {}
    this_year = date.today().year
    start = start_year
    while start <= this_year:
        chunk_end = min(start + 9, this_year)
        url = BLS_BASE.format(series=series) + f"?startyear={start}&endyear={chunk_end}"
        payload = json.loads(_get_retry(url, timeout=30).decode("utf-8", "replace"))
        result = (payload.get("Results") or {}).get("series") or []
        data = result[0].get("data", []) if result else []
        for row in data:
            period = (row.get("period") or "").strip()
            if not period.startswith("M") or period == "M13":  # M13 = annual average
                continue
            try:
                d = date(int(row["year"]), int(period[1:]), 1)
                raw[d] = _finite((row.get("value") or "").strip())
            except (ValueError, TypeError, KeyError):
                continue
        start = chunk_end + 1
    meta = {
        "series_id": series_id,
        "source": "bls",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": "monthly",
    }
    return meta, sorted(raw.items())


# --- BCB Olinda — Focus survey (market expectations) ------------------------------------
# OData service, no key. `$format=json` is mandatory; records live under `value`. We pull the
# SMOOTHED 12-month-ahead expectation (`Suavizada eq 'S'`, `baseCalculo eq 0`) for one
# indicator as a clean (survey-date, median) series — the expectations anchor a desk tracks
# against realised inflation. Paged by `$skip` until a short page.
FOCUS_INFL12M = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoInflacao12Meses"
)


def fetch_bcb_focus_12m(
    indicator: str, series_id: str, name: str, unit: str, geo: str = "Brazil"
) -> tuple[dict, list]:
    """Focus survey 12-month-ahead expectation (smoothed median) for ``indicator`` (e.g.
    'IPCA'), as a (survey-date, median) daily series. No key; paged via OData ``$skip``."""
    rows: list[dict] = []
    skip = 0
    page = 10000
    while True:
        params = {
            "$filter": (
                f"Suavizada eq 'S' and Indicador eq '{indicator}' and baseCalculo eq 0"
            ),
            "$select": "Data,Mediana",
            "$orderby": "Data",
            "$top": str(page),
            "$skip": str(skip),
            "$format": "json",
        }
        q = "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        payload = json.loads(_get_retry(FOCUS_INFL12M + q, timeout=45).decode("utf-8", "replace"))
        batch = payload.get("value") or []
        rows.extend(batch)
        if len(batch) < page:
            break
        skip += page
    obs: list[tuple[date, float]] = []
    for r in rows:
        d_raw = (r.get("Data") or "").strip()
        v = r.get("Mediana")
        if not d_raw or v is None:
            continue
        try:
            obs.append((date.fromisoformat(d_raw), _finite(v)))
        except (ValueError, TypeError):
            continue
    obs.sort()
    meta = {
        "series_id": series_id,
        "source": "bcb_focus",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": "daily",
    }
    return meta, obs


# --- IBGE SIDRA (Brazilian official statistics: IPCA, PNAD unemployment, PIB) ------------
# Open JSON REST, no key. The response is a FLAT array whose first element is a legend
# (header) and the rest are data rows; `V` is the value (string; non-numeric sentinels
# '-'/'..'/'...'/'X' mean missing), and the period lives in whichever dimension the legend
# names "Mês"/"Trimestre". Host `apisidra.ibge.gov.br` (the `api.sidra` host has a cert
# mismatch). An empty UA can 403 — the module UA in `_get` avoids it.
SIDRA_BASE = "https://apisidra.ibge.gov.br/values/t/{table}/n1/all/v/{variable}{cls}/p/all"

_SIDRA_MISSING = {"-", "..", "...", "X", "x", ""}


def _sidra_period(code: str, frequency: str) -> date:
    """SIDRA period codes: monthly/rolling-quarter = AAAAMM (dated to the month-1st);
    quarterly = AAAA0T where the last two digits are the quarter 01-04 (dated to the
    quarter-end month-1st). Anything else raises (skipped by the caller)."""
    year = int(code[:4])
    part = int(code[4:6])
    if frequency == "quarterly":
        if not 1 <= part <= 4:
            raise ValueError(f"bad SIDRA quarter {code!r}")
        return date(year, part * 3, 1)
    return date(year, part, 1)


def fetch_sidra(
    table: int,
    variable: int,
    series_id: str,
    name: str,
    unit: str,
    frequency: str = "monthly",
    classifications: list[tuple[int, int]] | None = None,
    geo: str = "Brazil",
    scale: float = 1.0,
) -> tuple[dict, list]:
    """One IBGE SIDRA series (national level). ``classifications`` pins extra dimensions as
    ``(classification_id, category_id)`` pairs (e.g. PIB's sector dimension). The period
    dimension is found from the legend by name, so a table whose period sits in a different
    ``D{n}`` column (PIB's is D4, not D3) parses correctly. ``scale`` is a labelled unit
    conversion (the UST:DEBT precedent)."""
    cls = "".join(f"/c{cid}/{cat}" for cid, cat in (classifications or []))
    url = SIDRA_BASE.format(table=table, variable=variable, cls=cls) + "?formato=json"
    data = json.loads(_get_retry(url).decode("utf-8", "replace"))
    meta = {
        "series_id": series_id,
        "source": "ibge",
        "name": name,
        "geo": geo,
        "unit": unit,
        "frequency": frequency,
    }
    if not isinstance(data, list) or len(data) < 2:
        return meta, []
    legend = data[0]
    period_key = next(
        (
            k
            for k, v in legend.items()
            if k.endswith("C") and isinstance(v, str)
            and ("Mês" in v or "Trimestre" in v or "Ano" in v)
        ),
        None,
    )
    if period_key is None:
        raise ValueError(f"sidra t{table}: no period dimension in legend")
    obs: list[tuple[date, float]] = []
    for row in data[1:]:
        v_raw = (row.get("V") or "").strip()
        p_raw = (row.get(period_key) or "").strip()
        if v_raw in _SIDRA_MISSING or not p_raw:
            continue
        try:
            obs.append((_sidra_period(p_raw, frequency), _finite(v_raw) * scale))
        except (ValueError, TypeError):
            continue
    obs.sort()
    return meta, obs


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
