"""Tests for the FMP index source (Story U2.1). DB-free (fake FMP client)."""

from __future__ import annotations

from datetime import date

import pytest

from universe.providers.fmp import FmpIndexSource, _mic_for, _parse_fmp_date
from universe.providers.index_source import IndexSourceError
from universe.registry import EXACT, JOIN, LEAVE, POLL_BOUNDED


class _FakeFmp:
    def __init__(self, current, history):
        self._current = current
        self._history = history

    def current_constituents(self, slug):
        return self._current

    def historical_constituents(self, slug):
        return self._history


def test_parse_fmp_date_formats():
    assert _parse_fmp_date("2020-01-02") == date(2020, 1, 2)
    assert _parse_fmp_date("January 2, 2020") == date(2020, 1, 2)
    assert _parse_fmp_date("garbage") is None


def test_mic_mapping():
    assert _mic_for("NASDAQ") == "XNAS"
    assert _mic_for("New York Stock Exchange") == "XNYS"
    assert _mic_for(None) == "XNYS"


def test_current_constituents_emit_poll_bounded_joins():
    src = FmpIndexSource(_FakeFmp([{"symbol": "AAPL", "exchange": "NASDAQ"}], []))
    changes = src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))
    assert len(changes) == 1
    c = changes[0]
    assert c.raw_identifier == "ticker:AAPL@XNAS"
    assert c.change == JOIN and c.effective_date_precision == POLL_BOUNDED


def test_historical_changes_are_exact_dated_join_and_leave():
    history = [
        {"date": "2021-03-15", "symbol": "NEW", "removedTicker": "OLD", "exchange": "NYSE"}
    ]
    src = FmpIndexSource(_FakeFmp([{"symbol": "AAPL", "exchange": "NASDAQ"}], history))
    changes = src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))
    join = next(c for c in changes if c.raw_identifier == "ticker:NEW@XNYS")
    leave = next(c for c in changes if c.raw_identifier == "ticker:OLD@XNYS")
    assert join.change == JOIN and join.effective_date == date(2021, 3, 15)
    assert join.effective_date_precision == EXACT
    assert leave.change == LEAVE and leave.effective_date == date(2021, 3, 15)


def test_history_outside_window_is_filtered():
    history = [{"date": "1999-01-01", "symbol": "OLD", "exchange": "NYSE"}]
    src = FmpIndexSource(_FakeFmp([{"symbol": "AAPL", "exchange": "NASDAQ"}], history))
    changes = src.fetch("sp500", date(2010, 1, 1), date(2024, 6, 1))
    assert all(c.raw_identifier != "ticker:OLD@XNYS" for c in changes)


def test_empty_current_is_loud_error():
    src = FmpIndexSource(_FakeFmp([], []))
    with pytest.raises(IndexSourceError):
        src.fetch("sp500", date(2000, 1, 1), date(2024, 6, 1))


def test_unknown_index_raises():
    src = FmpIndexSource(_FakeFmp([{"symbol": "X"}], []))
    with pytest.raises(IndexSourceError):
        src.fetch("sp400", date(2000, 1, 1), date(2024, 6, 1))
