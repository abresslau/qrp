"""``/api/operate`` — trigger sym ops as guarded background jobs + watch their status.

Status is watched over a Server-Sent Events stream (``/jobs/stream``, Story QH.4): the
server re-reads the job ledger on a short cadence and pushes a frame only when the payload
changes, replacing the console's 2s client polling. ``/jobs`` remains for one-shot reads and
as the stream's graceful fallback.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import psycopg

from operate.db import connect
from operate.gateway import DbOperateGateway, run_history

router = APIRouter(prefix="/api/operate", tags=["operate"])

# Server-side re-read cadence for the SSE stream: brisk while a job is live, slow
# when everything is terminal — the server analogue of the old 2s/6s client poll.
# A keep-alive comment frame on the idle path proves the connection is still live.
_STREAM_ACTIVE_S = 1.0
_STREAM_IDLE_S = 5.0


def _gateway() -> Iterator[DbOperateGateway]:
    conn = connect()  # qrp.job ledger lives in the qrp database
    try:
        yield DbOperateGateway(conn)
    finally:
        conn.close()


class OpDef(BaseModel):
    key: str
    label: str
    writes: bool
    takes_universe: bool
    takes_scope: bool
    note: str


class RunRequest(BaseModel):
    op: str
    args: list[str] = []
    confirm: bool = False


class RunResult(BaseModel):
    ok: bool
    job_id: int | None = None
    status: str
    reason: str | None = None


class Job(BaseModel):
    job_id: int
    op: str
    args: list[str]
    status: str
    exit_code: int | None
    output: str | None
    error: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None


class RunHistoryRow(BaseModel):
    run_id: int
    mode: str
    source: str
    started_at: str | None
    finished_at: str | None
    attempted: int
    loaded: int
    skipped: int
    errored: int
    rows_written: int
    status: str
    triggered_by: str | None


@router.get("/ops", response_model=list[OpDef])
def list_ops(gw: DbOperateGateway = Depends(_gateway)) -> list[dict]:
    return gw.ops()


@router.get("/jobs", response_model=list[Job])
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200), gw: DbOperateGateway = Depends(_gateway)
) -> list[dict]:
    return gw.list(limit)


@router.get("/jobs/stream")
def stream_jobs(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> StreamingResponse:
    """SSE stream of the jobs list (Story QH.4) — replaces the console's 2s polling.

    Declared BEFORE ``/jobs/{job_id}`` so the literal ``stream`` segment isn't captured by
    the int path param (which would 422). A pre-flight reachability check degrades an
    unreachable ledger to the honest 503 envelope BEFORE streaming begins (never a silently
    empty stream); the stream's OWN connection is opened inside the generator so its lifetime
    is bound to that generator's ``try/finally`` and can't leak across the route boundary if
    the response is never iterated. ``X-Accel-Buffering`` + ``Cache-Control: no-cache`` keep
    the event-stream flushing incrementally through the Next.js ``/api`` rewrite proxy.
    """
    try:
        connect().close()  # pre-flight: prove the ledger is reachable, then drop this conn
    except psycopg.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"job ledger unreachable: {exc}") from exc
    return StreamingResponse(
        job_event_stream(request, limit),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: int, gw: DbOperateGateway = Depends(_gateway)) -> dict:
    j = gw.get(job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="job not found")
    return j


async def job_event_stream(request: Request, limit: int) -> AsyncIterator[str]:
    """Yield ``text/event-stream`` frames carrying the jobs list, pushing only on change.

    Opens AND closes its own ledger connection (the close lives in ``finally``, so the
    connection's lifetime is bound entirely to this generator — it cannot leak across the
    route boundary). The job rows (and their heartbeat-derived ``orphaned`` status) come
    from ``DbOperateGateway.list`` verbatim — the same view the polled ``/jobs`` endpoint
    serves. The sync psycopg read runs off the event loop so one slow query can't stall
    other requests. Stops when the client disconnects; a DB error mid-stream ends it cleanly
    (the client reconnects). A connect failure here (a race after the pre-flight) propagates
    as a stream error — no conn is bound, so nothing leaks — and the client reconnects.
    """
    conn = connect()  # the pre-flight in stream_jobs already proved reachability
    gw = DbOperateGateway(conn)
    last: str | None = None
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                jobs = await run_in_threadpool(gw.list, limit)
            except psycopg.Error:
                # Mid-stream DB failure: end cleanly rather than 500 the worker.
                # EventSource reconnects (and re-opens a fresh connection) on its own.
                break
            payload = json.dumps(jobs)
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            else:
                yield ": keepalive\n\n"
            active = any(j["status"] in ("queued", "running") for j in jobs)
            await asyncio.sleep(_STREAM_ACTIVE_S if active else _STREAM_IDLE_S)
    finally:
        conn.close()


@router.get("/history", response_model=list[RunHistoryRow])
def pipeline_history(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    """Recent equity pipeline runs (FR-6) with qrp-job correlation via triggered_by."""
    try:
        conn = connect("equity")  # pipeline_run_log moved to the equity DB
    except psycopg.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"equity database unreachable: {exc}") from exc
    try:
        return run_history(conn, limit)
    except psycopg.Error as exc:
        # Mid-query failures (disconnect, missing column on a pre-migration DB)
        # degrade to the same honest 503, never a raw 500.
        raise HTTPException(status_code=503, detail=f"equity run log unavailable: {exc}") from exc
    finally:
        conn.close()


@router.post("/run", response_model=RunResult)
def run_op(body: RunRequest = Body(...), gw: DbOperateGateway = Depends(_gateway)) -> dict:
    res = gw.run(body.op, body.args, body.confirm)
    if not res["ok"]:
        # Honest status codes: 409 for a lock/duplicate conflict, 422 for validation rejections.
        code = 409 if res["status"] == "conflict" else 422
        raise HTTPException(status_code=code, detail=res["reason"])
    return res
