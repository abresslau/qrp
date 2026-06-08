"""Tests for universe<->benchmark linking (Benchmark epic B5). DB-free."""

from __future__ import annotations

from sym.benchmarks.levels import BENCHMARKS
from sym.benchmarks.links import UNIVERSE_BENCHMARKS


def test_every_mapping_has_exactly_one_primary():
    for universe_id, links in UNIVERSE_BENCHMARKS.items():
        primaries = [lk for lk in links if lk[2]]
        assert len(primaries) == 1, f"{universe_id} must have exactly one primary benchmark"


def test_mapping_roles_valid():
    valid = {"price_return", "total_return", "net_total_return"}
    for links in UNIVERSE_BENCHMARKS.values():
        assert all(role in valid for _sym, role, _p in links)


def test_mapped_yahoo_symbols_exist_in_registry():
    registry_syms = {b.yahoo_symbol for b in BENCHMARKS if b.yahoo_symbol}
    for universe_id, links in UNIVERSE_BENCHMARKS.items():
        for yahoo_symbol, _role, _p in links:
            assert yahoo_symbol in registry_syms, (
                f"{universe_id} links {yahoo_symbol} which is not in the benchmark registry"
            )


def test_sp500_links_both_price_and_total_return():
    roles = {role: sym for sym, role, _p in UNIVERSE_BENCHMARKS["sp500"]}
    assert roles["price_return"] == "^GSPC"
    assert roles["total_return"] == "^SP500TR"
