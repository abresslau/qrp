"""Yahoo ``assetProfile`` → GICS-sector classification (multi-source, AC #3).

A SECONDARY fill source for names the financedatabase + b3 + sec_sic passes leave
unclassified — overwhelmingly NON-US (LSE/European listings) that the US-only SEC
SIC source structurally cannot reach. Yahoo's v10 ``quoteSummary`` ``assetProfile``
module carries a sector + industry for most listed names worldwide, but it is
**crumb-gated** (HTTP 401 without a crumb+cookie — the same gating as the v7 quote
endpoint; the v8 *chart* endpoint we use for live quotes carries no sector). So a
session is established once per client, then reused:

1. seed cookies from ``fc.yahoo.com`` (404s, but sets the session cookies);
2. ``GET /v1/test/getcrumb`` with those cookies → an opaque crumb;
3. pass the crumb on every ``quoteSummary`` call.

Yahoo uses its OWN sector taxonomy (11 sectors, GICS-adjacent but differently
named — ``Technology``, ``Financial Services``, ``Consumer Cyclical`` …), so a
documented Yahoo→GICS-sector crosswalk normalizes it. Sector-only
(``source='yahoo_profile'``); Yahoo's *industry* strings are not GICS industries,
so the industry levels stay NULL (honest, matching b3/sec_sic).

Like the other fill sources it is fed only the still-unclassified identities, so
it is fill-only by construction and never overrides a higher-precedence source.
Stdlib ``urllib`` only — no new dependency; reuses sym's own ``YAHOO_SUFFIX``
(the MIC→Yahoo-symbol map the yfinance price adapter already maintains).
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Protocol

from sym.classification.gics import GicsClassification, SecurityIdentity
from sym.sources.yfinance_adapter import YAHOO_SUFFIX

# Yahoo gates these endpoints by browser-likeness; a desktop UA + the crumb flow
# is what lifts the 401 (probed 2026-06-17: AAPL→Technology, SHEL.L→Energy).
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
_COOKIE_URL = "https://fc.yahoo.com/"
# query1/query2 are interchangeable mirrors; try both for resilience.
_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
_CRUMB_PATH = "/v1/test/getcrumb"
_PROFILE_PATH = "/v10/finance/quoteSummary/{sym}?modules=assetProfile&crumb={crumb}"
_HTTP_TIMEOUT = 20


class YahooProfileError(RuntimeError):
    """The Yahoo session/crumb could not be established, or a profile fetch failed.

    ``is_auth`` flags a 401 (crumb expiry) so the caller can re-establish the
    session and retry — carried explicitly rather than via ``__cause__`` so it
    survives the host-fallback loop's exception reduction.
    """

    def __init__(self, message: str, *, is_auth: bool = False) -> None:
        super().__init__(message)
        self.is_auth = is_auth


def yahoo_symbol_for_identity(security: SecurityIdentity) -> str | None:
    """Build the Yahoo symbol for an identity, or None if its MIC is unmappable.

    Mirrors the yfinance price adapter: ``ticker`` with ``.`` → ``-`` (Yahoo's
    share-class convention, BRK.B → BRK-B) plus the MIC's Yahoo suffix (US → ``""``
    bare). A mic-less identity is trusted ticker-only (US-style bare symbol),
    matching the b3/sec_sic posture for test/legacy callers.
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
# Yahoo sector → GICS sector crosswalk (11 → 11)
# ---------------------------------------------------------------------------
# Keyed on the lower-cased Yahoo sector string. The 11 Yahoo sectors map 1:1 onto
# the 11 GICS sectors (only the names differ); kept identical to the financedatabase
# /b3/sec_sic GICS labels so the heatmap + validate group cleanly. An unrecognised
# sector returns None — recorded as unmapped, never guessed.
YAHOO_SECTOR_TO_GICS: dict[str, str] = {
    "technology": "Information Technology",
    "financial services": "Financials",
    "financial": "Financials",  # legacy label seen on some older payloads
    "healthcare": "Health Care",
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "industrials": "Industrials",
    "energy": "Energy",
    "basic materials": "Materials",
    "communication services": "Communication Services",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}


def yahoo_sector_to_gics(sector: str | None) -> str | None:
    """Map a Yahoo sector label to a GICS sector, or None if unrecognised."""
    if not sector:
        return None
    return YAHOO_SECTOR_TO_GICS.get(sector.strip().lower())


def _parse_profile_payload(payload: object) -> tuple[str | None, str | None]:
    """Pull ``(sector, industry)`` from a quoteSummary payload, tolerating every
    malformed/error shape Yahoo emits.

    Defensive at EVERY level — a ``{"quoteSummary": null}`` or ``{"finance":
    {"error": …}}`` envelope (returned under rate-limit/not-found conditions) must
    return ``(None, None)``, never raise: an ``AttributeError`` escaping here would
    bypass the source's per-symbol isolation and abort the whole pass.
    """
    if not isinstance(payload, dict):
        return (None, None)
    quote_summary = payload.get("quoteSummary")
    if not isinstance(quote_summary, dict):
        return (None, None)
    result = quote_summary.get("result")
    if not isinstance(result, list) or not result:
        return (None, None)
    first = result[0]
    profile = first.get("assetProfile") if isinstance(first, dict) else None
    if not isinstance(profile, dict):
        return (None, None)
    sector = profile.get("sector")
    industry = profile.get("industry")
    return (
        sector.strip() if isinstance(sector, str) and sector.strip() else None,
        industry.strip() if isinstance(industry, str) and industry.strip() else None,
    )


class YahooProfileClient(Protocol):
    """The single lookup the source needs (injectable for DB-free testing)."""

    def sector_for_symbol(self, symbol: str) -> tuple[str | None, str | None]:
        """Return ``(yahoo_sector, yahoo_industry)`` for a symbol; ``(None, None)`` if absent."""
        ...


class HttpYahooProfileClient:
    """Live :class:`YahooProfileClient` over Yahoo (stdlib ``urllib`` + the crumb flow).

    Establishes the cookie+crumb session lazily on first use and reuses it; a 401
    mid-run (crumb expiry) triggers exactly one re-establish + retry. Self-throttles
    to keep the per-symbol sequential fetch polite.
    """

    def __init__(self, min_interval: float = 0.3) -> None:
        self._min_interval = min_interval
        self._last_request = 0.0
        self._crumb: str | None = None
        self._opener: urllib.request.OpenerDirector | None = None

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _ensure_session(self) -> None:
        if self._crumb is not None and self._opener is not None:
            return
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        # Seed the session cookies. fc.yahoo.com 404s but sets them; tolerate that.
        try:
            opener.open(urllib.request.Request(_COOKIE_URL, headers=_UA), timeout=_HTTP_TIMEOUT)
        except urllib.error.HTTPError:
            pass  # 404 expected — the Set-Cookie still landed
        except OSError as exc:
            raise YahooProfileError(f"Yahoo cookie seed failed: {exc}") from exc
        crumb = ""
        last_exc: Exception | None = None
        for host in _HOSTS:
            try:
                req = urllib.request.Request(host + _CRUMB_PATH, headers=_UA)
                with opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
                    crumb = resp.read().decode("utf-8").strip()
                if crumb and "<" not in crumb:
                    break
            except OSError as exc:
                last_exc = exc
        if not crumb or "<" in crumb:
            raise YahooProfileError(f"could not obtain a Yahoo crumb: {last_exc}")
        self._crumb = crumb
        self._opener = opener

    def _fetch_profile(self, symbol: str) -> object:
        assert self._opener is not None and self._crumb is not None
        path = _PROFILE_PATH.format(
            sym=urllib.parse.quote(symbol, safe=""),
            crumb=urllib.parse.quote(self._crumb, safe=""),
        )
        last_exc: Exception | None = None
        saw_401 = False
        for host in _HOSTS:
            try:
                req = urllib.request.Request(host + path, headers=_UA)
                with self._opener.open(req, timeout=_HTTP_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_exc = exc
                # 401 = crumb expired; remember it even if a later host fails
                # differently, so the caller's retry decision isn't masked.
                saw_401 = saw_401 or exc.code == 401
            except (OSError, ValueError) as exc:
                last_exc = exc
        raise YahooProfileError(
            f"profile fetch failed for {symbol}: {last_exc}", is_auth=saw_401
        ) from last_exc

    def sector_for_symbol(self, symbol: str) -> tuple[str | None, str | None]:
        self._ensure_session()
        self._throttle()
        try:
            payload = self._fetch_profile(symbol)
        except YahooProfileError as exc:
            # A 401 means the crumb expired — re-establish once and retry. A second
            # failure propagates (no loop) and is recorded per-symbol by the caller.
            if not exc.is_auth:
                raise
            self._crumb = None
            self._opener = None
            self._ensure_session()
            self._throttle()
            payload = self._fetch_profile(symbol)
        return _parse_profile_payload(payload)


class YahooProfileGicsSource:
    """GICS *sector* classifications from Yahoo ``assetProfile``.

    Implements the :class:`sym.classification.gics.GicsSource` protocol. For each
    identity it builds the Yahoo symbol (ticker + MIC suffix), reads the profile
    sector, and maps it to GICS. Every classification is SECTOR-ONLY with
    ``source='yahoo_profile'`` (Yahoo industries aren't GICS industries → NULL).

    Attribution side-channels (reset per ``fetch``, reported by the caller, never
    guessed):

    * ``last_unmapped_sector`` (symbol -> raw Yahoo sector): a sector outside the
      crosswalk (surfaces a Yahoo taxonomy drift);
    * ``last_unmatched`` (symbols): Yahoo returned no profile / no sector;
    * ``last_unmapped_mic`` (tickers): the identity's MIC has no Yahoo suffix, so
      no symbol could be built;
    * ``last_errors`` (symbol -> message): a per-symbol fetch error — isolated so
      one bad name never aborts the rest of the pass.
    """

    def __init__(self, client: YahooProfileClient | None = None) -> None:
        self._client = client or HttpYahooProfileClient()
        self.last_unmapped_sector: dict[str, str] = {}
        self.last_unmatched: list[str] = []
        self.last_unmapped_mic: list[str] = []
        self.last_errors: dict[str, str] = {}

    def fetch(self, securities: Sequence[SecurityIdentity]) -> dict[str, GicsClassification]:
        self.last_unmapped_sector = {}
        self.last_unmatched = []
        self.last_unmapped_mic = []
        self.last_errors = {}

        found: dict[str, GicsClassification] = {}
        for security in securities:
            if not security.ticker:
                continue
            symbol = yahoo_symbol_for_identity(security)
            if symbol is None:
                self.last_unmapped_mic.append(security.ticker.upper())
                continue
            try:
                sector, _industry = self._client.sector_for_symbol(symbol)
            except YahooProfileError as exc:
                self.last_errors[symbol] = str(exc)
                continue
            if sector is None:
                self.last_unmatched.append(symbol)
                continue
            gics = yahoo_sector_to_gics(sector)
            if gics is None:
                self.last_unmapped_sector[symbol] = sector
                continue
            found[security.composite_figi] = GicsClassification(
                composite_figi=security.composite_figi,
                sector_name=gics,
                industry_group_name=None,
                industry_name=None,
                source="yahoo_profile",
            )
        return found
