"""Tests for three-phase load orchestration (Story 2.5). DB-free."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sym.ingest import pipeline
from sym.ingest.pipeline import (
    BACKFILL,
    DELTA,
    OVERWRITE,
    LoadSummary,
    compute_window,
    fetch_with_retry,
    plan_load,
    run_load,
)
from sym.ingest.prices import IngestSummary
from sym.sources.contract import OhlcvResult

FIXED = datetime(2026, 6, 6, tzinfo=UTC)
FLOOR = date(1990, 1, 1)
END = date(2024, 12, 31)


# --- compute_window ---------------------------------------------------------


def test_backfill_window_is_full_from_floor():
    assert compute_window(BACKFILL, None, floor=FLOOR, end_date=END) == (FLOOR, END)


def test_delta_window_starts_after_cursor():
    assert compute_window(DELTA, date(2024, 1, 1), floor=FLOOR, end_date=END) == (date(2024, 1, 2), END)


def test_delta_without_cursor_is_full():
    assert compute_window(DELTA, None, floor=FLOOR, end_date=END) == (FLOOR, END)


def test_up_to_date_security_is_skipped():
    # cursor at (or past) the latest session -> delta is a no-op.
    assert compute_window(DELTA, END, floor=FLOOR, end_date=END) is None
    # Backfill is gap-aware: a current cursor only skips once the floor was reached
    # (else there may be unfetched history below the earliest stored bar).
    assert compute_window(BACKFILL, END, floor=FLOOR, end_date=END, floor_reached=FLOOR) is None
    # ...but a current cursor with no recorded floor still re-fetches to fill below.
    assert compute_window(BACKFILL, END, floor=FLOOR, end_date=END) == (FLOOR, END)


def test_no_sessions_means_skip():
    assert compute_window(BACKFILL, None, floor=FLOOR, end_date=None) is None


# --- plan_load (the unified `sym load` flag -> mode mapping, Story 2.11) -----


def test_plan_load_no_window_is_delta():
    assert plan_load(start_date=None, overwrite=False) == DELTA


def test_plan_load_explicit_start_is_backfill():
    assert plan_load(start_date=date(2020, 1, 1), overwrite=False) == BACKFILL


def test_plan_load_overwrite_is_overwrite():
    assert plan_load(start_date=date(2020, 1, 1), overwrite=True) == OVERWRITE


def test_plan_load_overwrite_takes_precedence_over_start():
    # overwrite wins regardless of start_date presence (the CLI separately requires
    # --start_date with --overwrite, but the mapping itself is overwrite-first).
    assert plan_load(start_date=None, overwrite=True) == OVERWRITE


# --- fetch_with_retry -------------------------------------------------------


class _FlakySource:
    SOURCE = "fake"

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0

    def fetch_ohlcv(self, figi, start, end):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("429 rate limited")
        return OhlcvResult(figi=figi, currency="USD", bars=[], source="fake", retrieved_at=FIXED)


def test_fetch_retries_then_succeeds():
    slept = []
    src = _FlakySource(fail_times=2)
    result = fetch_with_retry(src, "F", FLOOR, END, retries=3, sleep=slept.append)
    assert result.figi == "F" and src.calls == 3 and len(slept) == 2


def test_fetch_exhausts_then_raises():
    slept = []
    src = _FlakySource(fail_times=99)
    with pytest.raises(RuntimeError):
        fetch_with_retry(src, "F", FLOOR, END, retries=3, sleep=slept.append)
    assert src.calls == 3


# --- run_load ---------------------------------------------------------------


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
        if "RETURNING" in sql.upper():  # pipeline_run_log insert returns run_id
            return _Cur((1,))
        return _Cur()

    def sql_for(self, needle):
        return [s for s, _ in self.calls if needle in s.upper()]


class _Source:
    SOURCE = "fake"

    def __init__(self, fail_figis=()):
        self.fail = set(fail_figis)
        self.fetched = []

    def fetch_ohlcv(self, figi, start, end):
        self.fetched.append((figi, start, end))
        if figi in self.fail:
            raise RuntimeError("boom")
        return OhlcvResult(figi=figi, currency="USD", bars=[], source="fake", retrieved_at=FIXED)


@pytest.fixture
def stub_db(monkeypatch):
    """Stub the DB-touching helpers so run_load's control flow is tested in isolation."""
    monkeypatch.setattr(pipeline, "latest_session_for", lambda conn, mic, as_of_date: END)
    monkeypatch.setattr(pipeline, "expected_trading_days", lambda conn, mic, s, e: set())
    monkeypatch.setattr(
        pipeline, "ingest_result",
        lambda conn, result, expected_sessions=None: IngestSummary(
            figi=result.figi, source=result.source, bars_written=5
        ),
    )


def _set_universe(monkeypatch, securities):
    monkeypatch.setattr(pipeline, "read_active_with_cursor", lambda conn: securities)


def test_delta_skips_up_to_date_and_windows_from_cursor(stub_db, monkeypatch):
    _set_universe(monkeypatch, [
        ("F1", "XNAS", None),               # never loaded -> full
        ("F2", "XNAS", date(2024, 1, 1)),   # behind -> window from cursor+1
        ("F3", "XNAS", END),                # up-to-date -> skip
    ])
    conn = _Conn()
    src = _Source()
    summary = run_load(conn, src, DELTA, as_of_date=date(2026, 6, 6), sleep=lambda d: None)
    assert (summary.loaded, summary.skipped, summary.attempted) == (2, 1, 3)
    assert conn.autocommit is True  # per-figi durable commits (Story 2.4 finding)
    fetched = dict((f, (s, e)) for f, s, e in src.fetched)
    assert "F3" not in fetched  # up-to-date never fetched
    assert fetched["F2"][0] == date(2024, 1, 2)  # delta window from cursor, not the clock
    # a run-level log row is written (FR-8), success since nothing errored
    assert summary.status == "success" and summary.run_id == 1
    assert conn.sql_for("INSERT INTO PIPELINE_RUN_LOG")


def test_one_failing_figi_is_isolated(stub_db, monkeypatch):
    _set_universe(monkeypatch, [
        ("F1", "XNAS", None), ("F2", "XNAS", None), ("F3", "XNAS", None),
    ])
    conn = _Conn()
    summary = run_load(conn, _Source(fail_figis={"F2"}), BACKFILL, as_of_date=date(2026, 6, 6),
                       sleep=lambda d: None)
    assert (summary.loaded, summary.errored) == (2, 1)
    assert summary.errors[0][0] == "F2"
    # F2 marked error (cursor NOT advanced) without halting the run
    assert any("'error'" in sql or "ERROR" in sql.upper() for sql, _ in conn.calls)
    # the run is logged as partial (FR-8: >=1 figi errored)
    assert summary.status == "partial"
    assert conn.sql_for("INSERT INTO PIPELINE_RUN_LOG")


def test_summary_is_returned():
    assert isinstance(LoadSummary(mode="delta"), LoadSummary)


def test_load_summary_status():
    assert LoadSummary(mode="delta").status == "success"
    assert LoadSummary(mode="delta", errored=2).status == "partial"


def test_write_run_log_records_the_run():
    from datetime import UTC, datetime

    from sym.ingest.pipeline import _write_run_log

    conn = _Conn()
    summary = LoadSummary(mode="backfill", attempted=3, loaded=2, errored=1, rows=500,
                          errors=[("F2", "boom")])
    t0 = datetime(2026, 6, 6, 9, 0, tzinfo=UTC)
    run_id = _write_run_log(conn, summary, source="yfinance", started_at=t0, finished_at=t0)
    assert run_id == 1
    sql, params = conn.calls[-1]
    assert "INSERT INTO PIPELINE_RUN_LOG" in sql.upper()
    assert "partial" in params  # status derived from errored>0
