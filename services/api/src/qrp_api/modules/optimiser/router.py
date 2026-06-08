"""``/api/optimiser`` — mean-variance portfolio solutions (min-variance, max-Sharpe)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from qrp_api.config import package_dsn
from qrp_api.db import connect
from qrp_api.modules.optimiser.gateway import DbOptimiserGateway

router = APIRouter(prefix="/api/optimiser", tags=["optimiser"])


def _gateway() -> Iterator[DbOptimiserGateway]:
    conn = connect(package_dsn("optimiser"))  # optimiser owns its own database
    sym = connect()                           # sym hub — engine reads on solve
    try:
        yield DbOptimiserGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


class OptSolutionSummary(BaseModel):
    solution_id: int
    created_at: str | None
    universe_id: str
    method: str
    n_assets: int
    lookback_days: int
    exp_return: float | None
    exp_vol: float | None
    sharpe: float | None
    ew_vol: float | None
    summary: dict | None


class OptWeight(BaseModel):
    figi: str
    ticker: str | None
    weight: float


class OptSolutionDetail(OptSolutionSummary):
    weights: list[OptWeight] = []


class OptSolveRequest(BaseModel):
    universe: str = "sp500"
    method: str = "min_variance"  # 'min_variance' | 'max_sharpe'
    n: int = 40
    lookback: int = 252


class OptSolveResult(BaseModel):
    ok: bool
    solution_id: int | None = None
    error: str | None = None


@router.post("/solve", response_model=OptSolveResult)
def solve_ep(body: OptSolveRequest = Body(...), gw: DbOptimiserGateway = Depends(_gateway)) -> dict:
    method = body.method if body.method in ("min_variance", "max_sharpe") else "min_variance"
    n = max(5, min(body.n, 80))
    res = gw.solve(body.universe, method, n, max(60, min(body.lookback, 1000)))
    if "error" in res:
        return {"ok": False, "solution_id": None, "error": res["error"]}
    return {"ok": True, "solution_id": res["solution_id"], "error": None}


@router.get("/solutions", response_model=list[OptSolutionSummary])
def list_solutions(gw: DbOptimiserGateway = Depends(_gateway)) -> list[dict]:
    return gw.solutions()


@router.get("/solutions/{solution_id}", response_model=OptSolutionDetail)
def get_solution(solution_id: int, gw: DbOptimiserGateway = Depends(_gateway)) -> dict:
    d = gw.get(solution_id)
    if d is None:
        raise HTTPException(status_code=404, detail="solution not found")
    return d
