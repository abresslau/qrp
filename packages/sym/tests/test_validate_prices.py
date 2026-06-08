"""Tests for price/calendar/lifecycle consistency (Story V4). DB-free pure logic."""

from __future__ import annotations

from datetime import date

from sym.validate.prices import classify_unpriced, off_calendar


def test_off_calendar_finds_non_sessions():
    prices = {date(2024, 3, 8), date(2024, 3, 9)}  # 9th = Saturday
    sessions = {date(2024, 3, 8)}
    assert off_calendar(prices, sessions) == {date(2024, 3, 9)}


def test_off_calendar_clean():
    s = {date(2024, 3, 8)}
    assert off_calendar(set(s), set(s)) == set()


def test_unpriced_delisted_is_warn():
    assert classify_unpriced("delisted", True)[0] == "warn"
    assert classify_unpriced("suspended", True)[0] == "warn"


def test_unpriced_no_calendar_is_warn():
    sev, reason = classify_unpriced("active", False)
    assert sev == "warn" and "calendar" in reason


def test_unpriced_active_priceable_is_fail():
    sev, reason = classify_unpriced("active", True)
    assert sev == "fail" and "priceable" in reason
