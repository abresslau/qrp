"""Tests for the criteria provider (Story U5.2). DB-free where possible."""

from __future__ import annotations

from datetime import date

import pytest

from sym.universe.providers.criteria import CriteriaProvider, _top_n_market_cap
from sym.universe.registry import CRITERIA, JOIN, is_registered


class _FakeConn:
    """Minimal conn stub returning the canned ranked figis for the screen query."""

    def __init__(self, ranked):
        self._ranked = ranked

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return [(f,) for f in self._ranked]


def test_criteria_is_registered():
    import sym.universe.providers  # noqa: F401

    assert is_registered(CRITERIA)


def test_requires_conn():
    with pytest.raises(ValueError):
        CriteriaProvider(conn=None)


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        CriteriaProvider(conn=_FakeConn([]), rule="nope")


def test_top_n_market_cap_ranks_screen():
    conn = _FakeConn(["BBG000000001", "BBG000000002"])
    figis = _top_n_market_cap(conn, date(2024, 6, 1), 2)
    assert figis == ["BBG000000001", "BBG000000002"]


def test_provider_emits_figi_join_events():
    conn = _FakeConn(["BBG000000001", "BBG000000002"])
    prov = CriteriaProvider(conn=conn, rule="top_n_market_cap", n=2)
    changes = list(prov.members(date(2020, 1, 1), date(2024, 6, 1)))
    assert [c.raw_identifier for c in changes] == ["figi:BBG000000001", "figi:BBG000000002"]
    assert all(c.change == JOIN and c.effective_date == date(2024, 6, 1) for c in changes)


def test_empty_screen_yields_nothing():
    figis = _top_n_market_cap(_FakeConn([]), date(2024, 6, 1), 10)
    assert figis == []
