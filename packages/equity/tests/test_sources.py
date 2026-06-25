"""Tests for the source-abstraction contract + yfinance adapter (Story 2.2).

Network-free: the yfinance ``history`` call is injected as a fake pandas frame and
``retrieved_at`` uses an injected clock, so the adapter is exercised without Yahoo.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from equity.sources import (
    DividendEvent,
    OhlcvBar,
    OhlcvResult,
    SplitEvent,
    UnknownSourceError,
    UnknownSymbolError,
    UnsupportedSourceError,
    actions_agree,
    assert_ohlcv_contract,
    cumulative_split_factor,
    get_source,
    register_source,
)
from equity.sources.contract import ContractViolation
from equity.sources.yfinance_adapter import YFinanceSource, parse_history

FIXED_NOW = datetime(2026, 6, 6, tzinfo=UTC)


def _aapl_frame():
    """A tiny yfinance-shaped history: a 4:1 split, a dividend, and an Adj Close
    that differs from Close (to prove the raw Close is used)."""
    idx = pd.to_datetime(["2020-08-28", "2020-08-31", "2020-11-06"])
    return pd.DataFrame(
        {
            "Open": [124.0, 31.0, 118.0],
            "High": [125.0, 31.5, 119.0],
            "Low": [123.0, 30.5, 117.0],
            "Close": [124.8, 31.2, 118.5],  # RAW
            "Adj Close": [123.0, 31.0, 117.9],  # different -> must be ignored
            "Volume": [1000, 2000, 1500],
            "Dividends": [0.0, 0.0, 0.205],
            "Stock Splits": [0.0, 4.0, 0.0],
        },
        index=idx,
    )


def _yf(**kwargs):
    return YFinanceSource(
        symbol_for=kwargs.pop("symbol_for", lambda figi: "AAPL"),
        history=kwargs.pop("history", lambda s, st, e: _aapl_frame()),
        currency_for=kwargs.pop("currency_for", lambda s: "USD"),
        clock=kwargs.pop("clock", lambda: FIXED_NOW),
    )


# --- OhlcvResult invariants (AC #1) -----------------------------------------


def test_result_defaults_actions_to_empty_lists():
    r = OhlcvResult(
        figi="BBG000B9XRY4", currency="USD", bars=[], source="x", retrieved_at=FIXED_NOW
    )
    assert r.splits == [] and r.dividends == []  # missing = [] not None


def test_result_rejects_none_action_lists():
    with pytest.raises(ValueError):
        OhlcvResult(
            figi="X", currency="USD", bars=[], source="x", retrieved_at=FIXED_NOW, splits=None
        )


# --- yfinance adapter (AC #1, #3) -------------------------------------------


def test_adapter_unadjusts_yahoo_split_adjusted_prices_to_raw():
    # Yahoo's Close is split-adjusted; the adapter must un-adjust to the real
    # traded price using the explicit 4:1 split, and ignore Adj Close entirely.
    result = _yf().fetch_ohlcv("BBG000B9XRY4", date(2020, 1, 1), date(2021, 1, 1))
    pre_split, split_day, post_split = result.bars
    assert pre_split.close == Decimal("499.2")  # 124.8 * 4, NOT 124.8 and NOT Adj 123.0
    assert pre_split.volume == 250  # 1000 / 4
    assert split_day.close == Decimal("31.2")  # factor 1 on/after the ex-date
    assert post_split.close == Decimal("118.5")
    assert isinstance(pre_split.close, Decimal)
    assert result.source == "yfinance" and result.currency == "USD"
    assert result.retrieved_at == FIXED_NOW
    assert_ohlcv_contract(result)


def test_adapter_normalizes_pence_to_pounds():
    # Yahoo quotes UK stocks in pence (GBp); the adapter normalizes to GBP.
    flat = pd.DataFrame(
        {
            "Open": [650.0], "High": [650.0], "Low": [650.0], "Close": [650.0],
            "Adj Close": [640.0], "Volume": [10], "Dividends": [6.5], "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    src = YFinanceSource(
        symbol_for=lambda f: "HSBA.L", history=lambda s, st, e: flat,
        currency_for=lambda s: "GBp", clock=lambda: FIXED_NOW,
    )
    result = src.fetch_ohlcv("BBG000BS1MT4", date(2024, 1, 1), date(2024, 12, 31))
    assert result.currency == "GBP"
    assert result.bars[0].close == Decimal("6.5")  # 650 pence -> 6.50 GBP
    assert result.dividends[0].amount == Decimal("0.065")  # 6.5 pence -> 0.065 GBP


def test_adapter_extracts_explicit_split_and_dividend():
    result = _yf().fetch_ohlcv("BBG000B9XRY4", date(2020, 1, 1), date(2021, 1, 1))
    assert result.splits == [SplitEvent(date(2020, 8, 31), Decimal("4.0"))]
    assert result.dividends == [DividendEvent(date(2020, 11, 6), Decimal("0.205"))]


def test_adapter_no_actions_yields_empty_lists():
    flat = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [10.0],
            "Low": [10.0],
            "Close": [10.0],
            "Volume": [1],
            "Dividends": [0.0],
            "Stock Splits": [0.0],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )
    bars, splits, dividends = parse_history(flat)
    assert splits == [] and dividends == [] and len(bars) == 1


def test_adapter_raises_on_unresolvable_symbol():
    source = _yf(symbol_for=lambda figi: None)
    with pytest.raises(UnknownSymbolError):
        source.fetch_ohlcv("BBG000NOPE", date(2020, 1, 1), date(2021, 1, 1))


# --- registry (AC #2) -------------------------------------------------------


def test_registry_selects_yfinance_by_key():
    source = get_source("yfinance", symbol_for=lambda figi: "AAPL")
    assert isinstance(source, YFinanceSource)


def test_registry_unknown_key_raises():
    with pytest.raises(UnknownSourceError):
        get_source("not-a-source")


def test_registry_adjusted_only_source_is_rejected():
    register_source("fake_adjusted_only", lambda **kw: object(), adjusted_only=True)
    with pytest.raises(UnsupportedSourceError):
        get_source("fake_adjusted_only")


# --- factor derivation + cross-vendor comparison (AC #3, #4) ----------------


def test_cumulative_split_factor_from_explicit_splits_only():
    splits = [
        SplitEvent(date(2014, 6, 9), Decimal("7")),
        SplitEvent(date(2020, 8, 31), Decimal("4")),
    ]
    assert cumulative_split_factor(splits, date(2010, 1, 1)) == Decimal("28")  # before both
    assert cumulative_split_factor(splits, date(2015, 1, 1)) == Decimal("4")  # between
    assert cumulative_split_factor(splits, date(2021, 1, 1)) == Decimal("1")  # after both


def _result(splits=(), dividends=()):
    return OhlcvResult(
        figi="X", currency="USD", bars=[], source="v", retrieved_at=FIXED_NOW,
        splits=list(splits), dividends=list(dividends),
    )


def test_actions_agree_within_tolerance():
    a = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.2050"))],
    )
    b = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.2052"))],  # within $0.005
    )
    assert actions_agree(a, b) is True


def test_actions_disagree_on_split_ratio_or_dividend_or_exdate():
    base = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.205"))],
    )
    wrong_ratio = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("2"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.205"))],
    )
    big_div_gap = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.25"))],  # way off
    )
    wrong_exdate = _result(
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 7), Decimal("0.205"))],  # ex-date off
    )
    assert actions_agree(base, wrong_ratio) is False
    assert actions_agree(base, big_div_gap) is False
    assert actions_agree(base, wrong_exdate) is False


def test_assert_ohlcv_contract_rejects_duplicate_ex_dates():
    bad = _result(
        dividends=[
            DividendEvent(date(2020, 11, 6), Decimal("0.2")),
            DividendEvent(date(2020, 11, 6), Decimal("0.3")),
        ]
    )
    bad = OhlcvResult(
        figi="X", currency="USD",
        bars=[OhlcvBar(date(2020, 1, 2), *([Decimal("1")] * 4), 1)],
        source="v", retrieved_at=FIXED_NOW, dividends=bad.dividends,
    )
    with pytest.raises(ContractViolation):  # real exception, not assert (python -O safe)
        assert_ohlcv_contract(bad)
