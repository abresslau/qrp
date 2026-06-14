"""Tests for macro.market_sources (yfinance commodities/indices) — no network."""

from __future__ import annotations

from datetime import date

import macro.market_sources as ms
from macro.market_sources import fetch_yfinance


def test_fetch_yfinance_scales_dedupes_and_skips_nan(monkeypatch):
    raw = [
        (date(2026, 1, 2), 100.0),
        (date(2026, 1, 3), float("nan")),  # NaN bar -> skipped, never faked
        (date(2026, 1, 3), 102.0),         # duplicate date, later value wins
        (date(2026, 1, 6), 104.0),
    ]
    monkeypatch.setattr(ms, "_history", lambda ticker, start: raw)
    meta, obs = fetch_yfinance("BZ=F", "MKT:BRENT", "Brent", "USD/bbl", "Global", scale=0.5)
    assert meta["source"] == "market"
    assert meta["frequency"] == "daily"
    assert obs == [(date(2026, 1, 2), 50.0), (date(2026, 1, 3), 51.0), (date(2026, 1, 6), 52.0)]


def test_fetch_yfinance_empty_history_is_no_data(monkeypatch):
    monkeypatch.setattr(ms, "_history", lambda ticker, start: [])
    meta, obs = fetch_yfinance("ZZZ", "MKT:ZZZ", "x", "u", "Global")
    assert obs == []  # caller's no-data rule drops it, never fabricated
