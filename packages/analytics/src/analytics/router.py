"""``/api/portfolios/{pid}/analytics`` + ``/api/analytics/benchmarks`` — risk/return metrics."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from analytics.db import connect
from analytics.gateway import DbAnalyticsGateway

router = APIRouter(tags=["analytics"])


def _gateway() -> Iterator[DbAnalyticsGateway]:
    conn = connect("portfolios")  # portfolios DB — portfolio weights
    sym = connect("sym")                            # sym package — fact_returns / index returns / instrument
    try:
        yield DbAnalyticsGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


class Benchmark(BaseModel):
    id: int
    name: str
    currency: str | None


class Metrics(BaseModel):
    ann_return: float | None
    ann_vol: float | None
    sharpe: float | None
    beta: float | None
    alpha_ann: float | None
    correlation: float | None
    bench_ann_return: float | None
    bench_ann_vol: float | None
    bench_sharpe: float | None
    active_return: float | None
    tracking_error: float | None
    information_ratio: float | None
    hit_ratio: float | None
    batting_average: float | None
    slugging_ratio: float | None


class Analytics(BaseModel):
    as_of: str | None
    window: str
    benchmark: Benchmark | None
    portfolio_currencies: list[str]
    n_days: int
    start: str | None
    end: str | None
    metrics: Metrics | None
    warning: str | None


@router.get("/api/analytics/benchmarks", response_model=list[Benchmark])
def list_benchmarks(gw: DbAnalyticsGateway = Depends(_gateway)) -> list[dict]:
    return gw.benchmarks()


@router.get("/api/portfolios/{pid}/analytics", response_model=Analytics)
def portfolio_analytics(
    pid: int,
    benchmark: int = Query(..., description="instrument sym_id of the index benchmark"),
    window: str = Query(default="ALL", description="ALL | YTD | 1M | 3M | 6M | 1Y | 2Y | 3Y"),
    gw: DbAnalyticsGateway = Depends(_gateway),
) -> dict:
    return gw.analytics(pid, benchmark, window)
