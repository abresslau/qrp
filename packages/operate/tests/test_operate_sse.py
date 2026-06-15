"""Operate SSE job stream (Story QH.4): event-stream framing, change-vs-keepalive,
client-disconnect teardown, mid-stream degrade, and 503-on-open. DB-free.

The async generator is driven directly with ``asyncio.run`` — the operate suite has no
async test plumbing and needs none: a fake Request flips ``is_disconnected`` after N polls
to bound the loop, and the stream cadence is monkeypatched to zero so it runs instantly.
"""

from __future__ import annotations

import asyncio
import json

import psycopg
import pytest
from fastapi import HTTPException

from operate import router as router_mod
from operate.router import job_event_stream

# A job row as gateway._row expects it: 11-tuple, timestamps may be None.
#   (job_id, op, args, status, exit_code, output, error, created, started, finished, heartbeat)
_RUNNING = (1, "eod", [], "running", None, None, None, None, None, None, None)
_DONE = (1, "eod", [], "success", 0, "ok", None, None, None, None, None)


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _SeqConn:
    """Returns a different SELECT result per ``list()`` call, advancing through ``batches``.

    The orphan-repair UPDATE that ``gateway.list`` fires first is a no-op here; only the
    SELECT advances the batch pointer (and the last batch repeats once exhausted).
    """

    def __init__(self, batches, fail_after=None):
        self.autocommit = False
        self._batches = batches
        self._i = 0
        self._selects = 0
        self._fail_after = fail_after
        self.closed = False

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("SELECT"):
            self._selects += 1
            if self._fail_after is not None and self._selects > self._fail_after:
                raise psycopg.OperationalError("mid-stream blip")
            batch = self._batches[min(self._i, len(self._batches) - 1)]
            self._i += 1
            return _Cur(batch)
        return _Cur([])  # the orphan-repair UPDATE

    def close(self):
        self.closed = True


def _use_conn(monkeypatch, conn):
    """Route the generator's internal ``connect()`` to a fake conn."""
    monkeypatch.setattr(router_mod, "connect", lambda *a, **k: conn)


class _Req:
    """Reports connected for the first ``alive`` polls, then disconnected (bounds the loop)."""

    def __init__(self, alive=2):
        self._alive = alive
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > self._alive


async def _drain(gen):
    return [frame async for frame in gen]


def _run(req, limit=25):
    # The generator opens its own connection via the (monkeypatched) connect().
    return asyncio.run(_drain(job_event_stream(req, limit)))


@pytest.fixture(autouse=True)
def _instant_cadence(monkeypatch):
    # No real waiting between frames — the loop is bounded by the fake Request.
    monkeypatch.setattr(router_mod, "_STREAM_ACTIVE_S", 0)
    monkeypatch.setattr(router_mod, "_STREAM_IDLE_S", 0)


def test_stream_frames_are_well_formed_event_stream(monkeypatch):
    # First frame is always a data event carrying the gateway's job rows as JSON.
    _use_conn(monkeypatch, _SeqConn([[_RUNNING]]))
    frames = _run(_Req(alive=1))
    assert len(frames) == 1
    assert frames[0].startswith("data: ") and frames[0].endswith("\n\n")
    payload = json.loads(frames[0][len("data: ") :].strip())
    assert payload[0]["job_id"] == 1
    assert payload[0]["op"] == "eod"
    assert payload[0]["status"] == "running"  # heartbeat-derived view, unchanged


def test_unchanged_payload_emits_keepalive_not_a_duplicate(monkeypatch):
    # Same rows twice → one data frame then a keepalive comment (no duplicate push).
    _use_conn(monkeypatch, _SeqConn([[_RUNNING], [_RUNNING]]))
    frames = _run(_Req(alive=2))
    assert len(frames) == 2
    assert frames[0].startswith("data: ")
    assert frames[1] == ": keepalive\n\n"


def test_changed_payload_emits_a_new_data_frame(monkeypatch):
    # running → success across polls → two distinct data frames.
    _use_conn(monkeypatch, _SeqConn([[_RUNNING], [_DONE]]))
    frames = _run(_Req(alive=2))
    assert len(frames) == 2
    assert all(f.startswith("data: ") for f in frames)
    assert json.loads(frames[0][6:].strip())[0]["status"] == "running"
    assert json.loads(frames[1][6:].strip())[0]["status"] == "success"


def test_stops_and_closes_connection_on_client_disconnect(monkeypatch):
    conn = _SeqConn([[_RUNNING]])
    _use_conn(monkeypatch, conn)
    frames = _run(_Req(alive=0))  # disconnected on the very first poll
    assert frames == []
    assert conn.closed is True  # finally: conn.close() ran


def test_connection_closed_after_normal_drain(monkeypatch):
    conn = _SeqConn([[_DONE]])
    _use_conn(monkeypatch, conn)
    _run(_Req(alive=1))
    assert conn.closed is True


def test_mid_stream_db_error_ends_cleanly_and_closes(monkeypatch):
    # SELECT succeeds once, then raises: the stream ends (no exception escapes) and the
    # connection is still closed. The client's EventSource reconnects on its own.
    conn = _SeqConn([[_RUNNING]], fail_after=1)
    _use_conn(monkeypatch, conn)
    frames = _run(_Req(alive=5))
    assert len(frames) == 1  # the one good frame before the blip
    assert conn.closed is True


def test_preflight_returns_stream_and_drops_its_probe_connection(monkeypatch):
    # A reachable ledger: stream_jobs returns a text/event-stream response and the
    # short-lived pre-flight probe connection is closed (the stream opens its own).
    from fastapi.responses import StreamingResponse

    probe = _SeqConn([[_DONE]])
    _use_conn(monkeypatch, probe)
    resp = router_mod.stream_jobs(_Req(), limit=5)
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"
    assert probe.closed is True  # connect().close() ran in the pre-flight


def test_stream_open_degrades_to_503_when_ledger_unreachable(monkeypatch):
    def _boom(*_a, **_k):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(router_mod, "connect", _boom)
    with pytest.raises(HTTPException) as exc:
        router_mod.stream_jobs(_Req(), limit=5)
    assert exc.value.status_code == 503
    assert "job ledger unreachable" in exc.value.detail
