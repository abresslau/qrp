"""``/api/analytics/*`` — risk/return metrics under the module's OWN prefix (A.1)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from analytics.db import connect
from analytics.gateway import DbAnalyticsGateway

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _gateway() -> Iterator[DbAnalyticsGateway]:
    conn = connect("portfolios")  # portfolios DB — portfolio weights
    try:
        sym = connect("sym")                            # sym package — fact_returns / index returns / instrument
    except Exception:
        conn.close()  # don't leak the first connection when the second connect fails
        raise
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


class Returns(BaseModel):
    """FR-15: cumulative time-weighted return compounded over the PORTFOLIO's own
    window-filtered effective-dated series (benchmark-INDEPENDENT, unlike the relative
    metrics); pnl = notional × cumulative_return when the portfolio states a notional
    (base_currency), else null. Coverage honesty: days below full coverage were
    renormalised (unpriced weight implicitly earns the covered-average return)."""

    cumulative_return: float
    n_days: int
    days_below_full_coverage: int
    min_coverage: float
    notional: float | None
    base_currency: str | None
    pnl: float | None


class Analytics(BaseModel):
    # the NEWEST stored weight vector's date — the series blends the full
    # effective-dated history (Q4.5), not just this vector
    as_of_date: str | None
    window: str
    benchmark: Benchmark | None
    portfolio_currencies: list[str]
    n_days: int
    start_date: str | None
    end_date: str | None
    returns: Returns | None
    metrics: Metrics | None
    warning: str | None


@router.get("/benchmarks", response_model=list[Benchmark])
def list_benchmarks(gw: DbAnalyticsGateway = Depends(_gateway)) -> list[dict]:
    return gw.benchmarks()


@router.get("/portfolios/{pid}", response_model=Analytics)
def portfolio_analytics(
    pid: int,
    benchmark: int = Query(..., description="instrument sym_id of the index benchmark"),
    window: str = Query(default="ALL", description="ALL | YTD | 1M | 3M | 6M | 1Y | 2Y | 3Y"),
    gw: DbAnalyticsGateway = Depends(_gateway),
) -> dict:
    try:
        return gw.analytics(pid, benchmark, window)
    except ValueError as exc:  # unknown window code
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:  # nonexistent portfolio
        raise HTTPException(status_code=404, detail=str(exc)) from exc
