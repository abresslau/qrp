"""Tests for the completeness contract + result types (Story V1). DB-free pure logic."""

from __future__ import annotations

from sym.validate.completeness import MemberFlags, classify_member
from sym.validate.results import FAIL, PASS, WARN, CheckResult, status_for, worst


def _flags(**kw):
    base = dict(
        has_name=True, has_symbology=True, has_gics=True,
        has_prices=True, has_fundamentals=True, status="active", has_calendar=True,
    )
    base.update(kw)
    return MemberFlags(**base)


def test_complete_member_is_ok():
    c = classify_member(_flags())
    assert c.is_complete and c.severity == "ok" and c.missing == []


def test_missing_metadata_is_fail():
    c = classify_member(_flags(has_gics=False))
    assert not c.is_complete and c.severity == "fail" and "gics" in c.missing
    assert "metadata" in c.reason


def test_priceable_missing_market_is_fail():
    c = classify_member(_flags(has_prices=False, has_fundamentals=False))
    assert c.severity == "fail" and "priceable" in c.reason
    assert set(c.missing) == {"prices", "fundamentals"}


def test_delisted_missing_market_is_expected_warn():
    c = classify_member(_flags(status="delisted", has_prices=False, has_fundamentals=False))
    assert c.severity == "warn" and "delisted" in c.reason


def test_no_calendar_missing_market_is_expected_warn():
    c = classify_member(_flags(has_calendar=False, has_prices=False))
    assert c.severity == "warn" and "calendar" in c.reason


def test_missing_metadata_outranks_market_gap_even_when_delisted():
    # A delisted name still must not lack metadata -> fail (metadata is fillable).
    c = classify_member(_flags(status="delisted", has_name=False, has_prices=False))
    assert c.severity == "fail" and "name" in c.missing


# --- result types ---


def test_status_for_and_worst():
    assert status_for(0, 0) == PASS
    assert status_for(0, 3) == WARN
    assert status_for(2, 3) == FAIL
    assert worst([PASS, WARN, PASS]) == WARN
    assert worst([]) == PASS


def test_check_result_from_items_samples_and_status():
    r = CheckResult.from_items("x", checked=5, failures=["a", "b"], warnings=["c"])
    assert r.status == FAIL and r.failures == 2 and r.warnings == 1 and not r.ok
    assert any(s.startswith("FAIL ") for s in r.samples)


def test_check_result_warn_only_is_ok():
    r = CheckResult.from_items("x", checked=5, warnings=["c"])
    assert r.status == WARN and r.ok
