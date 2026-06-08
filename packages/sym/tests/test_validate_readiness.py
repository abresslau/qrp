"""Tests for the universe readiness gate (Story V6). DB-free pure logic."""

from __future__ import annotations

from sym.validate.readiness import _missing_reason, coverage_pct


def test_coverage_pct():
    assert coverage_pct(100, 90) == 0.90
    # The math helper returns 1.0 for an empty set; the check handles a zero-member
    # universe separately (warn "no current members"), so it never silently passes.
    assert coverage_pct(0, 0) == 1.0


def test_missing_reason_priority():
    assert _missing_reason(has_prices=True, has_calendar=False) == "no calendar"
    assert _missing_reason(has_prices=False, has_calendar=True) == "unpriced"
    assert _missing_reason(has_prices=True, has_calendar=True).startswith("priced but no returns")
