"""Tests for the weekly re-fetch sweep + immutability (Story 2.8). DB-free."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sym.ingest import pipeline
from sym.ingest.pipeline import detect_divergences, run_sweep
from sym.sources.contract import OhlcvBar, OhlcvResult

FIXED = datetime(2026, 6, 6, tzinfo=UTC)


def _bar(d, close):
    p = Decimal(str(close))
    return OhlcvBar(d, p, p, p, p, 100)


# --- detect_divergences -----------------------------------------------------


def test_faithful_refetch_has_no_divergence():
    stored = {date(2026, 5, 1): Decimal("100"), date(2026, 5, 2): Decimal("101")}
    bars = [_bar(date(2026, 5, 1), 100), _bar(date(2026, 5, 2), 101)]
    assert detect_divergences(stored, bars) == []


def test_source_correction_is_flagged():
    stored = {date(2026, 5, 1): Decimal("100")}
    bars = [_bar(date(2026, 5, 1), 105)]  # source retroactively changed 100 -> 105
    divs = detect_divergences(stored, bars)
    assert len(divs) == 1
    ex_date, stored_close, fetched_close, _rel = divs[0]
    assert ex_date == date(2026, 5, 1)
    assert (stored_close, fetched_close) == (Decimal("100"), Decimal("105"))


def test_new_date_is_not_a_divergence():
    stored = {date(2026, 5, 1): Decimal("100")}
    bars = [_bar(date(2026, 5, 1), 100), _bar(date(2026, 5, 2), 102)]  # 5/2 is new
    assert detect_divergences(stored, bars) == []


def test_tiny_difference_within_tolerance_is_ignored():
    stored = {date(2026, 5, 1): Decimal("100.00")}
    bars = [_bar(date(2026, 5, 1), "100.01")]  # 0.01% < 0.1% tolerance
    assert detect_divergences(stored, bars) == []


# --- run_sweep --------------------------------------------------------------


class _Cur:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.autocommit = False
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "RETURNING" in sql.upper():
            return _Cur((7,))
        return _Cur()

    def sql_for(self, needle):
        return [s for s, _ in self.calls if needle in s.upper()]


class _Source:
    SOURCE = "fake"

    def __init__(self, bars):
        self._bars = bars

    def fetch_ohlcv(self, figi, start, end):
        return OhlcvResult(figi=figi, currency="USD", bars=self._bars, source="fake",
                           retrieved_at=FIXED)


def test_run_sweep_flags_divergence_without_overwriting(monkeypatch):
    monkeypatch.setattr(pipeline, "read_active_with_cursor", lambda conn: [("F1", "XNAS", None)])
    monkeypatch.setattr(
        pipeline, "_read_stored_closes",
        lambda conn, figi, s, e: {date(2026, 5, 1): Decimal("100")},
    )
    conn = _Conn()
    src = _Source([_bar(date(2026, 5, 1), 110)])  # 10% correction
    summary = run_sweep(conn, src, as_of_date=date(2026, 6, 6), sleep=lambda d: None)

    assert summary.mode == "sweep" and summary.flags == 1 and summary.run_id == 7
    assert conn.autocommit is True
    # divergence recorded as a review flag; the price itself is never updated
    assert conn.sql_for("INSERT INTO PRICES_REVIEW")
    assert conn.sql_for("INSERT INTO PIPELINE_RUN_LOG")  # run logged (mode=sweep)
    assert not any("UPDATE PRICES_RAW" in s.upper() for s, _ in conn.calls)


# --- immutability (AC #1) ---------------------------------------------------


def test_no_in_place_overwrite_of_prices_raw():
    """No code path may overwrite a stored raw price (AR-10 immutability)."""
    src = Path(__file__).resolve().parents[1] / "src" / "sym"
    overwrite = re.compile(r"update\s+prices_raw", re.IGNORECASE)
    offenders = [
        py.name for py in src.rglob("*.py")
        if overwrite.search(py.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"in-place overwrite of prices_raw found in: {offenders}"
