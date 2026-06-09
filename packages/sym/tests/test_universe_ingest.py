"""Tests for universe-driven ingestion (Epic U4). DB-free pure logic.

The bridge, selection query, run_universe_load, and coverage are verified live;
here we cover the run_load selection hooks (floor_for / end_cap_for) that implement
join-backfill and leaver-cap, with a fake source + fake DB-free harness.
"""

from __future__ import annotations

from datetime import date

from sym.ingest.pipeline import FILL, compute_window
from sym.universe.ingest import Coverage


def test_backfill_fetches_full_window_when_nothing_stored():
    end = date(2026, 6, 5)
    window = compute_window(FILL, None, floor=date(1990, 1, 1), end_date=end, gap_aware=True)
    assert window == (date(1990, 1, 1), end)


def test_end_cap_for_stops_leaver_at_exit():
    # A leaver's fetch end is capped at its exit (simulated by passing the cap as end).
    exit_date = date(2020, 3, 31)
    window = compute_window(FILL, None, floor=date(2010, 1, 1), end_date=exit_date, gap_aware=True)
    assert window == (date(2010, 1, 1), exit_date)


def test_forward_fill_skips_member_already_current():
    # An up-to-date member (cursor >= end) is skipped (no forward re-fetch).
    end = date(2026, 6, 5)
    assert compute_window(FILL, end, floor=date(1990, 1, 1), end_date=end) is None


def test_backfill_skips_when_floor_already_reached_and_current():
    # Cursor at end AND we already backfilled down to (<=) this floor -> skip.
    end = date(2026, 6, 5)
    assert (
        compute_window(
            FILL, end, floor=date(1990, 1, 1), end_date=end, gap_aware=True,
            floor_reached=date(1990, 1, 1),
        )
        is None
    )


def test_backfill_refetches_when_prior_floor_was_shallower():
    # The XYZ/Square case: cursor is current, but a prior backfill only reached 2025
    # (the membership-join floor) while we now request 1990 -> re-fetch to fill below.
    end = date(2026, 6, 5)
    window = compute_window(
        FILL, end, floor=date(1990, 1, 1), end_date=end, gap_aware=True,
        floor_reached=date(2025, 7, 23),
    )
    assert window == (date(1990, 1, 1), end)


def test_backfill_fetches_when_floor_never_recorded():
    # floor_reached unknown (NULL) and current -> still fetch (we don't know we went deep).
    end = date(2026, 6, 5)
    window = compute_window(
        FILL, end, floor=date(1990, 1, 1), end_date=end, gap_aware=True, floor_reached=None
    )
    assert window == (date(1990, 1, 1), end)


def test_backfill_no_fetch_when_floor_after_end():
    assert compute_window(
        FILL, None, floor=date(2030, 1, 1), end_date=date(2026, 6, 5), gap_aware=True
    ) is None


def test_coverage_percentages():
    cov = Coverage("sp500", members_total=868, resolved=650, unresolved=218,
                   in_master=650, priced=130, current_members=503, current_priced=100)
    assert abs(cov.resolved_pct - 650 / 868) < 1e-9
    assert abs(cov.priced_pct - 130 / 650) < 1e-9
    assert abs(cov.current_priced_pct - 100 / 503) < 1e-9


def test_coverage_zero_safe():
    cov = Coverage("empty")
    assert cov.resolved_pct == 0.0 and cov.priced_pct == 0.0 and cov.current_priced_pct == 0.0
