"""Commodity trailing-window returns (pure compute) — DB-free.

Mirrors the index-returns test: a price return is the settle ratio over the window; insufficient
history or a non-positive endpoint → None. One row per (window) for each as_of_date.
"""

from datetime import date
from decimal import Decimal

from equity.returns.windows import WINDOWS

from commodity.returns import commodity_return_rows


def _settles():
    # a short daily settle series for one commodity (06-22 … 06-27)
    vals = [100, 101, 102, 103, 105, 104]  # 6 sessions
    return {date(2026, 6, 22 + i): Decimal(v) for i, v in enumerate(vals)}


def test_one_row_per_window_per_as_of():
    settles = _settles()
    sessions = sorted(settles)
    rows = commodity_return_rows("WTI", settles, [date(2026, 6, 27)], sessions)
    # one row per window, all tagged with the commodity_code + as_of_date
    assert len(rows) == len(WINDOWS)
    assert {r[0] for r in rows} == {"WTI"}
    assert {r[2] for r in rows} == {date(2026, 6, 27)}
    assert {r[1] for r in rows} == {w.code for w in WINDOWS}  # window codes


def test_1d_return_is_settle_ratio():
    settles = _settles()
    sessions = sorted(settles)
    rows = commodity_return_rows("WTI", settles, [date(2026, 6, 27)], sessions)
    by_code = {wc: ret for (_c, wc, _d, ret) in rows}
    # series ends 06-26=105, 06-27=104; 1D return on 06-27 vs prior session 06-26 = 104/105 - 1
    assert by_code["1D"] is not None
    assert abs(float(by_code["1D"]) - (104 / 105 - 1)) < 1e-9


def test_insufficient_history_is_none():
    settles = _settles()
    sessions = sorted(settles)
    rows = commodity_return_rows("WTI", settles, [date(2026, 6, 27)], sessions)
    by_code = {wc: ret for (_c, wc, _d, ret) in rows}
    # a multi-year window has no base in a 6-day series → None
    assert by_code["5Y"] is None


def test_non_positive_settle_yields_none():
    # negative WTI (Apr-2020 style) → the canonical return rule treats it as undefined
    settles = {date(2026, 6, 25): Decimal("10"), date(2026, 6, 26): Decimal("-5")}
    sessions = sorted(settles)
    rows = commodity_return_rows("WTI", settles, [date(2026, 6, 26)], sessions)
    by_code = {wc: ret for (_c, wc, _d, ret) in rows}
    assert by_code["1D"] is None  # 1D return touches the negative settle
