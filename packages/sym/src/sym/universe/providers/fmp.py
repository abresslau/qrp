"""Open-finance-API index source (FMP) — Story U2.1.

The preferred **US** archetype: FMP exposes current constituents *and* a dated
historical add/remove feed for the US flagships (S&P 500, Nasdaq-100, Dow Jones),
so membership comes from a structured dated source rather than scraping (NFR4).

The HTTP call is isolated behind :class:`FmpClient` so the change-derivation logic
is testable without the network and a real outage raises :class:`IndexSourceError`
(loud → the orchestrator falls back) rather than a silent empty result.

FMP free-tier note: an API key is required (``FMP_API_KEY``); the free tier is
US-only and may gate the historical-constituent endpoint (a gated history is
swallowed — current-snapshot-only — and the membership log carries no signal of
the degradation). The only payload sanity checks are non-list rejection and the
empty-current-snapshot error; there is NO expected-vs-returned count verification,
so a throttled partial list would pass silently.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

import requests

from sym.universe.membership_diff import ticker_token
from sym.universe.providers.index_source import (
    ARCHETYPE_FMP,
    IndexSourceError,
    register_index_source,
)
from sym.universe.registry import EXACT, JOIN, LEAVE, POLL_BOUNDED, MembershipChange

# FMP index key -> its constituent-endpoint slug. Only these three are on the
# free tier; S&P 400/600 and European indexes use Wikipedia/ETF archetypes.
_FMP_SLUG = {
    "sp500": "sp500",
    "nasdaq100": "nasdaq",
    "dowjones": "dowjones",
}

# FMP exchange label -> operating MIC (US listings only on the free tier).
_EXCHANGE_MIC = {
    "NASDAQ": "XNAS",
    "NEW YORK STOCK EXCHANGE": "XNYS",
    "NYSE": "XNYS",
    "NYSEARCA": "ARCX",
    "AMEX": "XASE",
    "NYSE AMERICAN": "XASE",
    "BATS": "BATS",
}
_DEFAULT_US_MIC = "XNYS"

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


def _mic_for(exchange: str | None) -> str:
    if not exchange:
        return _DEFAULT_US_MIC
    return _EXCHANGE_MIC.get(exchange.strip().upper(), _DEFAULT_US_MIC)


def _parse_fmp_date(value: str) -> date | None:
    """Parse an FMP date — ISO ``2020-01-02`` or long ``January 2, 2020``."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


class FmpClient(Protocol):
    """Reads FMP constituent endpoints, one list of raw row dicts per call."""

    def current_constituents(self, slug: str) -> list[dict]: ...

    def historical_constituents(self, slug: str) -> list[dict]: ...


class HttpFmpClient:
    """Live FMP v3 constituent client (raises :class:`IndexSourceError` on failure)."""

    def __init__(
        self,
        api_key: str | None,
        *,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries

    def _get(self, path: str) -> list[dict]:
        if not self._api_key:
            raise IndexSourceError("FMP requires an API key (set FMP_API_KEY)")
        url = f"{FMP_BASE_URL}/{path}"
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    url, params={"apikey": self._api_key}, timeout=self._timeout
                )
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code == 429:
                time.sleep(1.0 * (attempt + 1))
                last = IndexSourceError("FMP rate limited (429)")
                continue
            if resp.status_code != 200:
                raise IndexSourceError(f"FMP returned HTTP {resp.status_code} for {path}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise IndexSourceError(f"FMP returned non-JSON for {path}") from exc
            if not isinstance(data, list):
                raise IndexSourceError(f"FMP returned a non-list payload for {path}")
            return data
        raise IndexSourceError(f"FMP unreachable after {self._max_retries} attempts: {last}")

    def current_constituents(self, slug: str) -> list[dict]:
        return self._get(f"{slug}_constituent")

    def historical_constituents(self, slug: str) -> list[dict]:
        return self._get(f"historical/{slug}_constituent")


class FmpIndexSource:
    """Derives membership events for a US flagship index from FMP."""

    archetype = ARCHETYPE_FMP

    def __init__(self, client: FmpClient) -> None:
        self._client = client

    def _changes_from_current(self, rows: Sequence[dict], at: date) -> list[MembershipChange]:
        changes: list[MembershipChange] = []
        for row in rows:
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                continue
            mic = _mic_for(row.get("exchange") or row.get("exchangeShortName"))
            # A current snapshot bounds the join date only to the observation day.
            changes.append(
                MembershipChange(ticker_token(symbol, mic), JOIN, at, ARCHETYPE_FMP, POLL_BOUNDED)
            )
        return changes

    def _changes_from_history(
        self, rows: Sequence[dict], start: date, end: date
    ) -> list[MembershipChange]:
        changes: list[MembershipChange] = []
        for row in rows:
            on = _parse_fmp_date(row.get("date", ""))
            if on is None or on < start or on > end:
                continue
            added = (row.get("symbol") or "").strip()
            removed = (row.get("removedTicker") or "").strip()
            mic = _mic_for(row.get("exchange") or row.get("exchangeShortName"))
            if added:
                changes.append(
                    MembershipChange(ticker_token(added, mic), JOIN, on, ARCHETYPE_FMP, EXACT)
                )
            if removed:
                changes.append(
                    MembershipChange(ticker_token(removed, mic), LEAVE, on, ARCHETYPE_FMP, EXACT)
                )
        return changes

    def fetch(self, index_key: str, start: date, end: date) -> list[MembershipChange]:
        slug = _FMP_SLUG.get(index_key)
        if slug is None:
            raise IndexSourceError(f"FMP has no constituent feed for index {index_key!r}")
        current = self._client.current_constituents(slug)
        if not current:
            # An empty current snapshot is an error, never "the index is empty".
            raise IndexSourceError(f"FMP returned no current constituents for {index_key!r}")
        changes = self._changes_from_current(current, end)
        try:
            history = self._client.historical_constituents(slug)
        except IndexSourceError:
            history = []  # historical endpoint may be gated on the free tier
        changes.extend(self._changes_from_history(history, start, end))
        return changes


def _build_from_config(client: FmpClient | None = None, api_key: str | None = None, **_: object):
    return FmpIndexSource(client or HttpFmpClient(api_key))


register_index_source(ARCHETYPE_FMP, _build_from_config)
