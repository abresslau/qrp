"""``/api/data-monitor`` router — the Data Monitor area's read endpoints.

v1 has one page (EOD): per-bucket expected-vs-actual business date + best-effort latest Dagster
run, plus a warehouse-summary header (migrated from the retired sym Overview).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from lineage.buckets import bucket_keys, job_name
from pydantic import BaseModel

from qrp_api.config import dagster_run_url
from qrp_api.db import connect
from qrp_api.modules.data_monitor.dagster_runs import launch_job
from qrp_api.modules.data_monitor.eod import EodMonitorGateway

router = APIRouter(prefix="/api/data-monitor", tags=["data-monitor"])


def _gateway() -> Iterator[EodMonitorGateway]:
    conn = connect()
    try:
        yield EodMonitorGateway(conn)
    finally:
        conn.close()


# ---- response models (typed seam: OpenAPI -> generated TS types carry real shapes) ----
class EodRun(BaseModel):
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    source: str | None = None


class EodSubgroup(BaseModel):
    group: str
    as_of_date: str | None = None
    days_behind: int | None = None
    detail: str | None = None


class EodBucketRow(BaseModel):
    key: str
    label: str
    subcategory: str
    datasets: list[str]
    cadence: str
    note: str | None = None
    actual_date: str | None = None
    expected_date: str | None = None
    days_behind: int | None = None
    status: str  # ok | stale | unknown
    coverage: str | None = None
    instrument_count: int | None = None  # distinct entities active in the recent trailing window
    instrument_label: str | None = None  # unit for the count (pairs/names/series/commodities/…)
    error: str | None = None
    subgroups: list[EodSubgroup] = []
    last_run: EodRun | None = None
    dagster_url: str | None = None
    run_subcategories: list[str] = []


class EodPipelineRun(BaseModel):
    run_id: str | None = None
    mode: str | None = None
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    rows_written: int | None = None


class EodSummary(BaseModel):
    securities: int | None = None
    universes: int | None = None
    priced_securities: int | None = None
    latest_session: str | None = None
    last_pipeline_run: EodPipelineRun | None = None


class EodDagster(BaseModel):
    reachable: bool
    ui_url: str
    jobs_with_runs: int


class EodMonitor(BaseModel):
    expected_date: str | None = None
    expected_basis: str
    dagster_runs_available: bool
    dagster: EodDagster
    summary: EodSummary
    buckets: list[EodBucketRow]


@router.get("/eod", response_model=EodMonitor)
def data_monitor_eod(gw: EodMonitorGateway = Depends(_gateway)) -> dict:
    """Per-bucket EOD freshness (expected vs actual business date) + best-effort latest Dagster run."""
    return gw.eod()


class LaunchRequest(BaseModel):
    job: str  # a bucket key (fx, equity_prices, index_levels, rates, …)
    subcategories: list[str] = []  # empty ⇒ the whole bucket; e.g. ["msci"] ⇒ only that subcategory
    as_of_date: str | None = None  # single-date alias
    start_date: str | None = None  # window start (with end_date) for a backfill
    end_date: str | None = None    # window end


class LaunchResult(BaseModel):
    ok: bool
    run_id: str | None = None
    status: str | None = None
    run_url: str | None = None
    error: str | None = None


@router.post("/launch", response_model=LaunchResult)
def data_monitor_launch(req: LaunchRequest) -> dict:
    """Trigger a bucket job in the running Dagster instance (one-click run from the EOD board).

    ``subcategories`` narrows the run (e.g. ``index_levels`` + ``["msci"]`` runs only `sym msci-pull`).
    Mutating + same-origin-guarded (Story O.3); returns the run id + a deep link to the run, or a
    clean error if Dagster isn't running.
    """
    if req.job not in set(bucket_keys()):
        raise HTTPException(status_code=422, detail=f"unknown job {req.job!r}")
    # the page sends the bucket key; Dagster knows the job by its mnemonic name (buckets.JOB_NAMES).
    # pipelineName is the job's mnemonic name (job_name); the config nests under the op name, which is
    # `{bucket_key}_op` (NOT `{job}_load`) — the bucket key is exactly req.job here.
    res = launch_job(
        job_name(req.job), f"{req.job}_op", req.subcategories or None, req.as_of_date,
        start_date=req.start_date, end_date=req.end_date,
    )
    out: dict = {"ok": res["ok"], "error": res.get("error")}
    if res["ok"]:
        out["run_id"] = res["run_id"]
        out["status"] = res.get("status")
        out["run_url"] = dagster_run_url(res["run_id"])
    return out
