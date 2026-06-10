"""Tests for stage-1 price-anomaly annotation (Story 2.4). DB-free."""

from __future__ import annotations

import contextlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from sym.ingest.anomaly import (
    PRICE_JUMP,
    PRICE_ON_NON_TRADING_DAY,
    detect_anomalies,
)
from sym.ingest.prices import ingest_result, resolve_review
from sym.sources.contract import OhlcvBar, OhlcvResult, SplitEvent

FIXED = datetime(2026, 6, 6, tzinfo=UTC)
D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def _bar(d, close):
    p = Decimal(str(close))
    return OhlcvBar(d, p, p, p, p, 100)


def _result(bars, splits=(), figi="BBG000B9XRY4"):
    return OhlcvResult(
        figi=figi, currency="USD", bars=list(bars), source="yfinance",
        retrieved_at=FIXED, splits=list(splits),
    )


class _Cursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, update_row=("BBG000B9XRY4",)):
        self.calls: list[tuple[str, tuple]] = []
        self._update_row = update_row

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "count(*)" in sql:
            return _Cursor((1,))   # one open flag: the ambiguity guard passes
        if sql.upper().lstrip().startswith("UPDATE"):
            return _Cursor(self._update_row)
        # Model INSERT ... RETURNING: a fresh fake DB never conflicts, so every insert lands.
        if "INSERT" in sql.upper() and "RETURNING" in sql.upper():
            return _Cursor(("x",))
        return _Cursor()

    def transaction(self):
        return contextlib.nullcontext()

    def sql_for(self, needle):
        return [s for s, _ in self.calls if needle in s.upper()]


# --- detect_anomalies -------------------------------------------------------


def test_detects_split_adjusted_jump():
    flags = detect_anomalies([_bar(D1, 100), _bar(D2, 200)], splits=[])
    assert len(flags) == 1
    assert flags[0].flag_type == PRICE_JUMP and flags[0].session_date == D2
    assert flags[0].pct_move == Decimal(1)  # +100%


def test_pure_split_drop_is_not_flagged():
    # 4:1 split on D2: raw drops 400 -> 100 (-75%), but split-adjusted it's flat.
    flags = detect_anomalies([_bar(D1, 400), _bar(D2, 100)], splits=[SplitEvent(D2, Decimal("4"))])
    assert flags == []  # corporate action, not an anomaly


def test_flags_price_on_non_trading_day():
    flags = detect_anomalies([_bar(D1, 100), _bar(D2, 101)], splits=[], expected_sessions={D1})
    assert len(flags) == 1
    assert flags[0].flag_type == PRICE_ON_NON_TRADING_DAY and flags[0].session_date == D2


def test_clean_series_has_no_flags():
    flags = detect_anomalies(
        [_bar(D1, 100), _bar(D2, 101), _bar(D3, 102)], splits=[], expected_sessions={D1, D2, D3}
    )
    assert flags == []


# --- ingest_result integration ----------------------------------------------


def test_ingest_annotates_jump_while_price_still_lands():
    conn = _FakeConn()
    summary = ingest_result(conn, _result([_bar(D1, 100), _bar(D2, 200)]))
    # the suspect price is NOT discarded — both bars written
    assert len(conn.sql_for("INSERT INTO PRICES_RAW")) == 2
    assert summary.bars_written == 2
    # and the flag is written, idempotently, without clobbering a human review
    flag_sql = conn.sql_for("INSERT INTO PRICES_REVIEW")
    assert len(flag_sql) == 1
    assert "ON CONFLICT" in flag_sql[0] and "NOT PRICES_REVIEW.REVIEWED" in flag_sql[0].upper()
    assert len(summary.flags) == 1 and summary.flags[0].flag_type == PRICE_JUMP


def test_ingest_clean_data_writes_no_flag():
    conn = _FakeConn()
    summary = ingest_result(conn, _result([_bar(D1, 100), _bar(D2, 101)]))
    assert summary.flags == []
    assert conn.sql_for("INSERT INTO PRICES_REVIEW") == []


# --- resolve_review ---------------------------------------------------------


def test_resolve_review_marks_reviewed():
    conn = _FakeConn()
    # S.1: the no-flag_type default first counts open flags (ambiguity guard);
    # the fake's single-row answer means count=1 -> proceed.
    assert resolve_review(conn, "BBG000B9XRY4", D2, resolution="confirmed") is True
    sql, params = conn.calls[-1]
    assert "UPDATE PRICES_REVIEW" in sql.upper() and "REVIEWED = TRUE" in sql.upper()
    assert params[0] == "confirmed"


def test_resolve_review_rejects_bad_resolution():
    conn = _FakeConn()
    with pytest.raises(ValueError):
        resolve_review(conn, "BBG000B9XRY4", D2, resolution="maybe")
