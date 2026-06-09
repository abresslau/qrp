"""Tests for the scheduler-agnostic EOD runner (Module-1 orchestration). DB-free."""

from __future__ import annotations

from sym.eod import DAILY_STEPS, run_eod, select_steps


def test_select_steps_default_order():
    keys = [s.key for s in select_steps()]
    assert keys == ["monitor", "fill", "map", "benchmarks", "fx", "recompute", "validate"]


def test_select_only_and_skip():
    assert [s.key for s in select_steps(only=["fill", "recompute"])] == ["fill", "recompute"]
    assert "monitor" not in [s.key for s in select_steps(skip=["monitor"])]


def test_dry_run_plans_without_executing():
    calls = []
    summary = run_eod(None, dry_run=True, runner=lambda k: calls.append(k) or "x")
    assert calls == []  # nothing executed
    assert [r.status for r in summary.results] == ["planned"] * len(DAILY_STEPS)
    assert summary.ok


def test_runs_each_step_and_reports_ok():
    ran = []
    summary = run_eod(None, runner=lambda k: ran.append(k) or f"did {k}")
    assert ran == [s.key for s in DAILY_STEPS]
    assert summary.ok and all(r.ok for r in summary.results)


def test_critical_failure_fails_run_but_isolates():
    def runner(key):
        if key == "fill":  # critical step fails
            raise RuntimeError("vendor down")
        return "ok"

    summary = run_eod(None, runner=runner)
    # every step still attempted (error-isolated)
    assert {r.key for r in summary.results} == {s.key for s in DAILY_STEPS}
    assert not summary.ok  # a critical step errored
    fill = next(r for r in summary.results if r.key == "fill")
    assert fill.status == "error" and "vendor down" in fill.detail


def test_noncritical_failure_does_not_fail_run():
    def runner(key):
        if key == "monitor":  # non-critical
            raise RuntimeError("wiki blip")
        return "ok"

    summary = run_eod(None, runner=runner)
    assert summary.ok  # monitor is non-critical
    assert next(r for r in summary.results if r.key == "monitor").status == "error"
