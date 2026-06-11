"""Fetchers for alt-data sources (no API key, stdlib only).

Each fetcher is pure I/O — callers persist. Network failures raise; partial/garbled
responses yield skipped rows, never fabricated values. Observation values are floats and
non-finite values are refused at the parse boundary (``_finite``): Postgres would store a
NaN, but the API's JSON encoder (``allow_nan=False``) cannot serialize one — a single bad
cell would 500 every altdata endpoint.

Sources (v1):
- Wikimedia per-article daily pageviews (dense daily series).
- SEC EDGAR filing activity: daily counts of selected form types from a company's
  submissions feed (sparse series — a date with no matching filings is a TRUE ZERO,
  derivable, never stored).

Both SEC hosts (www.sec.gov for the ticker map, data.sec.gov for submissions) refuse
requests without a User-Agent; SEC asks that it carry contact info.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date

_UA = {"User-Agent": "qrp-altdata/1.0 (personal research; abresslau@gmail.com)"}
_TIMEOUT = 20.0

_PV_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "en.wikipedia/all-access/all-agents/{article}/daily/{start}/{end}"
)
_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_RECENT_CAP = 1000  # documented size limit of the submissions `filings.recent` block


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 (trusted hosts)
        return r.read()


def _get_json(url: str) -> object:
    return json.loads(_get(url).decode("utf-8", "replace"))


def _finite(raw: object) -> float:
    """``float()`` that REFUSES NaN/Infinity (raises ValueError like any garbled value)."""
    v = float(raw)  # type: ignore[arg-type]
    if not math.isfinite(v):
        raise ValueError(f"non-finite value {raw!r}")
    return v


def fetch_pageviews(article: str, start: date, end: date) -> list[tuple[date, float]]:
    """Daily en.wikipedia pageviews for one article (Wikimedia REST API).

    The article title is percent-encoded at this boundary (an unencoded ``%`` or ``?``
    would silently fetch a DIFFERENT article / truncate the path). A payload without an
    ``items`` key is a shape break and raises (attributable error) — only a present-but-
    empty list is no-data. Garbled rows (missing fields, non-date timestamps, non-scalar
    or non-finite values) are skipped, never invented. Returns ``[(obs_date, views), ...]``
    in the API's (ascending) order.
    """
    url = _PV_URL.format(
        article=urllib.parse.quote(article, safe=""),
        start=start.strftime("%Y%m%d00"),
        end=end.strftime("%Y%m%d00"),
    )
    payload = _get_json(url)
    if not isinstance(payload, dict) or "items" not in payload:
        raise ValueError("pageviews payload missing items")
    out: list[tuple[date, float]] = []
    for item in payload["items"]:
        ts = item.get("timestamp")  # 'YYYYMMDD00'
        views = item.get("views")
        if not ts or views is None:
            continue
        try:
            d = date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
            v = _finite(views)
        except (ValueError, TypeError):
            continue  # garbled row: skip
        out.append((d, v))
    return out


def fetch_company_ciks(tickers: set[str]) -> dict[str, str]:
    """Ticker -> zero-padded 10-digit CIK from SEC's company_tickers.json.

    The payload is a dict keyed by stringified rank — ``{"0": {"cik_str": 1045810,
    "ticker": "NVDA", ...}, ...}`` — NOT a list. Only the requested tickers are returned;
    a ticker absent from the file is simply absent from the result (the caller attributes
    the skip — one garbled row must not kill every other company's series). First
    occurrence wins if the file ever repeats a ticker.
    """
    payload = _get_json(_CIK_URL)
    if not isinstance(payload, dict):
        raise ValueError("company_tickers.json: expected a dict payload")
    want = {t.upper() for t in tickers}
    out: dict[str, str] = {}
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).upper()
        if ticker not in want:
            continue
        try:
            cik = f"{int(row['cik_str']):010d}"
        except (KeyError, ValueError, TypeError):
            continue  # garbled row: skip (the ticker then reads as absent, attributed)
        out.setdefault(ticker, cik)
    return out


def fetch_sec_filing_counts(
    cik: str, metrics: dict[str, frozenset[str]], start: date, end: date
) -> dict[str, list[tuple[date, float]]]:
    """Daily EDGAR filing counts per metric for one company, within ``[start, end]``.

    ``metrics`` maps a metric name to the set of form types it counts (e.g.
    ``{"filings_form4": frozenset({"4"})}``). One submissions fetch serves all metrics.

    Honesty notes:
    - Reads only the ``filings.recent`` block — a hard window of (at most) the company's
      last 1000 filings, NOT full history (AAPL's reaches back to ~2015; older filings
      live in archive files this fetcher does not read). When the block is AT the cap,
      days at or before its earliest filing are dropped: the cap may have cut that day's
      filings mid-day, and an undercount upserted over a previously-correct row is wrong
      data — a deep backfill needs the archive files, not a quiet partial count.
    - Form matching is EXACT: amendments (``4/A``, ``8-K/A``) are deliberately excluded.
    - Dates with no matching filings inside the block's coverage are true zeros and are
      not emitted (sparse series).
    - A payload without a ``filings.recent`` block is a shape break and raises; a garbled
      filingDate is skipped; mismatched form/date array lengths raise.
    """
    payload = _get_json(_SUBMISSIONS_URL.format(cik=cik))
    if not isinstance(payload, dict) or not isinstance(payload.get("filings"), dict) \
            or not isinstance(payload["filings"].get("recent"), dict):
        raise ValueError("submissions payload missing filings.recent")
    recent = payload["filings"]["recent"]
    forms: list[str] = recent.get("form", [])
    dates: list[str] = recent.get("filingDate", [])
    parsed: list[tuple[date, str]] = []
    for form, fd in zip(forms, dates, strict=True):
        try:
            parts = str(fd).split("-")
            if len(parts) != 3:
                raise ValueError(fd)
            day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            continue  # garbled date: skip, never invent
        parsed.append((day, form))
    # Truncation guard: at the cap, the earliest day's count may be partial — exclude it.
    floor: date | None = None
    if len(forms) >= _RECENT_CAP and parsed:
        floor = min(day for day, _ in parsed)
    counts: dict[str, Counter[date]] = {m: Counter() for m in metrics}
    for day, form in parsed:
        if not start <= day <= end:
            continue
        if floor is not None and day <= floor:
            continue
        for metric, form_set in metrics.items():
            if form in form_set:
                counts[metric][day] += 1
    return {
        metric: sorted((day, float(n)) for day, n in by_day.items())
        for metric, by_day in counts.items()
    }
