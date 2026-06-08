"""Tests for the membership accuracy gate (Story U3.3). DB-free pure logic."""

from __future__ import annotations

from datetime import date

from sym.universe.accuracy import current_tokens_from_changes, evaluate
from sym.universe.registry import JOIN, LEAVE, MembershipChange


def test_identical_sets_no_divergence_no_alarm():
    s = {"ticker:A@XNYS", "ticker:B@XNYS"}
    r = evaluate(set(s), set(s), threshold=0.05)
    assert r.divergence == 0.0 and not r.alarm


def test_divergence_is_jaccard_distance():
    maintained = {"A", "B", "C", "D"}
    reference = {"A", "B", "C", "E"}  # 1 missing (E), 1 extra (D); union 5
    r = evaluate(maintained, reference, threshold=0.05)
    assert r.missing == {"E"} and r.extra == {"D"}
    assert abs(r.divergence - 2 / 5) < 1e-9
    assert r.alarm  # 0.4 > 0.05


def test_small_divergence_below_threshold_no_alarm():
    maintained = set(f"T{i}" for i in range(100))
    reference = set(f"T{i}" for i in range(100)) - {"T0"} | {"NEW"}  # 2/101 ≈ 0.0198
    r = evaluate(maintained, reference, threshold=0.05)
    assert not r.alarm


def test_proxy_tolerance_widens_threshold():
    maintained = set(f"T{i}" for i in range(100))
    reference = set(f"T{i}" for i in range(100)) - {"T0", "T1", "T2"} | {"X", "Y", "Z"}
    # symmetric diff 6 / union 103 ≈ 0.058 -> alarms at 0.05, not at 0.05+0.05
    assert evaluate(maintained, reference, threshold=0.05).alarm
    assert not evaluate(maintained, reference, threshold=0.05, proxy_tolerance=0.05).alarm


def test_empty_union_no_alarm():
    assert not evaluate(set(), set(), threshold=0.05).alarm


def test_current_tokens_ignores_leaves():
    changes = [
        MembershipChange("ticker:A@XNYS", JOIN, date(2024, 1, 1), "etf_holdings"),
        MembershipChange("ticker:B@XNYS", LEAVE, date(2024, 1, 1), "etf_holdings"),
    ]
    assert current_tokens_from_changes(changes) == {"ticker:A@XNYS"}
