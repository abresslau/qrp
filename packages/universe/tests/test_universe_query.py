"""Tests for the as-of membership query API (Story U1.5). DB-free.

`assert_within_pit` is pure; `members` + set-ops are exercised via a fake conn
that returns canned pit/membership rows. The as-of SQL select and the
fact_returns join are verified live.
"""

from __future__ import annotations

from datetime import date

import pytest

from universe.query import (
    assert_within_pit,
    members,
    members_in_a_not_b,
    members_overlap,
    members_union,
)
from universe.registry import PitBoundaryError, UnknownUniverseError

D = date(2020, 1, 1)


class _FakeConn:
    """Returns canned pit_valid_from and membership sets keyed by universe_id.

    A universe absent from ``pit`` is treated as unknown. ``members`` ignores the
    as-of filter (the SQL date predicate is verified live); these tests exercise
    the guardrail + set-op composition.
    """

    def __init__(self, pit: dict[str, date | None], members: dict[str, set[str]]):
        self._pit = pit
        self._members = members
        self._last: tuple[str, tuple] = ("", ())

    def execute(self, sql, params):
        self._last = (sql, params)
        return self

    def fetchone(self):
        sql, params = self._last
        uid = params[0]
        if "pit_valid_from" in sql:
            return (self._pit[uid],) if uid in self._pit else None
        return None

    def fetchall(self):
        _sql, params = self._last
        return [(f,) for f in sorted(self._members.get(params[0], set()))]


# --- assert_within_pit (pure) -----------------------------------------------


def test_pit_none_allows_any_date():
    assert_within_pit(date(1990, 1, 1), None)  # no boundary -> no raise


def test_as_of_on_or_after_pit_is_allowed():
    assert_within_pit(date(2020, 1, 1), date(2020, 1, 1))
    assert_within_pit(date(2025, 1, 1), date(2020, 1, 1))


def test_as_of_before_pit_raises():
    with pytest.raises(PitBoundaryError):
        assert_within_pit(date(2019, 12, 31), date(2020, 1, 1))


# --- members + guardrail ----------------------------------------------------


def test_members_returns_the_set():
    conn = _FakeConn({"a": None}, {"a": {"BBG1", "BBG2"}})
    assert members(conn, "a", D) == {"BBG1", "BBG2"}


def test_members_refuses_before_pit():
    conn = _FakeConn({"a": date(2021, 1, 1)}, {"a": {"BBG1"}})
    with pytest.raises(PitBoundaryError):
        members(conn, "a", date(2020, 1, 1))


def test_members_unknown_universe_raises():
    conn = _FakeConn({}, {})
    with pytest.raises(UnknownUniverseError):
        members(conn, "nope", D)


# --- set operations ---------------------------------------------------------


def _two_universe_conn():
    return _FakeConn(
        {"a": None, "b": None},
        {"a": {"BBG1", "BBG2", "BBG3"}, "b": {"BBG3", "BBG4"}},
    )


def test_overlap_is_intersection():
    assert members_overlap(_two_universe_conn(), "a", "b", D) == {"BBG3"}


def test_in_a_not_b_is_difference():
    assert members_in_a_not_b(_two_universe_conn(), "a", "b", D) == {"BBG1", "BBG2"}


def test_union_is_all():
    assert members_union(_two_universe_conn(), "a", "b", D) == {"BBG1", "BBG2", "BBG3", "BBG4"}
