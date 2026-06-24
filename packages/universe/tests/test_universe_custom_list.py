"""Tests for the custom-list provider (Story U1.7). DB-free.

The provider loads the seed universe and emits one join per name; resolution +
projection of the real seed are verified live (they reuse existing securities).
"""

from __future__ import annotations

from datetime import date

from universe.providers.custom_list import CustomListProvider, member_token
from universe.registry import CUSTOM_LIST, JOIN, is_registered
from universe.seeds import Seed, load_seed_universe


def _seed(ticker="AAPL", mic="XNAS", isin="US0378331005"):
    return Seed("Apple", "forward_split", ticker, mic, isin)


def test_custom_list_provider_is_registered():
    import universe.providers  # noqa: F401  (triggers registration)

    assert is_registered(CUSTOM_LIST)


def test_member_token_prefers_ticker_then_isin():
    assert member_token(_seed()) == "ticker:AAPL@XNAS"
    assert member_token(_seed(ticker=None, mic=None)) == "isin:US0378331005"


def test_provider_emits_one_join_per_seed_name_at_inception():
    start = date(2026, 6, 7)
    changes = list(CustomListProvider().members(start, date(2026, 6, 7)))
    seed = load_seed_universe()
    assert len(changes) == len(seed)
    assert all(c.change == JOIN and c.effective_date == start for c in changes)
    tokens = {c.raw_identifier for c in changes}
    assert "ticker:AAPL@XNAS" in tokens  # a known seed name


def test_provider_tokens_are_resolvable_shape():
    changes = list(CustomListProvider().members(date(2026, 6, 7), date(2026, 6, 7)))
    assert all(
        c.raw_identifier.startswith(("ticker:", "isin:")) for c in changes
    )
