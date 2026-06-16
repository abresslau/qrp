"""Live quote fetch for analytics' live-PnL (Story QH.2).

A deliberate small twin of ``qrp_api.modules.sym.quotes`` — this is a standalone package and
must not import the gateway, so the ~fetch/parse/symbol logic is duplicated (the project's
duplicate-across-package-until-justified posture, as with the per-package ``db.py`` helpers).
If a third consumer of live quotes appears, extract a shared package. Best-effort, NEVER
persisted; the live return is computed from the payload's own previousClose. stdlib only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# MIC -> Yahoo suffix — kept in sync with packages/sym/.../sources/yfinance_adapter.py.
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
_LIVE_THRESHOLD_S = 120
_TIMEOUT_S = 8.0


class QuoteSourceUnreachable(Exception):
    """The quote provider could not be reached at all (DNS/timeout/connection)."""


@dataclass(frozen=True)
class RawQuote:
    price: float
    prev_close: float | None
    currency: str | None
    quote_epoch: int | None


def yahoo_symbol_for(ticker: str | None, mic: str | None) -> str | None:
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
    """One snapshot. None = reachable but no usable data (per-symbol miss). Raises
    ``QuoteSourceUnreachable`` only on a network failure."""
    url = _CHART_URL.format(sym=yahoo_symbol)
    try:
        body = _http_get(url, timeout)
    except urllib.error.HTTPError:
        return None
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
    if quote_epoch is None:
        return ("delayed", None)
    age = max(0, int(now_epoch - quote_epoch))
    return ("live" if age <= threshold else "delayed", age)


def live_return(price: float | None, prev_close: float | None) -> float | None:
    if price is None or price <= 0 or prev_close is None or prev_close <= 0:
        return None
    return price / prev_close - 1.0


def now_epoch() -> float:
    return time.time()
