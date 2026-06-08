"""``/api/operate`` — trigger sym ops as guarded background jobs + poll their status."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from qrp_api.db import connect
from qrp_api.modules.operate.gateway import DbOperateGateway

router = APIRouter(prefix="/api/operate", tags=["operate"])


def _gateway() -> Iterator[DbOperateGateway]:
    conn = connect()
    try:
        yield DbOperateGateway(conn)
    finally:
        conn.close()


class OpDef(BaseModel):
    key: str
    label: str
    writes: bool
    takes_universe: bool
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


@router.post("/run", response_model=RunResult)
def run_op(body: RunRequest = Body(...), gw: DbOperateGateway = Depends(_gateway)) -> dict:
    return gw.run(body.op, body.args, body.confirm)
