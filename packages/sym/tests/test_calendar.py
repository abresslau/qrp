"""Tests for the trading-calendar snapshot loader (Story 2.1).

DB-free: a fake CalendarSource stands in for exchange_calendars and a fake
connection (with a minimal cursor().copy()) stands in for psycopg. The real bulk
load is exercised in live verification, matching the suite's DB-free convention.
"""

from __future__ import annotations

import contextlib
from datetime import date

import psycopg

from sym.calendar.snapshot import (
    EMPTY,
    NEW,
    UNCHANGED,
    UNKNOWN_MIC,
    ExchangeCalendarsSource,
    apply_snapshot,
    content_hash,
    plan_snapshot,
    snapshot_calendars,
)

D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


class _FakeSource:
    def __init__(self, mapping, library_version="4.13.2"):
        self._mapping = mapping  # mic -> list[date]; absent key => unknown MIC (None)
        self._lib = library_version

    @property
    def library_version(self):
        return self._lib

    def sessions(self, mic, start, end):
        return self._mapping.get(mic)


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Copy:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write_row(self, row):
        self._sink.append(row)


class _CopyCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def copy(self, sql):
        self._conn.copy_sql = sql
        return _Copy(self._conn.copied_rows)


class _FakeConn:
    """Routes the snapshot loader's statements; records flips and COPYed rows."""

    def __init__(self, current=None, start_version=10, fail_insert=False):
        self._current = current or {}  # mic -> content_hash (currently-effective)
        self.calls: list[tuple[str, tuple]] = []
        self.copied_rows: list[tuple] = []
        self.copy_sql = None
        self.flipped: list[str] = []
        self._next = start_version
        self._fail_insert = fail_insert

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        upper = sql.upper()
        if "UPDATE TRADING_CALENDAR_VERSION" in upper and "IS_CURRENT = FALSE" in upper:
            self.flipped.append(params[0])
            return _Cur([])
        if upper.lstrip().startswith("INSERT") and "TRADING_CALENDAR_VERSION" in upper:
            if self._fail_insert:
                raise psycopg.Error("simulated insert failure")
            version = self._next
            self._next += 1
            return _Cur([(version,)])
        if "SELECT MIC, CONTENT_HASH" in upper:
            return _Cur(list(self._current.items()))
        return _Cur([])

    def cursor(self):
        return _CopyCursor(self)

    def transaction(self):
        return contextlib.nullcontext()


# --- content_hash -----------------------------------------------------------


def test_content_hash_is_deterministic():
    assert content_hash("4.13.2", [D1, D2, D3]) == content_hash("4.13.2", [D1, D2, D3])


def test_content_hash_changes_with_sessions_or_library():
    base = content_hash("4.13.2", [D1, D2, D3])
    assert content_hash("4.13.2", [D1, D2]) != base  # a dropped session
    assert content_hash("4.13.3", [D1, D2, D3]) != base  # a library bump


# --- plan_snapshot ----------------------------------------------------------


def test_plan_classifies_new_unchanged_unknown_and_empty():
    src = _FakeSource({"XNYS": [D1, D2, D3], "XPAR": [D1, D2], "XEMPTY": []})
    # XNYS already at the current hash -> unchanged; XPAR has no current -> new;
    # XEMPTY -> empty; XBAD absent from source -> unknown.
    current = {"XNYS": content_hash("4.13.2", [D1, D2, D3])}
    plans = {
        p.mic: p
        for p in plan_snapshot(
            src, ["XNYS", "XPAR", "XEMPTY", "XBAD"],
            start=date(1990, 1, 1), end=date(2024, 12, 31), current_hashes=current,
        )
    }
    assert plans["XNYS"].outcome == UNCHANGED
    assert plans["XPAR"].outcome == NEW
    assert plans["XPAR"].sessions == (D1, D2)
    assert plans["XEMPTY"].outcome == EMPTY
    assert plans["XBAD"].outcome == UNKNOWN_MIC


# --- apply_snapshot ---------------------------------------------------------


def test_apply_new_flips_prior_then_copies_sessions():
    src = _FakeSource({"XPAR": [D1, D2, D3]})
    plans = plan_snapshot(
        src, ["XPAR"], start=date(1990, 1, 1), end=date(2024, 12, 31), current_hashes={}
    )
    conn = _FakeConn(start_version=10)
    summary = apply_snapshot(conn, plans)
    assert summary.versions_written == 1
    assert summary.sessions_written == 3
    assert conn.flipped == ["XPAR"]  # prior current version superseded
    # sessions COPYed under the version id returned by the INSERT
    assert conn.copied_rows == [(10, "XPAR", D1), (10, "XPAR", D2), (10, "XPAR", D3)]
    assert "COPY trading_calendar" in conn.copy_sql


def test_apply_counts_unchanged_unknown_empty_without_writing():
    src = _FakeSource({"XNYS": [D1, D2], "XEMPTY": []})
    current = {"XNYS": content_hash("4.13.2", [D1, D2])}
    plans = plan_snapshot(
        src, ["XNYS", "XEMPTY", "XBAD"],
        start=date(1990, 1, 1), end=date(2024, 12, 31), current_hashes=current,
    )
    conn = _FakeConn()
    summary = apply_snapshot(conn, plans)
    assert (summary.unchanged, summary.empty, summary.unknown_mic) == (1, 1, 1)
    assert summary.versions_written == 0
    assert summary.unknown_mics == ["XBAD"]
    assert conn.copied_rows == []


def test_apply_isolates_a_failing_mic():
    src = _FakeSource({"XPAR": [D1, D2]})
    plans = plan_snapshot(
        src, ["XPAR"], start=date(1990, 1, 1), end=date(2024, 12, 31), current_hashes={}
    )
    conn = _FakeConn(fail_insert=True)
    summary = apply_snapshot(conn, plans)
    assert summary.failed == 1
    assert summary.versions_written == 0


# --- snapshot_calendars (orchestrator) --------------------------------------


# --- ExchangeCalendarsSource (real library; deterministic, no network) ------


def test_exchange_calendars_source_honours_requested_start_and_unknown_mic():
    src = ExchangeCalendarsSource()
    # Regression guard: the library defaults to ~20y of history; we must get 1990.
    sessions = src.sessions("XNYS", date(1990, 1, 1), date(2024, 12, 31))
    assert sessions[0] <= date(1990, 1, 3)
    assert date(2024, 1, 2) in sessions  # a known NYSE session
    assert date(2024, 1, 1) not in sessions  # New Year's Day
    # A MIC the library doesn't know is reported as unknown, never raised.
    assert src.sessions("XNSE", date(1990, 1, 1), date(2024, 12, 31)) is None


def test_exchange_calendars_source_relaxes_a_hard_end_bound():
    # XBOM holidays are only recorded to 2026; requesting through 2027 must NOT
    # raise -- the source relaxes the end bound and still returns sessions.
    src = ExchangeCalendarsSource()
    sessions = src.sessions("XBOM", date(1990, 1, 1), date(2027, 12, 31))
    assert sessions is not None and len(sessions) > 0


def test_exchange_calendars_source_extends_to_calendar_bound_min():
    # XTKS (Tokyo) supports back to ~1997 in exchange_calendars; the source must
    # reach the calendar's true bound_min, NOT stop at the 20-year default (~2006).
    src = ExchangeCalendarsSource()
    sessions = src.sessions("XTKS", date(1990, 1, 1), date(2024, 12, 31))
    assert sessions[0].year <= 1997  # would be ~2006 before the bound-clamp fix


def test_snapshot_calendars_is_idempotent_on_second_run():
    src = _FakeSource({"XPAR": [D1, D2, D3]})
    # Simulate the row already present at the matching hash -> unchanged, no write.
    conn = _FakeConn(current={"XPAR": content_hash("4.13.2", [D1, D2, D3])})
    summary = snapshot_calendars(conn, src, ["XPAR"], end=date(2024, 12, 31))
    assert summary.unchanged == 1
    assert summary.versions_written == 0
    assert conn.copied_rows == []
