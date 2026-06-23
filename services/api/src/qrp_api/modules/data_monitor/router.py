"""``/api/data-monitor`` router — the Data Monitor area's read endpoints.

v1 has one page (EOD): per-bucket expected-vs-actual business date + best-effort latest Dagster
run, plus a warehouse-summary header (migrated from the retired sym Overview).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from qrp_api.db import connect
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
    error: str | None = None
    subgroups: list[EodSubgroup] = []
    last_run: EodRun | None = None
    dagster_url: str | None = None


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


class EodMonitor(BaseModel):
    expected_date: str | None = None
    expected_basis: str
    dagster_runs_available: bool
    summary: EodSummary
    buckets: list[EodBucketRow]


@router.get("/eod", response_model=EodMonitor)
def data_monitor_eod(gw: EodMonitorGateway = Depends(_gateway)) -> dict:
    """Per-bucket EOD freshness (expected vs actual business date) + best-effort latest Dagster run."""
    return gw.eod()
