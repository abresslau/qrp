"""Tests for universe<->index linking (Index epic B5). DB-free."""

from __future__ import annotations

from indices.levels import INDICES
from indices.links import UNIVERSE_INDICES


def test_every_mapping_has_exactly_one_primary():
    for universe_id, links in UNIVERSE_INDICES.items():
        primaries = [lk for lk in links if lk[2]]
        assert len(primaries) == 1, f"{universe_id} must have exactly one primary index"


def test_mapping_roles_valid():
    valid = {"price_return", "total_return", "net_total_return"}
    for links in UNIVERSE_INDICES.values():
        assert all(role in valid for _sym, role, _p in links)


def test_mapped_yahoo_symbols_exist_in_registry():
    registry_syms = {b.yahoo_symbol for b in INDICES if b.yahoo_symbol}
    for universe_id, links in UNIVERSE_INDICES.items():
        for yahoo_symbol, _role, _p in links:
            assert yahoo_symbol in registry_syms, (
                f"{universe_id} links {yahoo_symbol} which is not in the index registry"
            )


def test_sp500_links_both_price_and_total_return():
    roles = {role: sym for sym, role, _p in UNIVERSE_INDICES["sp500"]}
    assert roles["price_return"] == "^GSPC"
    assert roles["total_return"] == "^SP500TR"
