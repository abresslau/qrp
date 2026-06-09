"""DB-free tests for the explicit-range reload window logic (Story 2.10)."""

from __future__ import annotations

from datetime import date

from sym.ingest.pipeline import DELTA, RELOAD, compute_window

FLOOR = date(1990, 1, 1)


def test_reload_window_is_explicit_and_cursor_independent():
    end = date(2026, 6, 9)
    # cursor is already current (delta would skip) — reload re-fetches the window anyway
    w = compute_window(RELOAD, date(2026, 6, 9), floor=FLOOR, end_date=end, reload_start_date=date(2026, 6, 1))
    assert w == (date(2026, 6, 1), end)


def test_reload_returns_start_to_end_session():
    w = compute_window(RELOAD, None, floor=FLOOR, end_date=date(2026, 6, 5), reload_start_date=date(2026, 6, 1))
    assert w == (date(2026, 6, 1), date(2026, 6, 5))


def test_reload_skips_when_start_after_end():
    assert (
        compute_window(RELOAD, None, floor=FLOOR, end_date=date(2026, 6, 1), reload_start_date=date(2026, 6, 9))
        is None
    )


def test_reload_skips_when_no_session():
    assert compute_window(RELOAD, None, floor=FLOOR, end_date=None, reload_start_date=date(2026, 6, 1)) is None


def test_reload_requires_reload_start():
    assert compute_window(RELOAD, None, floor=FLOOR, end_date=date(2026, 6, 9), reload_start_date=None) is None


def test_delta_ignores_reload_start():
    end = date(2026, 6, 9)
    w = compute_window(DELTA, date(2026, 6, 5), floor=FLOOR, end_date=end, reload_start_date=date(2020, 1, 1))
    assert w == (date(2026, 6, 6), end)  # still cursor+1, reload_start ignored
