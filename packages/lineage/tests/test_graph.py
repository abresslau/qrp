"""Tests for the merged lineage graph (declared + auto-derived + FK) and the Mermaid diagram."""

from lineage import diagram
from lineage.assets import all_assets, edges, key_tables


def test_key_tables_composite_figi():
    kt = key_tables("composite_figi")
    assert {"securities", "fact_returns", "weight", "wiki_map"} <= kt
    assert "run" not in kt and "point" not in kt  # keyed by run_id / obs_date, not figi


def test_key_tables_sym_id_disjoint():
    kt = key_tables("sym_id")
    assert {"instrument", "index_levels", "fact_index_returns"} <= kt
    assert "securities" not in kt  # the two key-spaces are disjoint


def test_edges_cover_all_three_bases():
    pairs = {(f, t) for (f, t, _b) in edges()}
    assert ("securities", "prices_raw") in pairs        # FK referential (auto)
    assert ("prices_raw", "fact_returns") in pairs      # hand-declared transform
    assert ("fact_returns", "weight") in pairs          # auto-derived cross-package


def test_catalog_still_31_assets():
    assert len(all_assets()) == 31


def test_mermaid_renders_both_keys():
    md = diagram.render()
    assert "flowchart LR" in md
    assert "`composite_figi` field flow" in md and "`sym_id` field flow" in md
    assert "instrument --> index_levels" in md
    assert "securities --> prices_raw" in md


def test_modeled_set_matches_schemas():
    # _MODELED in generate.py is a hand-mirror of the asset tables — guard against drift.
    from lineage.generate import _MODELED
    from lineage.assets import SCHEMAS
    assert _MODELED == {t for (_db, t) in SCHEMAS}


def test_referential_basis_is_recorded():
    assert any(b == "referential" for (_f, _t, b) in edges())
