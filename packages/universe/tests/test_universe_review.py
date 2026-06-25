"""Tests for the universe review digest (Story U3.4). DB-free pure formatting.

Digest assembly + confirm/reject are verified live.
"""

from __future__ import annotations

from datetime import date, datetime

from universe.review import Digest, format_digest


def test_clear_digest():
    assert "all clear" in format_digest(Digest())


def test_digest_is_clear_property():
    assert Digest().is_clear
    assert not Digest(stale_monitors=[("sp500", None)]).is_clear


def test_format_lists_each_section():
    d = Digest(
        pending_changes=[
            {
                "proposal_id": 7,
                "universe_id": "sp500",
                "change": "leave",
                "raw_identifier": "ticker:X@XNYS",
                "effective_date": date(2024, 3, 1),
                "reason": "churn_threshold",
                "seen_count": 1,
            }
        ],
        stale_monitors=[("sp400", None)],
        aging_unresolved=[{"universe_id": "sp600", "unresolved": 12, "oldest": date(2026, 1, 1)}],
        accuracy_alarms=[
            {
                "universe_id": "sp500",
                "divergence": 0.42,
                "threshold": 0.05,
                "reference_source": "etf_holdings:test",
            }
        ],
    )
    out = format_digest(d)
    assert "[7] sp500 leave ticker:X@XNYS" in out
    assert "churn_threshold" in out
    assert "sp400: last success never" in out
    assert "sp600: 12 unresolved" in out
    assert "divergence 0.420" in out
    assert not d.is_clear


def test_format_handles_datetime_last_success():
    d = Digest(stale_monitors=[("sp500", datetime(2026, 6, 1, 12, 0))])
    assert "sp500: last success 2026-06-01" in format_digest(d)
