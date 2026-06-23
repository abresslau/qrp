"""Tests for index returns + alpha (B3). DB-free pure logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sym.indices.returns import IndexReturnsSummary, alpha, index_return_rows


def test_alpha_excess_return():
    assert alpha(Decimal("0.12"), Decimal("0.10")) == Decimal("0.02")
    assert alpha(None, Decimal("0.10")) is None
    assert alpha(Decimal("0.12"), None) is None


def test_index_return_rows_one_day():
    # Two consecutive sessions; the 1-day window return = level ratio - 1.
    sessions = [date(2024, 1, 2), date(2024, 1, 3)]
    levels = {date(2024, 1, 2): Decimal("100"), date(2024, 1, 3): Decimal("110")}
    rows = index_return_rows(7, levels, [date(2024, 1, 3)], sessions)
    # window_id 1 is the 1-day window (see returns.windows); ret = 110/100 - 1 = 0.10
    one_day = [ret for _s, wid, _a, ret in rows if wid == 1]
    assert one_day and abs(one_day[0] - Decimal("0.10")) < Decimal("0.0001")
    # carries sym_id through
    assert all(s == 7 for s, _w, _a, _r in rows)


def test_index_return_rows_insufficient_history_is_none():
    sessions = [date(2024, 1, 3)]
    levels = {date(2024, 1, 3): Decimal("110")}
    rows = index_return_rows(7, levels, [date(2024, 1, 3)], sessions)
    # No prior session -> every window that needs history is None. The one exception
    # is cumulative since-inception (window 27, SI): its base IS the first session, so
    # day-one total return is a legitimate 0 (annualized SI_ANN stays None -- a
    # zero-length span can't be annualized).
    for _s, wid, _a, ret in rows:
        assert ret == Decimal("0") if wid == 27 else ret is None


def test_index_summary_counts_extreme_rows():
    """IndexReturnsSummary exposes extreme_rows for the indices CLI line (Story 3.2-ext)."""
    assert IndexReturnsSummary().extreme_rows == 0
