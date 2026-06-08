"""Tests for the seed universe loader (Story 1.5)."""

import pytest

from sym.identity.universe import (
    ISIN,
    TICKER,
    ResolutionInput,
    SeedUniverseError,
    load_seed_universe,
)

# Categories the AC requires the seed set to span.
REQUIRED_CATEGORIES = {
    "forward_split",
    "reverse_split",
    "special_dividend",
    "stock_dividend",
    "spin_off",
    "multi_currency",
    "adr",
    "delisting",
}


@pytest.fixture(scope="module")
def universe():
    return load_seed_universe()


def test_seed_universe_has_about_fifty_names(universe):
    assert 45 <= len(universe) <= 55


def test_required_adversarial_categories_present(universe):
    present = {s.category for s in universe}
    missing = REQUIRED_CATEGORIES - present
    assert not missing, f"seed universe missing categories: {missing}"


def test_at_least_one_delisting(universe):
    assert any(s.category == "delisting" for s in universe)


def test_every_entry_yields_a_valid_resolution_input(universe):
    for s in universe:
        inputs = s.resolution_inputs()
        assert inputs, f"{s.name} yields no resolution input"
        for ri in inputs:
            assert ri.symbol_type in (TICKER, ISIN)
            assert ri.symbol_value
            if ri.symbol_type == TICKER:
                assert ri.mic, f"{s.name} ticker input missing mic"


def test_every_entry_documents_rationale(universe):
    # The adversarial 'why' must be inline so the set stays meaningful as fixtures.
    for s in universe:
        assert s.note, f"{s.name} is missing an inline rationale note"


def test_ticker_resolution_input_requires_mic():
    with pytest.raises(SeedUniverseError):
        ResolutionInput(TICKER, "AAPL", mic=None)


def test_isin_resolution_input_needs_no_mic():
    ri = ResolutionInput(ISIN, "US0378331005")
    assert ri.mic is None


def test_unknown_symbol_type_rejected():
    with pytest.raises(SeedUniverseError):
        ResolutionInput("cusip", "037833100")


def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(SeedUniverseError):
        load_seed_universe(tmp_path / "does_not_exist.toml")


def test_load_rejects_entry_with_no_identifier(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[[security]]\nname = "No IDs"\ncategory = "baseline"\n',
        encoding="utf-8",
    )
    with pytest.raises(SeedUniverseError):
        load_seed_universe(bad)
