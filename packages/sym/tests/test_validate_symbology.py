"""Tests for symbology/name completeness + uniqueness (Story V3). DB-free."""

from __future__ import annotations

from sym.validate.symbology import find_collisions, find_missing


def test_find_missing():
    assert find_missing({"A", "B", "C"}, {"A"}) == {"B", "C"}


def test_no_collision_when_unique():
    rows = [("ticker", "AAPL", "XNAS", "F1"), ("ticker", "MSFT", "XNAS", "F2")]
    assert find_collisions(rows) == {}


def test_cross_exchange_same_ticker_is_not_a_collision():
    # MC on XPAR (LVMH) and MC on XNYS (Moelis) -> different keys -> fine.
    rows = [("ticker", "MC", "XPAR", "F_LVMH"), ("ticker", "MC", "XNYS", "F_MOELIS")]
    assert find_collisions(rows) == {}


def test_true_collision_same_key_two_figis():
    rows = [("ticker", "DUP", "XNAS", "F1"), ("ticker", "DUP", "XNAS", "F2")]
    coll = find_collisions(rows)
    assert coll == {("ticker", "DUP", "XNAS"): {"F1", "F2"}}


def test_isin_collision_null_mic():
    rows = [("isin", "US0000000001", None, "F1"), ("isin", "US0000000001", None, "F2")]
    assert find_collisions(rows) == {("isin", "US0000000001", None): {"F1", "F2"}}
