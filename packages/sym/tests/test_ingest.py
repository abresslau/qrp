"""Tests for atomic raw-price + factor ingestion (Story 2.3). DB-free (fake conn)."""

from __future__ import annotations

import contextlib
from datetime import UTC, date, datetime
from decimal import Decimal

from sym.ingest.prices import (
    IngestSummary,
    detect_gaps,
    ingest_result,
    validate_bar,
)
from sym.sources.contract import DividendEvent, OhlcvBar, OhlcvResult, SplitEvent

FIXED = datetime(2026, 6, 6, tzinfo=UTC)


def _bar(d, o=10, h=11, low=9, c=10, v=100):
    return OhlcvBar(d, Decimal(str(o)), Decimal(str(h)), Decimal(str(low)), Decimal(str(c)), v)


def _result(bars, splits=(), dividends=(), figi="BBG000B9XRY4", source="yfinance"):
    return OhlcvResult(
        figi=figi, currency="USD", bars=list(bars), source=source, retrieved_at=FIXED,
        splits=list(splits), dividends=list(dividends),
    )


class _Cursor:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.transactions = 0

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        # Model INSERT ... RETURNING: a fresh fake DB never conflicts, so every insert lands.
        if "INSERT" in sql.upper() and "RETURNING" in sql.upper():
            return _Cursor(("x",))
        return _Cursor()

    def transaction(self):
        self.transactions += 1
        return contextlib.nullcontext()

    def sql_for(self, needle):
        return [sql for sql, _ in self.calls if needle in sql.upper()]


# --- validate_bar -----------------------------------------------------------


def test_validate_bar_accepts_well_formed():
    assert validate_bar(_bar(date(2024, 1, 2))) == (True, None)


def test_validate_bar_rejects_corruption():
    assert validate_bar(_bar(date(2024, 1, 2), c=-1))[0] is False  # non-positive
    assert validate_bar(_bar(date(2024, 1, 2), h=8, low=9))[0] is False  # high < low
    assert validate_bar(_bar(date(2024, 1, 2), o=99))[0] is False  # open above high
    assert validate_bar(_bar(date(2024, 1, 2), v=-5))[0] is False  # negative volume


# --- detect_gaps ------------------------------------------------------------


def test_detect_gaps_returns_expected_minus_actual():
    expected = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)}
    actual = {date(2024, 1, 2), date(2024, 1, 4)}
    assert detect_gaps(expected, actual) == [date(2024, 1, 3)]


def test_detect_gaps_ignores_pre_listing_sessions():
    # Exchange open since 2024-01-02 but the security's first bar is 2024-01-04:
    # the 2nd/3rd are pre-listing, NOT gaps. Only the interior 2024-01-08 counts.
    expected = {date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9)}
    actual = {date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 9)}
    assert detect_gaps(expected, actual) == [date(2024, 1, 8)]


def test_detect_gaps_empty_window_yields_nothing():
    # No bars returned for the window -> cannot tell "not listed" from "outage";
    # emit nothing rather than flag every session (the pre-IPO phantom-gap bug).
    expected = {date(2024, 1, 2), date(2024, 1, 3)}
    assert detect_gaps(expected, set()) == []


# --- ingest_result ----------------------------------------------------------


def test_ingest_writes_prices_actions_and_cursor_in_one_transaction():
    conn = _FakeConn()
    result = _result(
        [_bar(date(2020, 8, 28)), _bar(date(2020, 8, 31))],
        splits=[SplitEvent(date(2020, 8, 31), Decimal("4"))],
        dividends=[DividendEvent(date(2020, 11, 6), Decimal("0.205"))],
    )
    summary = ingest_result(conn, result)
    assert conn.transactions == 1  # one transaction per figi (NFR-6)
    assert summary.bars_written == 2
    assert summary.actions_written == 2
    assert summary.cursor_date == date(2020, 8, 31)
    assert len(conn.sql_for("INSERT INTO PRICES_RAW")) == 2
    assert len(conn.sql_for("INSERT INTO CORPORATE_ACTIONS")) == 2
    assert conn.sql_for("PIPELINE_BACKFILL_PROGRESS")  # cursor advanced atomically


def test_ingest_excludes_and_flags_invalid_bar():
    conn = _FakeConn()
    result = _result([_bar(date(2024, 1, 2)), _bar(date(2024, 1, 3), c=-1)])  # one corrupt
    summary = ingest_result(conn, result)
    assert summary.bars_written == 1  # corrupt bar excluded, not written
    assert summary.rejected and summary.rejected[0][0] == date(2024, 1, 3)
    assert len(conn.sql_for("INSERT INTO PRICES_RAW")) == 1


def test_ingest_records_gaps_never_fills():
    conn = _FakeConn()
    result = _result([_bar(date(2024, 1, 2)), _bar(date(2024, 1, 4))])
    expected = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)}
    summary = ingest_result(conn, result, expected_sessions=expected)
    assert summary.gaps == [date(2024, 1, 3)]
    assert len(conn.sql_for("INSERT INTO PRICE_GAPS")) == 1  # logged, not forward-filled
    assert summary.bars_written == 2  # only real bars, no synthetic fill


def test_ingest_is_immutable_on_conflict_do_nothing():
    conn = _FakeConn()
    ingest_result(conn, _result([_bar(date(2024, 1, 2))],
                                splits=[SplitEvent(date(2024, 1, 2), Decimal("2"))]))
    for needle in ("INSERT INTO PRICES_RAW", "INSERT INTO CORPORATE_ACTIONS"):
        sql = conn.sql_for(needle)[0]
        assert "ON CONFLICT" in sql and "DO NOTHING" in sql  # AR-10 immutable re-run


def test_ingest_stores_no_adjusted_close():
    conn = _FakeConn()
    ingest_result(conn, _result([_bar(date(2024, 1, 2))]))
    all_sql = " ".join(sql.upper() for sql, _ in conn.calls)
    assert "ADJ" not in all_sql  # never a vendor adjusted close (FR-5/AR-7)


def test_ingest_summary_cursor_none_when_no_valid_bars():
    conn = _FakeConn()
    summary = ingest_result(conn, _result([]))
    assert isinstance(summary, IngestSummary)
    assert summary.cursor_date is None and summary.bars_written == 0
