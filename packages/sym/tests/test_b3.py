"""B3 (Brazil) index portfolio source. DB-free + network-free (fake client)."""

from __future__ import annotations

from datetime import date

import pytest

from sym.universe.membership_diff import ticker_token
from sym.universe.providers.b3 import (
    B3IndexSource,
    _portfolio_token,
    parse_portfolio_tokens,
)
from sym.universe.providers.index_source import (
    ARCHETYPE_B3,
    ARCHETYPES,
    IndexSourceError,
    get_index_source,
    is_registered,
)
from sym.universe.registry import JOIN, POLL_BOUNDED

# A trimmed GetPortfolioDay `results` payload (Brazilian comma-decimals in `part`).
_SAMPLE = [
    {"cod": "PETR4", "asset": "PETROBRAS", "part": "8,123"},
    {"cod": "VALE3", "asset": "VALE", "part": "7,500"},
    {"cod": "ITUB4", "asset": "ITAUUNIBANCO", "part": "5,001"},
    {"cod": "", "asset": "(blank row)", "part": "0,000"},  # skipped
]


class _FakeB3Client:
    def __init__(self, results):
        self.results = results
        self.requested: list[str] = []

    def portfolio(self, index_code):
        self.requested.append(index_code)
        return self.results


def test_b3_archetype_is_registered():
    assert ARCHETYPE_B3 == "b3" and "b3" in ARCHETYPES
    assert is_registered("b3")
    assert isinstance(get_index_source("b3", client=_FakeB3Client(_SAMPLE)), B3IndexSource)


def test_parse_portfolio_tokens_tickers_only():
    tokens = parse_portfolio_tokens(_SAMPLE, "BVMF")
    # the blank `cod` row is dropped; the three real tickers tokenize on BVMF
    assert tokens == {ticker_token(t, "BVMF") for t in ("PETR4", "VALE3", "ITUB4")}


def test_fetch_emits_poll_bounded_joins_for_known_index():
    client = _FakeB3Client(_SAMPLE)
    src = B3IndexSource(client)
    end = date(2026, 6, 8)
    changes = src.fetch("ibov", date(2026, 1, 1), end)
    assert client.requested == ["IBOV"]  # ibov -> B3 code IBOV
    assert {c.raw_identifier for c in changes} == parse_portfolio_tokens(_SAMPLE, "BVMF")
    assert all(c.change == JOIN and c.effective_date == end for c in changes)
    assert all(
        c.effective_date_precision == POLL_BOUNDED and c.source == "b3:IBOV" for c in changes
    )


def test_ibx_maps_to_ibrx_100_code():
    client = _FakeB3Client(_SAMPLE)
    B3IndexSource(client).fetch("ibx", date(2026, 1, 1), date(2026, 6, 8))
    assert client.requested == ["IBXX"]  # ibx -> IBrX 100


def test_unknown_index_key_raises():
    with pytest.raises(IndexSourceError, match="no B3 spec"):
        B3IndexSource(_FakeB3Client(_SAMPLE)).fetch("nikkei", date(2026, 1, 1), date(2026, 6, 8))


def test_empty_portfolio_is_error_not_empty_membership():
    # A garbled/empty parse must raise (never "every member left"), per NFR2.
    with pytest.raises(IndexSourceError, match="zero constituents"):
        src = B3IndexSource(_FakeB3Client([{"cod": ""}]))
        src.fetch("ibov", date(2026, 1, 1), date(2026, 6, 8))


def test_portfolio_token_round_trips_index_code():
    import base64
    import json

    token = _portfolio_token("IBOV")
    decoded = json.loads(base64.b64decode(token))
    assert decoded["index"] == "IBOV" and decoded["segment"] == "1"
