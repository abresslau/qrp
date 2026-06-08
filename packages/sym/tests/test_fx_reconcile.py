"""FX cross-source divergence reconcile (Epic FX, FR4b). DB-free pure-function tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sym.fx.reconcile import DEFAULT_DIVERGENCE, compare, relative_divergence


def test_relative_divergence_is_symmetric_magnitude_vs_reference():
    # 5.05 vs reference 5.00 -> 1% high; the reverse is ~0.99% (relative to a larger base).
    assert relative_divergence(Decimal("5.05"), Decimal("5.00")) == Decimal("0.01")
    assert round(relative_divergence(Decimal("5.00"), Decimal("5.05")), 6) == Decimal("0.009901")


def test_relative_divergence_rejects_nonpositive_reference():
    with pytest.raises(ValueError):
        relative_divergence(Decimal("5"), Decimal("0"))


def test_compare_flags_only_above_threshold_worst_first():
    rows = [
        ("BRL", date(2024, 1, 2), Decimal("5.00"), Decimal("5.00")),  # 0% -> not flagged
        ("GBP", date(2024, 1, 2), Decimal("0.808"), Decimal("0.800")),  # 1.0% -> flagged
        ("EUR", date(2024, 1, 2), Decimal("0.920"), Decimal("0.900")),  # ~2.2% -> flagged
    ]
    flagged = compare(rows, threshold=DEFAULT_DIVERGENCE)  # 0.5%
    assert [d.currency for d in flagged] == ["EUR", "GBP"]  # worst-first
    assert flagged[0].rel > flagged[1].rel


def test_compare_empty_when_all_within_threshold():
    rows = [("BRL", date(2024, 1, 2), Decimal("5.001"), Decimal("5.000"))]  # 0.02%
    assert compare(rows, threshold=DEFAULT_DIVERGENCE) == []
