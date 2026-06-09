"""DB-free tests for the equity↔instrument bridge set logic (Story B7)."""

from __future__ import annotations

from sym.validate.instrument_bridge import find_orphan_instruments, find_unmapped


def test_find_unmapped_flags_securities_with_no_equity_mapping():
    securities = {"BBG000000001", "BBG000000002", "BBG000000003"}
    # 002 maps nowhere (or only to a non-equity instrument → absent from equity_mapped_figis)
    equity_mapped = {"BBG000000001", "BBG000000003"}
    assert find_unmapped(securities, equity_mapped) == {"BBG000000002"}


def test_find_unmapped_clean_when_all_mapped():
    s = {"BBG000000001", "BBG000000002"}
    assert find_unmapped(s, s) == set()
    assert find_unmapped(set(), {"BBG000000001"}) == set()


def test_find_unmapped_ignores_empty_figi():
    assert find_unmapped({"", "BBG000000001"}, set()) == {"BBG000000001"}


def test_find_orphan_instruments_flags_equity_without_figi_xref():
    equity_sym_ids = {1, 2, 3}
    with_figi_xref = {1, 3}
    assert find_orphan_instruments(equity_sym_ids, with_figi_xref) == {2}


def test_find_orphan_instruments_clean_when_all_have_xref():
    assert find_orphan_instruments({1, 2}, {1, 2, 3}) == set()
    assert find_orphan_instruments(set(), {1}) == set()
