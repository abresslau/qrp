"""Live/delayed quote source for the sym serving module (Story QH.2).

The FIRST `/api/sym` path that fetches EXTERNALLY at request time — every other sym read is a
DB read. Best-effort and **never persisted**: live quotes are a second data class (unvalidated,
stale-on-arrival) deliberately kept off the immutable EOD store. Source: the Yahoo v8 chart
endpoint (no auth; re-probed reachable 2026-06-15). The live RETURN is computed from the
payload's own `previousClose`, so no sym price read (and no read-surface change) is needed.

Pure + injectable: `_http_get` is monkeypatched in tests; `now_epoch` is passed in. No DB, no
new dependency (stdlib `urllib`).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass

# MIC -> Yahoo suffix. Replicated from packages/sym/.../sources/yfinance_adapter.py
# (`YAHOO_SUFFIX`) — the serving gateway must NOT import the sym package (topology
# no-sym-imports gate), so the small map is duplicated and kept in sync with that source
# of truth. Yahoo uses '-' for share classes (BRK.A -> BRK-A); US listings have no suffix.
YAHOO_SUFFIX = {
    "XNYS": "", "XNAS": "", "XASE": "", "ARCX": "",
    "XLON": ".L", "XPAR": ".PA", "XETR": ".DE", "XFRA": ".F", "XSWX": ".SW",
    "XTKS": ".T", "XHKG": ".HK", "XKRX": ".KS", "XTAI": ".TW", "XASX": ".AX",
    "XMAD": ".MC", "XAMS": ".AS", "XBRU": ".BR", "XMIL": ".MI", "XSTO": ".ST",
    "XCSE": ".CO", "XHEL": ".HE", "XOSL": ".OL", "XLIS": ".LS", "XWAR": ".WA",
    "XTSE": ".TO", "XNZE": ".NZ", "XJSE": ".JO", "XSES": ".SI", "XBOM": ".BO",
    "XNSE": ".NS", "XSHG": ".SS", "XSHE": ".SZ", "XMEX": ".MX", "BVMF": ".SA",
    "XTAE": ".TA",
}

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
_LIVE_THRESHOLD_S = 120  # a quote no older than this reads as 'live', else 'delayed'
_TIMEOUT_S = 8.0
_BATCH_WORKERS = 24  # bounded concurrency for universe-scale fan-out (Story QH.9); headroom for ~700
_BATCH_BUDGET_S = 20.0  # overall wall-clock budget; symbols not done by then read as unavailable


class QuoteSourceUnreachable(Exception):
    """The quote provider could not be reached at all (DNS/timeout/connection)."""


@dataclass(frozen=True)
class RawQuote:
    price: float
    prev_close: float | None
    currency: str | None
    quote_epoch: int | None


def yahoo_symbol_for(ticker: str | None, mic: str | None) -> str | None:
    """figi's (ticker, MIC) -> Yahoo symbol, or None when the MIC has no Yahoo mapping."""
    if not ticker:
        return None
    suffix = YAHOO_SUFFIX.get(mic.strip() if isinstance(mic, str) else mic)
    if suffix is None:
        return None
    return f"{ticker.replace('.', '-')}{suffix}"


def _http_get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https host)
        return r.read().decode("utf-8", "replace")


def fetch_raw_quote(yahoo_symbol: str, *, timeout: float = _TIMEOUT_S) -> RawQuote | None:
    """One snapshot from the chart endpoint.

    Returns None when the source is reachable but has no usable data for this symbol (unknown
    ticker, empty meta, missing price). Raises ``QuoteSourceUnreachable`` only on a NETWORK
    failure (DNS/timeout/connection) — a per-symbol HTTP 4xx/5xx is treated as no-data (None),
    not a whole-source outage.
    """
    url = _CHART_URL.format(sym=yahoo_symbol)
    try:
        body = _http_get(url, timeout)
    except urllib.error.HTTPError:
        return None  # this symbol 4xx/5xx'd — unavailable, not a source outage
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise QuoteSourceUnreachable(str(exc)) from exc
    try:
        meta = json.loads(body)["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        prev = meta.get("previousClose")
        if prev is None:
            prev = meta.get("chartPreviousClose")
        rmt = meta.get("regularMarketTime")
        return RawQuote(
            price=float(price),
            prev_close=float(prev) if prev is not None else None,
            currency=meta.get("currency"),
            quote_epoch=int(rmt) if rmt else None,
        )
    except (ValueError, KeyError, IndexError, TypeError):
        # Malformed/unparseable payload (incl. a non-numeric price/time) is a per-symbol
        # miss -> None (unavailable), never an unhandled error that would surface as a 500.
        return None


def classify_freshness(
    quote_epoch: int | None, now_epoch: float, *, threshold: int = _LIVE_THRESHOLD_S
) -> tuple[str, int | None]:
    """(freshness, age_seconds) — 'live' if the quote is fresh, else 'delayed'."""
    if quote_epoch is None:
        return ("delayed", None)
    age = max(0, int(now_epoch - quote_epoch))
    return ("live" if age <= threshold else "delayed", age)


def live_return(price: float | None, prev_close: float | None) -> float | None:
    """Live price return vs the prior close — the EOD engine's input, computed live.

    None when either endpoint is missing or non-positive (same NULL rule as the EOD path).
    """
    if price is None or price <= 0 or prev_close is None or prev_close <= 0:
        return None
    return price / prev_close - 1.0


def now_epoch() -> float:
    return time.time()


def fetch_quotes_batch(
    yahoo_symbols: list[str],
    *,
    timeout: float = _TIMEOUT_S,
    max_workers: int = _BATCH_WORKERS,
    budget: float = _BATCH_BUDGET_S,
) -> dict[str, RawQuote | None]:
    """Fetch many symbols concurrently with bounded workers + an overall wall-clock budget
    (Story QH.9 — the fan-out QH.2 deferred). Returns ``{symbol: RawQuote|None}`` (None = a
    per-symbol miss OR not finished within the budget). Mirrors the single-fetch two-tier
    contract: raises ``QuoteSourceUnreachable`` ONLY when every COMPLETED symbol network-errored
    (a wholly-unreachable provider); a mix is honest partial coverage. Input is de-duplicated.
    """
    syms = list(dict.fromkeys(s for s in yahoo_symbols if s))
    if not syms:
        return {}
    results: dict[str, RawQuote | None] = {s: None for s in syms}
    net_errors = 0
    # NOT a `with` block: the context-manager exit calls shutdown(wait=True), which would block on
    # every in-flight request and make the wall-clock `budget` a no-op. We wait() up to the budget,
    # then shut down WITHOUT waiting (cancelling not-yet-started tasks) so the request returns
    # promptly; symbols not finished in the budget stay None (= unavailable, honest).
    ex = ThreadPoolExecutor(max_workers=min(max_workers, len(syms)))
    try:
        fut_map = {ex.submit(fetch_raw_quote, s, timeout=timeout): s for s in syms}
        done, _pending = wait(fut_map, timeout=budget)
        for fut in done:
            try:
                results[fut_map[fut]] = fut.result()
            except QuoteSourceUnreachable:
                net_errors += 1  # result stays None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    # Whole-source-unreachable (→503) ONLY when EVERY symbol network-errored — never from a biased
    # subset that merely happened to complete first under budget pressure.
    if net_errors == len(syms):
        raise QuoteSourceUnreachable(
            f"quote provider unreachable ({net_errors}/{len(syms)} symbols network-errored)"
        )
    return results
