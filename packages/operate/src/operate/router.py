"""``/api/operate`` — trigger sym ops as guarded background jobs + poll their status."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

import psycopg

from operate.db import connect
from operate.gateway import DbOperateGateway, run_history

router = APIRouter(prefix="/api/operate", tags=["operate"])


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


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: int, gw: DbOperateGateway = Depends(_gateway)) -> dict:
    j = gw.get(job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="job not found")
    return j


@router.get("/history", response_model=list[RunHistoryRow])
def pipeline_history(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    """Recent sym pipeline runs (FR-6) with qrp-job correlation via triggered_by."""
    try:
        conn = connect("sym")
    except psycopg.OperationalError as exc:
        raise HTTPException(status_code=503, detail=f"sym database unreachable: {exc}") from exc
    try:
        return run_history(conn, limit)
    except psycopg.Error as exc:
        # Mid-query failures (disconnect, missing column on a pre-migration DB)
        # degrade to the same honest 503, never a raw 500.
        raise HTTPException(status_code=503, detail=f"sym run log unavailable: {exc}") from exc
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
