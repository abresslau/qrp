"""Tests for the daily maintenance monitor (Story U3.1). DB-free pure logic.

Calendar-alignment snapping is pure (`snap_to_sessions`); the full run_monitor +
idempotency + liveness are verified live against the populated DB.
"""

from __future__ import annotations

from datetime import date

from universe.monitor import snap_to_sessions
from universe.registry import JOIN, MembershipChange


def _chg(d, tok="ticker:A@XNYS"):
    return MembershipChange(tok, JOIN, d, "wikipedia")


def test_snap_to_sessions_aligns_non_trading_days():
    # A Saturday change snaps back to Friday; a session date is unchanged.
    sessions = {date(2024, 3, 9): date(2024, 3, 8), date(2024, 3, 8): date(2024, 3, 8)}
    changes = [_chg(date(2024, 3, 9)), _chg(date(2024, 3, 8))]
    out = snap_to_sessions(changes, lambda d: sessions.get(d))
    assert out[0].effective_date == date(2024, 3, 8)  # snapped
    assert out[1].effective_date == date(2024, 3, 8)  # already a session


def test_snap_leaves_unknown_dates_unchanged():
    changes = [_chg(date(1900, 1, 1))]
    out = snap_to_sessions(changes, lambda d: None)
    assert out[0].effective_date == date(1900, 1, 1)


def test_snap_preserves_other_fields():
    out = snap_to_sessions([_chg(date(2024, 3, 9), "ticker:Z@XNYS")], lambda d: date(2024, 3, 8))
    assert out[0].raw_identifier == "ticker:Z@XNYS" and out[0].change == JOIN
