"""DB-free tests for the explicit-range overwrite window logic (Story 2.10)."""

from __future__ import annotations

from datetime import date

from sym.ingest.pipeline import DELTA, OVERWRITE, compute_window

FLOOR = date(1990, 1, 1)


def test_overwrite_window_is_explicit_and_cursor_independent():
    end = date(2026, 6, 9)
    # cursor is already current (delta would skip) — overwrite re-fetches the window anyway
    w = compute_window(
        OVERWRITE, date(2026, 6, 9), floor=FLOOR, end_date=end,
        overwrite_start_date=date(2026, 6, 1),
    )
    assert w == (date(2026, 6, 1), end)


def test_overwrite_returns_start_to_end_session():
    w = compute_window(
        OVERWRITE, None, floor=FLOOR, end_date=date(2026, 6, 5),
        overwrite_start_date=date(2026, 6, 1),
    )
    assert w == (date(2026, 6, 1), date(2026, 6, 5))


def test_overwrite_skips_when_start_after_end():
    w = compute_window(
        OVERWRITE, None, floor=FLOOR, end_date=date(2026, 6, 1),
        overwrite_start_date=date(2026, 6, 9),
    )
    assert w is None


def test_overwrite_skips_when_no_session():
    w = compute_window(
        OVERWRITE, None, floor=FLOOR, end_date=None, overwrite_start_date=date(2026, 6, 1),
    )
    assert w is None


def test_overwrite_requires_overwrite_start():
    w = compute_window(
        OVERWRITE, None, floor=FLOOR, end_date=date(2026, 6, 9), overwrite_start_date=None,
    )
    assert w is None


def test_delta_ignores_overwrite_start():
    end = date(2026, 6, 9)
    w = compute_window(
        DELTA, date(2026, 6, 5), floor=FLOOR, end_date=end,
        overwrite_start_date=date(2020, 1, 1),
    )
    assert w == (date(2026, 6, 6), end)  # still cursor+1, overwrite_start ignored
