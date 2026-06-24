"""ETF-holdings index source — Story U2.2.

The preferred **Europe** archetype (and the least-brittle source for big/gated US
indices): an index ETF's issuer publishes a daily holdings file, and the equity
constituents of that file proxy the index membership. It is self-archivable and
needs no structured constituents API (which Europe lacks for free).

Membership is derived from the holdings on the identifier **set** only — a weight
change is not a membership change. Non-equity lines (cash, futures, FX hedges) are
dropped. Events are tagged ``poll_bounded`` (a holdings snapshot only bounds the
date to the polling interval) and carry *proxy* provenance (an ETF tracks, but is
not, the index). An empty/garbled parse is a loud :class:`IndexSourceError`
(never applied as "all members left").
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import requests

from universe.membership_diff import isin_token, ticker_token
from universe.providers.index_source import (
    ARCHETYPE_ETF,
    IndexSourceError,
    register_index_source,
)
from universe.registry import JOIN, POLL_BOUNDED, MembershipChange

# Asset-class / sector labels that are NOT equity constituents.
_NON_EQUITY = {
    "CASH",
    "CASH COLLATERAL",
    "CASH AND/OR DERIVATIVES",
    "MONEY MARKET",
    "FUTURES",
    "FX",
    "FOREIGN EXCHANGE",
    "FORWARD",
    "FORWARDS",
    "SWAP",
    "BOND",
    "FIXED INCOME",
}


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _is_equity(row: dict) -> bool:
    """True if a holdings row is an equity constituent (not cash/derivative)."""
    asset_class = _norm(row.get("asset_class")).upper()
    if asset_class:
        return asset_class == "EQUITY"
    # No asset-class column: fall back to sector + a present ISIN/ticker.
    sector = _norm(row.get("sector")).upper()
    if sector in _NON_EQUITY:
        return False
    return bool(_norm(row.get("isin")) or _norm(row.get("ticker")))


def _row_token(row: dict, default_mic: str | None) -> str | None:
    """The resolver token for an equity row — ISIN preferred, else ticker+MIC."""
    isin = _norm(row.get("isin"))
    if isin:
        return isin_token(isin)
    ticker = _norm(row.get("ticker"))
    mic = _norm(row.get("mic")) or default_mic
    if ticker and mic:
        return ticker_token(ticker, mic)
    return None


def parse_equity_tokens(rows: Iterable[dict], default_mic: str | None = None) -> set[str]:
    """Filter holdings rows to equity constituents and tokenize them (pure)."""
    tokens: set[str] = set()
    for row in rows:
        if not _is_equity(row):
            continue
        token = _row_token(row, default_mic)
        if token:
            tokens.add(token)
    return tokens


# A holdings CSV column header (lower-cased) -> our canonical row key.
_HEADER_ALIASES = {
    "asset class": "asset_class",
    "ticker": "ticker",
    "issuer ticker": "ticker",
    "isin": "isin",
    "name": "name",
    "sector": "sector",
    "exchange": "exchange",
}


def parse_holdings_csv(text: str) -> list[dict]:
    """Parse an issuer holdings CSV into canonical row dicts.

    Issuer files (iShares/Amundi/Xtrackers) prepend metadata lines before the
    header; we skip to the first line that looks like a header (contains a known
    column) and parse from there.
    """
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if "isin" in low or "ticker" in low:
            start = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    rows: list[dict] = []
    for raw in reader:
        row: dict[str, str] = {}
        for header, value in raw.items():
            if header is None:
                continue
            key = _HEADER_ALIASES.get(header.strip().lower())
            if key:
                row[key] = value
        if row:
            rows.append(row)
    return rows


class EtfHoldingsClient(Protocol):
    """Returns the raw holdings rows for an ETF key (one dict per line)."""

    def holdings(self, etf_key: str) -> list[dict]: ...


class HttpEtfHoldingsClient:
    """Fetches + parses an issuer holdings CSV from a per-ETF URL."""

    def __init__(
        self,
        urls: dict[str, str],
        *,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        self._urls = urls
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries

    def holdings(self, etf_key: str) -> list[dict]:
        url = self._urls.get(etf_key)
        if not url:
            raise IndexSourceError(f"no holdings URL configured for ETF {etf_key!r}")
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(url, timeout=self._timeout)
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise IndexSourceError(f"ETF holdings returned HTTP {resp.status_code}")
            return parse_holdings_csv(resp.text)
        raise IndexSourceError(f"ETF holdings unreachable after {self._max_retries}: {last}")


class EtfHoldingsIndexSource:
    """Derives index membership from an ETF's equity holdings (proxy)."""

    archetype = ARCHETYPE_ETF
    PROXY = "proxy"
    # Full current-membership token set from the last fetch (U3.5): the holdings file
    # is a complete snapshot — leaver-diff-safe.
    last_snapshot_tokens: set[str] | None = None

    def __init__(
        self,
        client: EtfHoldingsClient,
        etf_for_index: dict[str, str],
        mic_for_index: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._etf_for_index = etf_for_index
        self._mic_for_index = mic_for_index or {}

    def fetch(self, index_key: str, start: date, end: date) -> list[MembershipChange]:
        # Reset on entry: a raising fetch must not leak the previous call's snapshot.
        self.last_snapshot_tokens = None
        etf_key = self._etf_for_index.get(index_key)
        if etf_key is None:
            raise IndexSourceError(f"no ETF proxy configured for index {index_key!r}")
        rows = self._client.holdings(etf_key)
        tokens = parse_equity_tokens(rows, self._mic_for_index.get(index_key))
        if not tokens:
            # Empty/garbled parse: an error, never "every member left".
            raise IndexSourceError(
                f"ETF holdings for {index_key!r} parsed to zero equity constituents"
            )
        source = f"{ARCHETYPE_ETF}:{etf_key}"
        self.last_snapshot_tokens = set(tokens)
        return [MembershipChange(tok, JOIN, end, source, POLL_BOUNDED) for tok in sorted(tokens)]


def _build_from_config(
    client: EtfHoldingsClient | None = None,
    holdings_urls: dict[str, str] | None = None,
    etf_for_index: dict[str, str] | None = None,
    mic_for_index: dict[str, str] | None = None,
    **_: object,
):
    resolved_client = client or HttpEtfHoldingsClient(holdings_urls or {})
    return EtfHoldingsIndexSource(resolved_client, etf_for_index or {}, mic_for_index)


register_index_source(ARCHETYPE_ETF, _build_from_config)
