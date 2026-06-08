"""Tests for sanity-gating + corroboration + reversal (Story U3.2). DB-free pure logic.

The staging/promotion/reversal DB functions are verified live on a synthetic universe.
"""

from __future__ import annotations

from datetime import date

from sym.universe.gating import (
    REASON_CHURN,
    REASON_PERSIST,
    churn_ratio,
    is_promotable,
    is_surprising,
)


def test_churn_ratio():
    assert churn_ratio(5, 100) == 0.05
    assert churn_ratio(5, 0) == 5.0  # zero denominator guarded


def test_is_surprising_threshold():
    assert not is_surprising(5, 100, 0.10)  # 5% < 10%
    assert is_surprising(20, 100, 0.10)  # 20% > 10%


def test_churn_gated_proposal_never_auto_promotes():
    # Even with persistence + corroboration, a churn-gated proposal needs an operator.
    assert not is_promotable(
        REASON_CHURN, date(2024, 1, 1), date(2024, 12, 31), 5,
        persist_days=2, min_corroborations=2,
    )


def test_promotable_on_persistence():
    assert is_promotable(
        REASON_PERSIST, date(2024, 1, 1), date(2024, 1, 5), 1,
        persist_days=2, min_corroborations=2,
    )  # 4 days >= 2


def test_promotable_on_corroboration_before_persistence():
    assert is_promotable(
        REASON_PERSIST, date(2024, 1, 1), date(2024, 1, 1), 2,
        persist_days=30, min_corroborations=2,
    )  # same day but 2 sources


def test_not_promotable_when_neither_met():
    assert not is_promotable(
        REASON_PERSIST, date(2024, 1, 1), date(2024, 1, 1), 1,
        persist_days=30, min_corroborations=2,
    )
