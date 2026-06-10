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


def test_arg_validation_symmetry(monkeypatch):
    # No-arg ops must not forward arbitrary positionals; universe ops take
    # EXACTLY one id — the guard applies uniformly, not just to scopes.
    monkeypatch.setattr(gateway_mod, "launch", lambda *a: None)
    gw = DbOperateGateway(_Conn())
    assert gw.run("eod", ["sneaky"], confirm=True)["status"] == "rejected"
    assert gw.run("validate", ["extra"], confirm=False)["status"] == "rejected"
    assert gw.run("universe_accuracy", ["ibov", "more"], confirm=False)["status"] == "rejected"
    assert gw.run("universe_accuracy", ["ibov"], confirm=False)["ok"] is True


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


def test_list_and_get_read_repair_orphans():
    # Storage must converge with the API view: detection during list/get
    # persists status='orphaned' so ad-hoc SQL never sees eternal 'running'.
    conn = _Conn()
    gw = DbOperateGateway(conn)
    gw.list()
    gw.get(1)
    repairs = [sql for sql, _ in conn.calls if "SET status='orphaned'" in sql]
    assert len(repairs) == 2
    assert all("finished_at=now()" in sql for sql in repairs)


def test_stale_window_is_derived_from_beat():
    from operate.executor import _BEAT_S, _STALE_S

    assert _STALE_S == int(_BEAT_S * 3)
    gw = DbOperateGateway(_Conn())
    assert f"{_STALE_S} seconds" in gw._COLS


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
        captured["encoding"] = kw.get("encoding")
        return _FakeProc()

    monkeypatch.setattr(executor_mod, "connect", lambda: conn)
    monkeypatch.setattr(executor_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(executor_mod, "_BEAT_S", 0.01)
    _run_job(7, OPS["validate"], [])

    assert captured["env"]["SYM_TRIGGERED_BY"] == "qrp-job:7"
    assert captured["encoding"] == "utf-8"       # cp1252 default would kill the drain
    beats = [sql for sql, _ in conn.calls if "SET heartbeat_at" in sql]
    assert len(beats) >= 2                       # beat while alive, every cycle
    assert all("now()" in sql for sql, _ in conn.calls if "SET heartbeat_at" in sql)
    final = [p for sql, p in conn.calls if "exit_code" in sql]
    assert final and final[0][0] == "success"    # status param
    assert "line1" in final[0][2]                # output tail captured via drain


def test_beat_failure_does_not_abandon_the_child(monkeypatch):
    # A DB hiccup on one beat must not crash the supervisor — the child keeps
    # being supervised and the final status still lands.
    import psycopg

    class _FlakyConn(_Conn):
        def execute(self, sql, params=None):
            if "SET heartbeat_at" in sql:
                self.calls.append((sql, params))
                raise psycopg.OperationalError("blip")
            return super().execute(sql, params)

    conn = _FlakyConn()
    monkeypatch.setattr(executor_mod, "connect", lambda: conn)
    monkeypatch.setattr(executor_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(executor_mod, "_BEAT_S", 0.01)
    _run_job(9, OPS["validate"], [])
    final = [p for sql, p in conn.calls if "exit_code" in sql]
    assert final and final[0][0] == "success"


def test_run_job_timeout_tree_kills_and_records_output(monkeypatch):
    conn = _Conn()

    class _NeverEnds(_FakeProc):
        def poll(self):
            return None

    proc = _NeverEnds()
    killed = []
    monkeypatch.setattr(executor_mod, "connect", lambda: conn)
    monkeypatch.setattr(executor_mod.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(executor_mod, "_kill_tree", lambda p: killed.append(p))
    monkeypatch.setattr(executor_mod, "_BEAT_S", 0.01)
    monkeypatch.setattr(executor_mod, "_TIMEOUT_S", 0.02)
    _run_job(8, OPS["validate"], [])
    assert killed == [proc]                       # tree-kill, not bare proc.kill
    fails = [p for sql, p in conn.calls if "status='failed'" in sql]
    assert fails and "timed out" in fails[0][0]
    assert "line1" in fails[0][1]                 # output persisted on timeout too


def test_kill_tree_survives_hung_wait(monkeypatch):
    # proc.wait raising TimeoutExpired must not displace the real failure
    # message (constraint 6).
    import subprocess as sp

    class _Hung:
        pid = 12345

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise sp.TimeoutExpired(cmd="x", timeout=timeout)

    monkeypatch.setattr(executor_mod.subprocess, "run", lambda *a, **k: None)
    executor_mod._kill_tree(_Hung())              # must not raise


# --- run history -------------------------------------------------------------------


def test_run_history_maps_rows():
    rows = [(42, "fill", "yfinance", T, T, 10, 9, 1, 0, 4500, "success", "qrp-job:7")]
    out = run_history(_Conn(rows=rows), limit=5)
    assert out[0]["run_id"] == 42
    assert out[0]["triggered_by"] == "qrp-job:7"
    assert out[0]["started_at"] == T.isoformat()


def test_history_endpoint_degrades_to_503_on_query_failure(monkeypatch):
    import psycopg
    import pytest
    from fastapi import HTTPException

    from operate import router as router_mod

    class _BrokenConn(_Conn):
        def execute(self, sql, params=None):
            raise psycopg.errors.UndefinedColumn("triggered_by missing")

    monkeypatch.setattr(router_mod, "connect", lambda db: _BrokenConn())
    with pytest.raises(HTTPException) as exc:
        router_mod.pipeline_history(limit=5)
    assert exc.value.status_code == 503
    assert "run log unavailable" in exc.value.detail
