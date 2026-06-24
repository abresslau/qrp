"""Universe catalogue sanity — pure, no DB/network."""

from __future__ import annotations

from commodities.universe import BY_CODE, SECTORS, UNIVERSE, sector_rank


def test_codes_unique_and_indexed():
    codes = [c.code for c in UNIVERSE]
    assert len(codes) == len(set(codes)), "duplicate commodity_code"
    assert set(BY_CODE) == set(codes)


def test_every_commodity_has_valid_sector_and_ticker():
    sectors = {s for s, _ in SECTORS}
    for c in UNIVERSE:
        assert c.sector in sectors, f"{c.code} has unknown sector {c.sector}"
        assert c.yahoo.endswith("=F"), f"{c.code} yahoo ticker looks wrong: {c.yahoo}"
        assert c.unit and c.currency and c.exchange


def test_sector_rank_orders_by_declared_sequence():
    assert sector_rank("energy") < sector_rank("livestock")
    assert sector_rank("unknown_sector") == len(SECTORS)


def test_universe_spans_all_sectors():
    covered = {c.sector for c in UNIVERSE}
    assert covered == {s for s, _ in SECTORS}, "a declared sector has no commodities"
