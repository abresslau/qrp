"""FMP company-profile → GICS-sector classification (multi-source). KEYED / opt-in-by-key.

Financial Modeling Prep's ``/v3/profile/{symbol}`` endpoint returns a ``sector`` +
``industry`` (FMP's own ~11-sector vendor taxonomy — the same shape Yahoo uses) plus
``isFund``/``isEtf`` flags. It REQUIRES an API key (``FMP_API_KEY``, the same key the
FMP universe provider uses); without one the source raises and the fill pass degrades
honestly — no key means it simply contributes nothing, never a crash.

Precedence: FMP is a paid, structured fundamentals vendor, so it ranks ABOVE the free
``yahoo_profile`` + ``llm`` sources but BELOW the official/regulatory ones
(financedatabase / b3 / sec_sic) — see :data:`sym.classification.gics.SOURCE_PRECEDENCE`.
Sector-only (``source='fmp'``, industry levels NULL like the other fill sources). Unlike
the guess-prone sources, FMP's ``isFund``/``isEtf`` lets it explicitly DECLINE a fund
(a fund has no GICS sector) rather than mis-classify it.

Stdlib ``urllib`` only (uniform with sec_sic/yahoo_profile — the FMP universe provider
uses ``requests``, but the classification clients are a self-contained family). Shared
:class:`~sym.classification._http.RequestThrottle` + per-symbol error isolation.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Protocol

from equity.sources.yfinance_adapter import YAHOO_SUFFIX

from sym.classification._http import RequestThrottle
from sym.classification.gics import GicsClassification, SecurityIdentity

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
_PROFILE_PATH = "/profile/{symbol}?apikey={key}"
_HTTP_TIMEOUT = 20


class FmpProfileError(RuntimeError):
    """FMP was unreachable, unkeyed, or returned an unusable shape."""


def fmp_symbol_for_identity(security: SecurityIdentity) -> str | None:
    """Build the FMP symbol for an identity, or None if its MIC is unmappable.

    FMP largely follows the same exchange-suffix convention as Yahoo (US → bare
    ticker; ``.L`` LSE, ``.PA`` Paris, …), so it reuses sym's ``YAHOO_SUFFIX`` map.
    FMP's international symbol formats are unverified in-env (no key to probe), but
    US coverage — where FMP is strongest — is the bare ticker and is exact. A
    mic-less identity is trusted ticker-only (US-style), matching the sibling sources.
    """
    if not security.ticker:
        return None
    base = security.ticker.replace(".", "-")
    if security.mic is None:
        return base
    mic = security.mic.strip() if isinstance(security.mic, str) else security.mic
    suffix = YAHOO_SUFFIX.get(mic)
    if suffix is None:
        return None
    return f"{base}{suffix}"


# ---------------------------------------------------------------------------
# FMP sector → GICS sector crosswalk
# ---------------------------------------------------------------------------
# FMP uses the same ~11-sector vendor taxonomy as Yahoo, plus a few legacy labels
# seen on older profiles. Keyed on the lower-cased sector string; targets are the
# canonical GICS labels (identical to financedatabase/b3/sec_sic/yahoo) so the
# heatmap + validate group cleanly. Unrecognised → None (recorded, never guessed).
FMP_SECTOR_TO_GICS: dict[str, str] = {
    "technology": "Information Technology",
    "information technology": "Information Technology",
    "financial services": "Financials",
    "financial": "Financials",  # legacy FMP label
    "financials": "Financials",
    "healthcare": "Health Care",
    "health care": "Health Care",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "industrials": "Industrials",
    "industrial goods": "Industrials",  # legacy FMP label
    "energy": "Energy",
    "basic materials": "Materials",
    "materials": "Materials",
    "communication services": "Communication Services",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}


def fmp_sector_to_gics(sector: str | None) -> str | None:
    """Map an FMP sector label to a GICS sector, or None if unrecognised."""
    if not sector:
        return None
    return FMP_SECTOR_TO_GICS.get(sector.strip().lower())


def _parse_profile_payload(payload: object) -> tuple[str | None, str | None, bool]:
    """Pull ``(sector, industry, is_fund)`` from an FMP profile payload, tolerating
    every malformed shape — a parse error must never escape per-symbol isolation.

    FMP returns a single-element list; an unknown symbol returns ``[]``.
    """
    if not isinstance(payload, list) or not payload:
        return (None, None, False)
    first = payload[0]
    if not isinstance(first, dict):
        return (None, None, False)
    sector = first.get("sector")
    industry = first.get("industry")
    is_fund = bool(first.get("isFund") or first.get("isEtf"))
    return (
        sector.strip() if isinstance(sector, str) and sector.strip() else None,
        industry.strip() if isinstance(industry, str) and industry.strip() else None,
        is_fund,
    )


class FmpProfileClient(Protocol):
    """The single lookup the source needs (injectable for DB-free testing)."""

    def profile_for_symbol(self, symbol: str) -> tuple[str | None, str | None, bool]:
        """Return ``(sector, industry, is_fund)`` for a symbol; absent → ``(None, None, False)``."""
        ...


class HttpFmpProfileClient:
    """Live :class:`FmpProfileClient` over FMP v3 (stdlib ``urllib``, keyed).

    The key defaults to ``$FMP_API_KEY`` (the same env var the FMP universe provider
    reads). An absent key raises :class:`FmpProfileError` on first use — the caller's
    per-pass catch turns that into an honest "FMP not configured", not a crash.
    """

    def __init__(self, api_key: str | None = None, min_interval: float = 0.25) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("FMP_API_KEY")
        self._throttle = RequestThrottle(min_interval)

    def profile_for_symbol(self, symbol: str) -> tuple[str | None, str | None, bool]:
        if not self._api_key:
            raise FmpProfileError("FMP requires an API key (set FMP_API_KEY)")
        self._throttle.wait()
        url = FMP_BASE_URL + _PROFILE_PATH.format(
            symbol=urllib.parse.quote(symbol, safe=""),
            key=urllib.parse.quote(self._api_key, safe=""),
        )
        req = urllib.request.Request(url, headers={"User-Agent": "qrp-sym/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as exc:  # URLError/HTTPError/timeout/bad-json
            raise FmpProfileError(f"FMP profile fetch failed for {symbol}: {exc}") from exc
        return _parse_profile_payload(payload)


class FmpProfileGicsSource:
    """GICS *sector* classifications from FMP company profiles.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. Sector-only
    (``source='fmp'``). Per-symbol error isolation — one bad symbol never aborts the
    pass. Side-channels (reset per ``fetch``, reported by the caller, never guessed):

    * ``last_unmapped_sector`` (symbol -> raw FMP sector): outside the crosswalk;
    * ``last_unmatched`` (symbols): FMP returned no profile / no sector;
    * ``last_skipped_fund`` (symbols): FMP flagged it ``isFund``/``isEtf`` — a fund
      has no GICS sector, so it is deliberately left unclassified;
    * ``last_unmapped_mic`` (tickers): the MIC has no symbol suffix;
    * ``last_errors`` (symbol -> message): a per-symbol fetch error (incl. no-key).
    """

    def __init__(self, client: FmpProfileClient | None = None) -> None:
        self._client = client or HttpFmpProfileClient()
        self.last_unmapped_sector: dict[str, str] = {}
        self.last_unmatched: list[str] = []
        self.last_skipped_fund: list[str] = []
        self.last_unmapped_mic: list[str] = []
        self.last_errors: dict[str, str] = {}

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmapped_sector = {}
        self.last_unmatched = []
        self.last_skipped_fund = []
        self.last_unmapped_mic = []
        self.last_errors = {}

        found: dict[str, GicsClassification] = {}
        for security in securities:
            if not security.ticker:
                continue
            symbol = fmp_symbol_for_identity(security)
            if symbol is None:
                self.last_unmapped_mic.append(security.ticker.upper())
                continue
            try:
                sector, _industry, is_fund = self._client.profile_for_symbol(symbol)
            except FmpProfileError as exc:
                self.last_errors[symbol] = str(exc)
                continue
            if is_fund:
                # FMP says it's a fund/ETF — no GICS sector exists; never invent one.
                self.last_skipped_fund.append(symbol)
                continue
            if sector is None:
                self.last_unmatched.append(symbol)
                continue
            gics = fmp_sector_to_gics(sector)
            if gics is None:
                self.last_unmapped_sector[symbol] = sector
                continue
            found[security.composite_figi] = GicsClassification(
                composite_figi=security.composite_figi,
                sector_name=gics,
                industry_group_name=None,
                industry_name=None,
                source="fmp",
            )
        return found
