"""Tests for membership tokens + snapshot set-diff (Epic U2/U3). DB-free."""

from __future__ import annotations

from datetime import date

from universe.membership_diff import (
    diff_identifier_sets,
    isin_token,
    normalize_ticker,
    ticker_token,
)
from universe.registry import JOIN, LEAVE, POLL_BOUNDED


def test_normalize_ticker_unifies_separators():
    assert normalize_ticker("brk-b") == "BRK.B"
    assert normalize_ticker("BRK.B") == "BRK.B"
    assert normalize_ticker(" brk b ") == "BRK.B"


def test_token_builders():
    assert ticker_token("brk-b", "xnys") == "ticker:BRK.B@XNYS"
    assert isin_token("us0378331005") == "isin:US0378331005"


def test_diff_emits_joins_and_leaves():
    prev = {"ticker:A@XNYS", "ticker:B@XNYS"}
    curr = {"ticker:B@XNYS", "ticker:C@XNYS"}
    changes = diff_identifier_sets(prev, curr, date(2024, 3, 1), "etf_holdings")
    by_change = {(c.raw_identifier, c.change) for c in changes}
    assert ("ticker:C@XNYS", JOIN) in by_change
    assert ("ticker:A@XNYS", LEAVE) in by_change
    assert ("ticker:B@XNYS", JOIN) not in by_change  # unchanged membership
    assert all(c.effective_date_precision == POLL_BOUNDED for c in changes)


def test_diff_no_change_when_only_weights_move():
    same = {"ticker:A@XNYS", "ticker:B@XNYS"}
    assert diff_identifier_sets(same, set(same), date(2024, 3, 1), "etf_holdings") == []
