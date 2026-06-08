"""Tests for the validate orchestration report (Story V7). DB-free pure logic."""

from __future__ import annotations

from sym.validate.results import FAIL, PASS, WARN, CheckResult
from sym.validate.runner import format_report, summarize


def _r(name, status, **kw):
    return CheckResult(name=name, status=status, **kw)


def test_summarize_counts_and_overall():
    results = [_r("a", PASS), _r("b", WARN), _r("c", FAIL)]
    passed, warned, failed, overall = summarize(results)
    assert (passed, warned, failed) == (1, 1, 1) and overall == FAIL


def test_summarize_warn_overall_when_no_fail():
    assert summarize([_r("a", PASS), _r("b", WARN)])[3] == WARN


def test_summarize_all_pass():
    assert summarize([_r("a", PASS), _r("b", PASS)])[3] == PASS


def test_format_report_includes_each_check_and_overall():
    results = [
        _r("completeness", FAIL, checked=10, failures=2, samples=["FAIL x: missing gics"]),
        _r("integrity", PASS, checked=9),
    ]
    out = format_report(results)
    assert "[FAIL] completeness" in out
    assert "[PASS] integrity" in out
    assert "missing gics" in out
    assert "overall: FAIL" in out
