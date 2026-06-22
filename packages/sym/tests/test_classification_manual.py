"""Manual (operator-asserted) GICS source tests — no network, matches by composite_figi."""

from __future__ import annotations

import json

import pytest

from sym.classification.gics import SecurityIdentity, outranks
from sym.classification.llm import GICS_SECTORS
from sym.classification.manual import (
    ManualClassificationError,
    ManualGicsSource,
    ManualRecord,
    load_manual_classifications,
)

# --- the shipped artifact loads + is sane -----------------------------------------------


def test_shipped_artifact_loads_and_is_all_gics():
    records = load_manual_classifications()
    assert records, "the shipped artifact should carry at least one classification"
    for rec in records:
        assert rec.sector in GICS_SECTORS
        assert rec.composite_figi  # every row names an exact security


def test_shipped_artifact_covers_the_ftse_investment_trusts():
    by_figi = {r.composite_figi: r for r in load_manual_classifications()}
    # the three FTSE-100 investment trusts the live sources can't reach in-env → Financials
    for figi in ("BBG000BFZM24", "BBG000HHH6S1", "BBG000BFH585"):
        assert figi in by_figi
        assert by_figi[figi].sector == "Financials"


# --- precedence: manual is high-trust (above every automated source, below FD) ----------


def test_manual_precedence_is_below_financedatabase_above_automated():
    assert outranks("financedatabase", "manual")  # FD primary still wins
    for automated in ("b3", "sec_sic", "fmp", "yahoo_profile", "wikidata", "llm", "google"):
        assert outranks("manual", automated), f"manual must outrank {automated}"


# --- matching by composite_figi ---------------------------------------------------------


def test_matches_by_figi_sector_only_source_manual():
    src = ManualGicsSource(
        [ManualRecord(composite_figi="FIGI_A", sector="Financials", ticker="SMT")]
    )
    out = src.fetch(
        [
            SecurityIdentity(composite_figi="FIGI_A", ticker="SMT", mic="XLON"),
            SecurityIdentity(composite_figi="FIGI_B", ticker="XXX", mic="XLON"),
        ]
    )
    assert set(out) == {"FIGI_A"}
    c = out["FIGI_A"]
    assert c.sector_name == "Financials"
    assert c.source == "manual"
    # sector-only — industry levels NULL (matching b3/sec_sic/yahoo)
    assert c.industry_group_name is None and c.industry_name is None
    assert src.last_unmatched == ["FIGI_B"]
    assert src.last_unused == []


def test_artifact_row_not_in_scope_is_reported_unused():
    # a stale/obsolete manual row whose figi isn't in the in-scope set is surfaced, not silent
    src = ManualGicsSource([ManualRecord(composite_figi="GONE", sector="Energy")])
    out = src.fetch([SecurityIdentity(composite_figi="OTHER", ticker="ZZZ", mic="XNYS")])
    assert out == {}
    assert src.last_unused == ["GONE"]


# --- load validation --------------------------------------------------------------------


def test_load_refuses_non_gics_sector(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps({"classifications": [{"composite_figi": "F", "sector": "Banking"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ManualClassificationError, match="non-GICS sector"):
        load_manual_classifications(p)


def test_load_refuses_missing_figi_or_sector(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"classifications": [{"sector": "Financials"}]}), encoding="utf-8")
    with pytest.raises(ManualClassificationError, match="missing composite_figi/sector"):
        load_manual_classifications(p)


def test_duplicate_figi_refused():
    with pytest.raises(ManualClassificationError, match="duplicate composite_figi"):
        ManualGicsSource(
            [
                ManualRecord(composite_figi="DUP", sector="Energy"),
                ManualRecord(composite_figi="DUP", sector="Financials"),
            ]
        )


def test_missing_file_is_explicit_error(tmp_path):
    with pytest.raises(ManualClassificationError, match="not found"):
        load_manual_classifications(tmp_path / "nope.json")
