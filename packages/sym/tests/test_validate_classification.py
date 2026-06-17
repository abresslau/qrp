"""Tests for the GICS classification coverage gate (AC6 guardrail). DB-free pure logic."""

from __future__ import annotations

from sym.validate.classification import coverage_detail


def test_coverage_above_threshold_passes_and_reports_breakdown():
    by_source = [("financedatabase", 1968), ("yahoo_profile", 97), ("b3", 49)]
    failures, detail = coverage_detail(2114, 2187, by_source, threshold=0.90)
    assert failures == []  # 96.7% ≥ 90% → no FAIL
    assert "2114/2187" in detail
    assert "96.7%" in detail
    assert "financedatabase 1968" in detail  # by-source breakdown always shown


def test_coverage_below_threshold_fails():
    # a source broke / a wave of members went unclassified → coverage dropped below the floor
    by_source = [("financedatabase", 1700)]
    failures, detail = coverage_detail(1700, 2187, by_source, threshold=0.90)
    assert len(failures) == 1
    assert "below the 90% threshold" in failures[0]
    assert "77.7%" in failures[0]
    assert "financedatabase 1700" in failures[0]  # breakdown points at what's left


def test_empty_universe_is_full_coverage_not_a_div_by_zero():
    failures, detail = coverage_detail(0, 0, [], threshold=0.90)
    assert failures == []  # 0/0 → 100% (nothing to classify), never a crash
    assert "100.0%" in detail
    assert "by source: none" in detail


def test_unknown_source_labelled():
    failures, detail = coverage_detail(10, 10, [(None, 10)], threshold=0.90)
    assert "unknown 10" in detail
