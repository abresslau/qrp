"""Tests for the historical fundamentals input + figi tokens (Stories U5.1/U5.2). DB-free."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from universe.membership_diff import figi_token

from sym.universe.fundamentals import (
    YFinanceSharesHistorySource,
    dedupe_changes,
)
from sym.universe.resolver import FIGI, _parse_token


def test_figi_token_and_parse_roundtrip():
    tok = figi_token("bbg000b9xry4")
    assert tok == "figi:BBG000B9XRY4"
    assert _parse_token(tok) == (FIGI, "BBG000B9XRY4", None)


def test_dedupe_changes_keeps_first_and_changes_only():
    series = [
        (date(2020, 1, 1), Decimal("100")),
        (date(2020, 2, 1), Decimal("100")),  # unchanged -> dropped
        (date(2020, 3, 1), Decimal("90")),   # change -> kept
        (date(2020, 4, 1), Decimal("90")),   # unchanged -> dropped
        (date(2020, 5, 1), Decimal("110")),  # change -> kept
    ]
    assert dedupe_changes(series) == [
        (date(2020, 1, 1), Decimal("100")),
        (date(2020, 3, 1), Decimal("90")),
        (date(2020, 5, 1), Decimal("110")),
    ]


def test_dedupe_sorts_unordered_input():
    series = [(date(2021, 1, 1), Decimal("5")), (date(2020, 1, 1), Decimal("5"))]
    assert dedupe_changes(series) == [(date(2020, 1, 1), Decimal("5"))]


def test_shares_source_missing_symbol_is_empty_not_faked():
    src = YFinanceSharesHistorySource(symbol_for=lambda figi: None)
    assert src.shares_history("BBG000000000") == []
