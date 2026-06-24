"""Tests for the ETF-holdings index source (Story U2.2). DB-free (fake client)."""

from __future__ import annotations

from datetime import date

import pytest

from universe.providers.etf_holdings import (
    EtfHoldingsIndexSource,
    parse_equity_tokens,
    parse_holdings_csv,
)
from universe.providers.index_source import IndexSourceError
from universe.registry import JOIN, POLL_BOUNDED


class _FakeEtf:
    def __init__(self, rows):
        self._rows = rows

    def holdings(self, etf_key):
        return self._rows


def test_non_equity_rows_are_dropped():
    rows = [
        {"asset_class": "Equity", "isin": "DE0007164600", "ticker": "SAP"},
        {"asset_class": "Cash", "ticker": "EUR"},
        {"asset_class": "Futures", "ticker": "FESX"},
    ]
    tokens = parse_equity_tokens(rows)
    assert tokens == {"isin:DE0007164600"}


def test_isin_preferred_then_ticker():
    rows = [
        {"asset_class": "Equity", "isin": "DE0007164600"},
        {"asset_class": "Equity", "ticker": "BAS", "mic": "XETR"},
    ]
    tokens = parse_equity_tokens(rows, default_mic="XETR")
    assert tokens == {"isin:DE0007164600", "ticker:BAS@XETR"}


def test_parse_holdings_csv_skips_issuer_preamble():
    text = (
        "iShares Core DAX UCITS ETF\n"
        "Fund Holdings as of 01-Jun-2024\n"
        "Ticker,Name,ISIN,Asset Class,Weight (%)\n"
        "SAP,SAP SE,DE0007164600,Equity,10.5\n"
        "EUR,Euro Cash,,Cash,0.2\n"
    )
    rows = parse_holdings_csv(text)
    tokens = parse_equity_tokens(rows)
    assert tokens == {"isin:DE0007164600"}


def test_source_emits_poll_bounded_joins_with_proxy_source():
    rows = [{"asset_class": "Equity", "isin": "DE0007164600"}]
    src = EtfHoldingsIndexSource(_FakeEtf(rows), {"dax": "ishares_dax"})
    changes = src.fetch("dax", date(2000, 1, 1), date(2024, 6, 1))
    assert len(changes) == 1
    c = changes[0]
    assert c.change == JOIN and c.effective_date == date(2024, 6, 1)
    assert c.effective_date_precision == POLL_BOUNDED
    assert c.source == "etf_holdings:ishares_dax"


def test_empty_parse_is_loud_error_not_all_left():
    src = EtfHoldingsIndexSource(_FakeEtf([{"asset_class": "Cash"}]), {"dax": "ishares_dax"})
    with pytest.raises(IndexSourceError):
        src.fetch("dax", date(2000, 1, 1), date(2024, 6, 1))


def test_unconfigured_index_raises():
    src = EtfHoldingsIndexSource(_FakeEtf([]), {})
    with pytest.raises(IndexSourceError):
        src.fetch("dax", date(2000, 1, 1), date(2024, 6, 1))
