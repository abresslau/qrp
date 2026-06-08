"""``/api/backtest`` — run + read walk-forward factor-strategy backtests."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from backtest.db import connect, hub
from backtest.gateway import DbBacktestGateway

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _gateway() -> Iterator[DbBacktestGateway]:
    conn = connect()  # backtest owns its own database
    sym = hub()                          # sym hub — engine reads on run
    try:
        yield DbBacktestGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


class Stats(BaseModel):
    total_return: float | None = None
    ann_return: float | None = None
    ann_vol: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None


class Summary(BaseModel):
    strategy: Stats
    baseline: Stats
    excess_total: float | None = None
    first_rebalance: str | None = None
    first_holding_n: int | None = None


class RunSummary(BaseModel):
    run_id: int
    created_at: str | None
    factor: str
    universe_id: str
    top_pct: float
    rebalance: str
    start_date: str | None
    end_date: str | None
    n_days: int | None
    n_rebalances: int | None
    summary: Summary | None


class CurvePoint(BaseModel):
    date: str
    strat: float
    base: float


class RunDetail(RunSummary):
    curve: list[CurvePoint] = []


class BacktestRunRequest(BaseModel):
    factor: str = "mom_12_1"
    universe: str = "sp500"
    top_pct: float = 0.2
    save_portfolio: bool = False  # Q6.4: also materialise the run as a paper Portfolio


class BacktestRunResult(BaseModel):
    ok: bool
    run_id: int | None = None
    portfolio_id: int | None = None  # set when save_portfolio = true
    error: str | None = None


@router.post("/run", response_model=BacktestRunResult)
def run_backtest_ep(
    body: BacktestRunRequest = Body(...), gw: DbBacktestGateway = Depends(_gateway)
) -> dict:
    pconn = pgw = None
    if body.save_portfolio:
        from portfolios.gateway import DbPortfolioGateway

        pconn = connect("portfolios")   # write the paper portfolio to its own DB
        pgw = DbPortfolioGateway(pconn, gw._sym)      # reuse the sym hub for figi resolution
    try:
        res = gw.run(body.factor, body.universe, body.top_pct, portfolios_gw=pgw)
    finally:
        if pconn is not None:
            pconn.close()
    if "error" in res:
        return {"ok": False, "run_id": None, "portfolio_id": None, "error": res["error"]}
    return {"ok": True, "run_id": res["run_id"], "portfolio_id": res.get("portfolio_id"),
            "error": None}


@router.get("/runs", response_model=list[RunSummary])
def list_runs(gw: DbBacktestGateway = Depends(_gateway)) -> list[dict]:
    return gw.runs()


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, gw: DbBacktestGateway = Depends(_gateway)) -> dict:
    d = gw.get(run_id)
    if d is None:
        raise HTTPException(status_code=404, detail="run not found")
    return d
