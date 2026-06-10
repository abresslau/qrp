"""Tests for the append-only membership event log (Story U1.2). DB-free.

Covers append validation (typed errors before any DB call) and the insert-vs-
duplicate return contract via a fake connection. The real dedupe/idempotency
(the DB UNIQUE + ON CONFLICT) and conflicting-date behavior are verified live.
"""

from __future__ import annotations

from datetime import date

import pytest

from sym.universe.events import append_change, append_changes
from sym.universe.registry import (
    InvalidMembershipEventError,
    MembershipChange,
)


def _change(change="join", precision="exact"):
    return MembershipChange(
        raw_identifier="ticker:AAPL@XNAS",  # append_change validates token shape (poison guard)
        change=change,
        effective_date=date(2024, 1, 2),
        source="test",
        effective_date_precision=precision,
    )


class _FakeCursorConn:
    """Records executes and returns a canned fetchone() (a 1-tuple = inserted,
    None = ON CONFLICT no-op)."""

    def __init__(self, inserted: bool):
        self._inserted = inserted
        self.calls = 0

    def execute(self, _sql, _params):
        self.calls += 1
        return self

    def fetchone(self):
        return (1,) if self._inserted else None


class _ExplodingConn:
    """Any DB call is a bug: validation must happen before touching the DB."""

    def execute(self, *_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("append_change must validate before any DB call")


# --- validation (no DB) -----------------------------------------------------


def test_append_invalid_change_kind_raises_before_db():
    with pytest.raises(InvalidMembershipEventError):
        append_change(_ExplodingConn(), "u", _change(change="bogus"))


def test_append_invalid_precision_raises_before_db():
    with pytest.raises(InvalidMembershipEventError):
        append_change(_ExplodingConn(), "u", _change(precision="fuzzy"))


def test_correct_is_a_valid_change_kind():
    conn = _FakeCursorConn(inserted=True)
    assert append_change(conn, "u", _change(change="correct")) is True


# --- insert vs duplicate return contract ------------------------------------


def test_append_returns_true_when_inserted():
    assert append_change(_FakeCursorConn(inserted=True), "u", _change()) is True


def test_append_returns_false_on_conflict():
    # ON CONFLICT DO NOTHING -> RETURNING empty -> fetchone() is None -> False.
    assert append_change(_FakeCursorConn(inserted=False), "u", _change()) is False


def test_append_changes_counts_only_inserted():
    conn = _FakeCursorConn(inserted=True)
    n = append_changes(conn, "u", [_change(), _change(change="leave")])
    assert n == 2 and conn.calls == 2
