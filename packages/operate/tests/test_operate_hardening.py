"""Operate hardening (Story O.2): heartbeat, orphan classification, provenance,
allowlist, history. DB-free."""

from __future__ import annotations

from datetime import datetime, timezone

from operate import executor as executor_mod
from operate import gateway as gateway_mod
from operate.executor import OPS, _run_job
from operate.gateway import DbOperateGateway, run_history

T = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    autocommit = False

    def __init__(self, rows=None):
        self.calls: list[tuple[str, tuple]] = []
        self._rows = rows or []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return _Cur(one=(True,))
        if "INSERT INTO qrp.job" in sql:
            return _Cur(one=(1,))
        if "count(*)" in sql:
            return _Cur(one=(0,))
        return _Cur(rows=self._rows, one=(self._rows[0],) if self._rows else None)

    def close(self):
        pass


# --- allowlist -------------------------------------------------------------------


def test_new_ops_present_with_correct_flags():
    assert OPS["eod"].writes is True
    assert OPS["fx_load"].writes is True and OPS["fx_load"].argv == ("fx", "load")
    assert OPS["load_fill"].takes_scope is True and OPS["load_fill"].writes is True
    assert OPS["universe_review"].writes is False
    assert OPS["universe_accuracy"].takes_universe is True
    assert OPS["universe_accuracy"].writes is False


def test_scope_arg_validated(monkeypatch):
    monkeypatch.setattr(gateway_mod, "launch", lambda *a: None)
    gw = DbOperateGateway(_Conn())
    assert gw.run("load_fill", [], confirm=True)["status"] == "rejected"
    assert gw.run("load_fill", ["ibov"], confirm=True)["status"] == "rejected"
    assert gw.run("load_fill", ["universe:ibov", "x"], confirm=True)["status"] == "rejected"
    ok = gw.run("load_fill", ["universe:ibov"], confirm=True)
    assert ok["ok"] is True


# --- orphan classification --------------------------------------------------------


def test_listing_sql_reclassifies_stale_running_as_orphaned():
    gw = DbOperateGateway(_Conn())
    assert "orphaned" in gw._COLS
    assert "heartbeat_at" in gw._COLS


def test_busy_check_ignores_stale_running(monkeypatch):
    # The busy predicate must demand a FRESH heartbeat for running rows — a dead
    # supervisor's row no longer blocks a re-run (its advisory lock died with it).
    monkeypatch.setattr(gateway_mod, "launch", lambda *a: None)
    conn = _Conn()
    gw = DbOperateGateway(conn)
    gw.run("validate", [], confirm=False)
    busy_sql = next(sql for sql, _ in conn.calls if "count(*)" in sql)
    assert "heartbeat_at" in busy_sql and "30 seconds" in busy_sql


def test_row_maps_heartbeat():
    gw = DbOperateGateway(_Conn())
    row = gw._row((1, "validate", [], "running", None, None, None, T, T, None, T))
    assert row["heartbeat_at"] == T.isoformat()


# --- executor heartbeat + provenance ----------------------------------------------


class _FakeProc:
    """Stays alive for two polls, then exits 0."""

    def __init__(self):
        self._polls = 0
        import io

        self.stdout = io.StringIO("line1\nline2\n")

    def poll(self):
        self._polls += 1
        return None if self._polls < 3 else 0


def test_run_job_heartbeats_and_injects_provenance(monkeypatch):
    conn = _Conn()
    captured = {}

    def fake_popen(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env") or {}
        return _FakeProc()

    monkeypatch.setattr(executor_mod, "connect", lambda: conn)
    monkeypatch.setattr(executor_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(executor_mod, "_BEAT_S", 0.01)
    _run_job(7, OPS["validate"], [])

    assert captured["env"]["SYM_TRIGGERED_BY"] == "qrp-job:7"
    beats = [sql for sql, _ in conn.calls if "SET heartbeat_at" in sql]
    assert len(beats) >= 2                       # beat while alive, every cycle
    final = [p for sql, p in conn.calls if "exit_code" in sql]
    assert final and final[0][0] == "success"    # status param
    assert "line1" in final[0][2]                # output tail captured via drain


def test_run_job_timeout_kills_and_fails(monkeypatch):
    conn = _Conn()

    class _NeverEnds(_FakeProc):
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    proc = _NeverEnds()
    monkeypatch.setattr(executor_mod, "connect", lambda: conn)
    monkeypatch.setattr(executor_mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(executor_mod, "_BEAT_S", 0.01)
    monkeypatch.setattr(executor_mod, "_TIMEOUT_S", 0.02)
    _run_job(8, OPS["validate"], [])
    assert proc.killed
    fails = [p for sql, p in conn.calls if "status='failed'" in sql]
    assert fails and "timed out" in fails[0][0]


# --- run history -------------------------------------------------------------------


def test_run_history_maps_rows():
    rows = [(42, "fill", "yfinance", T, T, 10, 9, 1, 0, 4500, "success", "qrp-job:7")]
    out = run_history(_Conn(rows=rows), limit=5)
    assert out[0]["run_id"] == 42
    assert out[0]["triggered_by"] == "qrp-job:7"
    assert out[0]["started_at"] == T.isoformat()
