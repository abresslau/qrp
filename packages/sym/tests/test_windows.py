"""Tests for the return-window spec (Story 3.1). Pure, no DB."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sym.returns.windows import (
    BY_CODE,
    WINDOWS,
    Window,
    _minus_months,
    base_date,
    canonical_return,
    end_date,
    period_years,
)


def _weekdays(start, end):
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = _weekdays(date(2020, 1, 1), date(2024, 12, 31))


def _base(code, asof, sessions=SESSIONS):
    return base_date(BY_CODE[code], asof, sessions)


# --- the window set ---------------------------------------------------------


def test_window_set_has_stable_unique_ids():
    assert len(WINDOWS) == 28
    assert [w.id for w in WINDOWS] == list(range(1, 29))
    assert len({w.code for w in WINDOWS}) == 28
    assert "1W" in BY_CODE
    # Appended (never renumbered) so existing materialized rows stay valid.
    assert BY_CODE["5D"].id == 19 and BY_CODE["10D"].id == 20
    assert BY_CODE["5Y"].id == 23 and BY_CODE["SI"].id == 27 and BY_CODE["PQ"].id == 28
    # Cumulative multi-year siblings are NOT annualized (vs their *_ANN twins).
    assert BY_CODE["5Y"].annualized is False and BY_CODE["5Y_ANN"].annualized is True
    # `kind` is internal plumbing: every non-calendar window is trailing/discrete,
    # never the legacy 'rolling'/'multiyear' split. 5Y and 3M share one kind.
    assert {w.kind for w in WINDOWS} == {"calendar", "session", "trailing", "inception", "period"}
    assert BY_CODE["5Y"].kind == BY_CODE["3M"].kind == "trailing"


# --- session-count base = N trading days back (5D, 10D) ---------------------


def test_session_count_bases():
    asof = date(2024, 6, 14)  # Friday
    # 5 trading days back: 6/13, 6/12, 6/11, 6/10, 6/7 -> 6/7.
    assert _base("5D", asof) == date(2024, 6, 7)
    # 10 trading days back continues: 6/6, 6/5, 6/4, 6/3, 5/31 -> 5/31.
    assert _base("10D", asof) == date(2024, 5, 31)
    # 5D with sessions==5 lands one further back than 1D (which is 1 session back).
    assert _base("1D", asof) == date(2024, 6, 13)


def test_session_count_returns_none_when_history_short():
    early = [SESSIONS[i] for i in range(3)]  # only 3 sessions exist
    assert base_date(BY_CODE["5D"], early[-1], early) is None  # can't reach 5 back


# --- discrete prior period: PQ = last completed quarter (both endpoints past) ----


def test_prior_quarter_endpoints_are_the_completed_quarter():
    pq = BY_CODE["PQ"]
    asof = date(2024, 11, 15)  # in Q4 -> the just-completed quarter is Q3
    # end = last session of Q3 (2024-09-30 was a Mon), base = last session of Q2 (06-28 Fri).
    assert end_date(pq, asof, SESSIONS) == date(2024, 9, 30)
    assert base_date(pq, asof, SESSIONS) == date(2024, 6, 28)
    # Contrast QTD (current quarter, ends at as-of): base = prior-quarter end, end = as-of.
    assert end_date(BY_CODE["QTD"], asof, SESSIONS) == asof
    assert base_date(BY_CODE["QTD"], asof, SESSIONS) == date(2024, 9, 30)


def test_prior_quarter_none_when_no_completed_quarter():
    # asof in the first quarter with no sessions before it -> nothing completed.
    sessions = _weekdays(date(2024, 1, 1), date(2024, 2, 15))
    assert base_date(BY_CODE["PQ"], date(2024, 2, 1), sessions) is None


# --- calendar-anchored base = prior period-end (AC #1) ----------------------


def test_calendar_anchored_bases():
    asof = date(2024, 6, 14)  # Friday
    assert _base("1D", asof) == date(2024, 6, 13)  # prior session
    assert _base("WTD", asof) == date(2024, 6, 7)  # last session of prior week
    assert _base("MTD", asof) == date(2024, 5, 31)  # last session of prior month
    assert _base("QTD", asof) == date(2024, 3, 29)  # last session of prior quarter
    assert _base("YTD", asof) == date(2023, 12, 29)  # last session of prior year


# --- rolling: same calendar date N prior, snapped on/before (AC #1) ---------


def test_rolling_on_a_trading_day():
    asof = date(2024, 6, 14)
    assert _base("1M", asof) == date(2024, 5, 14)
    assert _base("1Y", asof) == date(2023, 6, 14)


def test_rolling_target_on_weekend_snaps_to_prior_session():
    asof = date(2024, 6, 10)  # 3M back = 2024-03-10 (Sunday)
    assert _base("3M", asof) == date(2024, 3, 8)  # last session on/before


def test_rolling_1w_is_seven_days_back_not_week_to_date():
    asof = date(2024, 6, 12)  # Wednesday
    assert _base("1W", asof) == date(2024, 6, 5)  # rolling 7 days back
    assert _base("WTD", asof) == date(2024, 6, 7)  # calendar: last session of prior week


# --- multi-year + since-inception (AC #2) -----------------------------------


def test_multiyear_and_inception_bases():
    asof = date(2024, 6, 14)
    assert _base("2Y_ANN", asof) == date(2022, 6, 14)
    assert _base("SI_ANN", asof) == SESSIONS[0]  # first available close


# --- NULL rule (AC #4) ------------------------------------------------------


def test_insufficient_history_is_none():
    asof = date(2020, 6, 15)
    assert _base("5Y_ANN", asof) is None  # history starts 2020; 2015 unreachable
    assert base_date(BY_CODE["1D"], SESSIONS[0], SESSIONS) is None  # no prior session


# --- month arithmetic clamps day -------------------------------------------


def test_minus_months_clamps_to_month_end():
    assert _minus_months(date(2024, 3, 31), 1) == date(2024, 2, 29)  # leap year
    assert _minus_months(date(2023, 3, 31), 1) == date(2023, 2, 28)


# --- return formula (AC #2) -------------------------------------------------


def test_cumulative_return():
    assert canonical_return(Decimal("110"), Decimal("100"), annualized=False) == Decimal("0.1")


def test_cagr_doubling_over_two_years():
    r = canonical_return(Decimal("200"), Decimal("100"), annualized=True, years=Decimal("2"))
    assert abs(r - (Decimal("2").sqrt() - 1)) < Decimal("0.0001")  # ~41.42%


def test_missing_base_price_is_none():
    assert canonical_return(Decimal("100"), Decimal("0"), annualized=False) is None
    zero = canonical_return(Decimal("100"), Decimal("100"), annualized=True, years=Decimal("0"))
    assert zero is None


def test_period_years():
    # 2022-01-01 -> 2024-01-01 is 730 days (neither 2022 nor 2023 is a leap year)
    assert period_years(date(2024, 1, 1), date(2022, 1, 1)) == Decimal("730") / Decimal("365.25")


def test_window_is_a_frozen_record():
    assert isinstance(WINDOWS[0], Window) and WINDOWS[0].code == "1D"
