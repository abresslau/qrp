"""B3 (Brazil exchange) index portfolio source — Brazil index archetype.

The **authoritative** source for Brazilian index membership: B3 publishes each
index's official theoretical portfolio (Ibovespa, IBrX, …) via its listed-systems
``GetPortfolioDay`` endpoint. Unlike the scraped/proxy archetypes, this *is* the
index, so no cross-source corroboration is needed.

It is a **snapshot** source (the endpoint returns only the current portfolio), so
membership is derived from the constituent ticker **set** at ``end`` — weight
changes are not membership changes — and events are ``poll_bounded`` (the date is
bounded by the polling interval, not exact). B3 rebalances its indices three times
a year (Jan/May/Sep) plus ad-hoc corporate events; a daily ``sym universe monitor``
diff catches both. An empty/garbled response is a loud :class:`IndexSourceError`
(never applied as "every member left").

Maintenance: `pit_valid_from` is build-forward from the first monitor (the daily
endpoint carries no history); leavers are tracked forward via the monitor diff.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterable
from datetime import date
from typing import Protocol

import requests

from universe.membership_diff import ticker_token
from universe.providers.index_source import (
    ARCHETYPE_B3,
    IndexSourceError,
    register_index_source,
)
from universe.registry import JOIN, POLL_BOUNDED, MembershipChange

B3_PORTFOLIO_URL = (
    "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{token}"
)

# index key (our universe id) -> B3 index code + listing MIC. IBX = IBrX-100 (IBXX);
# IBrX-50 would be IBXL. All B3 equities list on BVMF.
_B3_SPECS: dict[str, dict] = {
    "ibov": {"code": "IBOV", "mic": "BVMF"},  # Ibovespa
    "ibx": {"code": "IBXX", "mic": "BVMF"},  # IBrX 100
}


def _portfolio_token(index_code: str, page_size: int = 500) -> str:
    """Base64 of the GetPortfolioDay request params (B3 encodes the query this way)."""
    params = {
        "language": "pt-br",
        "pageNumber": 1,
        "pageSize": page_size,
        "index": index_code,
        "segment": "1",
    }
    return base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")


def parse_portfolio_tokens(results: Iterable[dict], mic: str) -> set[str]:
    """Tokenize a GetPortfolioDay ``results`` list to resolver tokens (pure).

    Each row's ``cod`` is the B3 ticker (e.g. ``PETR4``); membership is the set of
    those tickers. Rows without a usable ``cod`` are skipped.
    """
    tokens: set[str] = set()
    for row in results:
        cod = (row.get("cod") or "").strip()
        if cod:
            tokens.add(ticker_token(cod, mic))
    return tokens


class B3Client(Protocol):
    """Returns the ``results`` rows of GetPortfolioDay for a B3 index code."""

    def portfolio(self, index_code: str) -> list[dict]: ...


class HttpB3Client:
    """Fetches the official theoretical portfolio from B3's listed-systems endpoint."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 25.0,
        max_retries: int = 3,
        user_agent: str = "sym-universe/1.0 (personal research)",
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._user_agent = user_agent

    def portfolio(self, index_code: str) -> list[dict]:
        url = B3_PORTFOLIO_URL.format(token=_portfolio_token(index_code))
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    url,
                    timeout=self._timeout,
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
            except requests.RequestException as exc:
                last = exc
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise IndexSourceError(
                    f"B3 returned HTTP {resp.status_code} for index {index_code!r}"
                )
            try:
                payload = resp.json()
            except ValueError as exc:
                raise IndexSourceError(f"B3 returned non-JSON for {index_code!r}: {exc}") from exc
            results = payload.get("results")
            if results is None:
                raise IndexSourceError(f"B3 response for {index_code!r} has no 'results'")
            page = payload.get("page") or {}
            total_pages = page.get("totalPages")
            if isinstance(total_pages, int) and total_pages > 1:
                # pageSize=500 covers every current B3 index; if an index ever outgrows
                # one page, truncated membership must be an error, not silent truth.
                raise IndexSourceError(
                    f"B3 portfolio for {index_code!r} spans {total_pages} pages "
                    "(pageSize=500 exceeded) — pagination not implemented"
                )
            return results
        raise IndexSourceError(f"B3 unreachable after {self._max_retries}: {last}")


class B3IndexSource:
    """Derives index membership from B3's official theoretical portfolio."""

    archetype = ARCHETYPE_B3
    # The full current-membership token set from the last fetch (U3.5): B3's endpoint
    # IS the current portfolio, so the whole output is a snapshot — the monitor's
    # leaver diff may trust it.
    last_snapshot_tokens: set[str] | None = None

    def __init__(self, client: B3Client, specs: dict[str, dict] | None = None) -> None:
        self._client = client
        self._specs = {**_B3_SPECS, **(specs or {})}

    def fetch(self, index_key: str, start: date, end: date) -> list[MembershipChange]:
        # Reset on entry: a raising fetch must not leak the PREVIOUS call's
        # snapshot to a later reader (instances serve multiple indices).
        self.last_snapshot_tokens = None
        spec = self._specs.get(index_key)
        if spec is None:
            raise IndexSourceError(f"no B3 spec for index {index_key!r}")
        results = self._client.portfolio(spec["code"])
        tokens = parse_portfolio_tokens(results, spec["mic"])
        if not tokens:
            # Empty/garbled parse: an error, never "every member left".
            raise IndexSourceError(
                f"B3 portfolio for {index_key!r} ({spec['code']}) parsed to zero constituents"
            )
        source = f"{ARCHETYPE_B3}:{spec['code']}"
        self.last_snapshot_tokens = set(tokens)
        return [MembershipChange(tok, JOIN, end, source, POLL_BOUNDED) for tok in sorted(tokens)]


def _build_from_config(
    client: B3Client | None = None, specs: dict[str, dict] | None = None, **_: object
):
    return B3IndexSource(client or HttpB3Client(), specs)


register_index_source(ARCHETYPE_B3, _build_from_config)
