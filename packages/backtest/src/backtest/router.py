"""``/api/backtest`` — run + read walk-forward factor-strategy backtests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from backtest.db import connect
from backtest.gateway import DbBacktestGateway

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _gateway() -> Iterator[DbBacktestGateway]:
    conn = connect()  # backtest owns its own database
    try:
        sym = connect("sym")                          # sym package — engine reads on run
    except Exception:
        conn.close()  # don't leak the first connection when the second connect fails
        raise
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
    strategy: Stats  # net of costs when cost_bps > 0, else gross
    baseline: Stats
    excess_total: float | None = None
    first_rebalance: str | None = None
    first_holding_n: int | None = None
    # cap-weighting honesty: names dropped for missing market cap (never zero-weighted)
    dropped_no_mcap: int | None = None
    # turnover + transaction-cost honesty (1A): turnover always reported; cost applied iff costed
    turnover_ann: float | None = None
    turnover_total: float | None = None
    cost_bps: float | None = None
    cost_drag_total: float | None = None
    strategy_gross: Stats | None = None  # populated only when costs are modelled
    # statistical-significance guardrail (1B; Harvey-Liu-Zhu hurdle is t>3.0, not 2.0)
    spread_tstat: float | None = None
    spread_tstat_hurdle: float | None = None
    spread_significant: bool | None = None


class StrategySpec(BaseModel):
    """The reproducible strategy definition a run was produced from (FR-18, Q6.3)."""

    factor: str
    universe: str
    top_pct: float | None = None
    top_n: int | None = None
    weighting: str = "equal"
    rebalance: str = "monthly"
    cost_bps: float | None = None  # round-trip cost per unit one-way turnover (NULL on pre-1A runs)
    start_date: str | None = None
    end_date: str | None = None


class RunSummary(BaseModel):
    run_id: int
    created_at: str | None
    factor: str
    universe_id: str
    top_pct: float | None  # None on top_n runs (the legacy column's 0.0 sentinel is not data)
    rebalance: str
    start_date: str | None
    end_date: str | None
    n_days: int | None
    n_rebalances: int | None
    summary: Summary | None
    spec: StrategySpec | None = None  # NULL on pre-Q6.3 runs


class CurvePoint(BaseModel):
    obs_date: str  # matches backtest.point.obs_date (canonical date naming)
    strat: float
    base: float


class RunDetail(RunSummary):
    curve: list[CurvePoint] = []


class BacktestRunRequest(BaseModel):
    factor: str = "mom_12_1"  # any signals-package factor key (incl. cross-module)
    universe: str = "sp500"
    # selection: exactly one of top_pct / top_n (422 if both given)
    top_pct: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    top_n: int | None = Field(default=None, gt=0)
    weighting: str = "equal"  # equal | cap
    rebalance: str = "monthly"  # monthly | quarterly
    # 1A transaction costs: bps charged on one-way turnover (0 = gross). Default 10 (liquid
    # large-cap one-way) so runs are NET by default; raise for a less-liquid book, 0 for gross.
    cost_bps: float = Field(default=10.0, ge=0, le=1000, allow_inf_nan=False)
    start_date: date | None = None  # FR-18: optional explicit range (default: ~5y of data)
    end_date: date | None = None
    save_portfolio: bool = False  # Q6.4: also materialise the run as a paper Portfolio


class BacktestRunResult(BaseModel):
    ok: bool
    run_id: int | None = None
    portfolio_id: int | None = None  # set when save_portfolio = true
    error: str | None = None


class SweepRequest(BaseModel):
    """A parameter-grid sweep (Story 1B): fixed base params + a grid of varied run-kwargs.

    ``grid`` keys are run parameters (e.g. ``top_pct``, ``rebalance``, ``cost_bps``, ``factor``);
    the cartesian product is the trial set whose size N feeds the Deflated Sharpe / MinBTL.
    """

    factor: str = "mom_12_1"
    universe: str = "sp500"
    weighting: str = "equal"
    rebalance: str = "monthly"
    cost_bps: float = Field(default=10.0, ge=0, le=1000, allow_inf_nan=False)
    start_date: date | None = None
    end_date: date | None = None
    grid: dict[str, list] = Field(..., description="{run_param: [values, ...]}")
    n_splits: int = Field(default=16, ge=4, le=20)


class SweepResult(BaseModel):
    ok: bool
    sweep_id: int | None = None
    n_configs: int | None = None
    summary: dict | None = None
    error: str | None = None


class SweepSummary(BaseModel):
    sweep_id: int
    created_at: str | None
    base_spec: dict | None
    grid: dict | None
    n_configs: int
    best_run_id: int | None = None
    summary: dict | None = None


@router.post("/run", response_model=BacktestRunResult)
def run_backtest_ep(
    body: BacktestRunRequest = Body(...), gw: DbBacktestGateway = Depends(_gateway)
) -> dict:
    from signals.compute import required_modules

    if body.top_pct is not None and body.top_n is not None:
        raise HTTPException(status_code=422, detail="give top_pct OR top_n, not both")
    top_pct = body.top_pct if (body.top_pct is not None or body.top_n is not None) else 0.2
    try:
        needed = required_modules(body.factor)
    except ValueError as exc:  # unknown factor
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Explicit module -> engine-kwarg map: a factor declaring a module the engine has
    # no parameter for must be a clear 422, not a TypeError-500 after connecting.
    module_kwarg = {"altdata": "alt_conn", "macro": "macro_conn"}
    unsupported = needed - set(module_kwarg)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"factor {body.factor!r} requires unsupported module(s): "
                   f"{', '.join(sorted(unsupported))}",
        )

    pconn = pgw = None
    extra_conns: list = []
    module_conns: dict = {}
    if body.save_portfolio:
        from portfolio.gateway import DbPortfolioGateway

        pconn = connect("portfolio")   # write the paper portfolio to its own DB
        pgw = DbPortfolioGateway(pconn, gw._sym)      # reuse the sym package for figi resolution
    try:
        # AR-R2: a cross-module factor's input modules are read over their OWN
        # connections, opened only when the factor's declared inputs demand them.
        for module in sorted(needed):
            try:
                c = connect(module)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"input module {module!r} unavailable: {type(exc).__name__}",
                ) from exc
            extra_conns.append(c)
            module_conns[module_kwarg[module]] = c
        res = gw.run(body.factor, body.universe, top_pct, portfolios_gw=pgw,
                     start_date=body.start_date, end_date=body.end_date,
                     top_n=body.top_n, weighting=body.weighting, rebalance=body.rebalance,
                     cost_bps=body.cost_bps, **module_conns)
    finally:
        if pconn is not None:
            pconn.close()
        for c in extra_conns:
            c.close()
    if "error" in res:
        return {"ok": False, "run_id": None, "portfolio_id": None, "error": res["error"]}
    return {"ok": True, "run_id": res["run_id"], "portfolio_id": res.get("portfolio_id"),
            "error": None}


@router.post("/sweep", response_model=SweepResult)
def run_sweep_ep(
    body: SweepRequest = Body(...), gw: DbBacktestGateway = Depends(_gateway)
) -> dict:
    from signals.compute import required_modules

    grid = {("universe_id" if k == "universe" else k): v for k, v in body.grid.items()}
    if not grid:
        raise HTTPException(status_code=422, detail="grid must vary at least one parameter")
    base_spec = {
        "factor": body.factor, "universe_id": body.universe, "weighting": body.weighting,
        "rebalance": body.rebalance, "cost_bps": body.cost_bps,
        "start_date": body.start_date, "end_date": body.end_date,
    }
    # a grid key overrides the fixed base value for that parameter
    for k in grid:
        base_spec.pop(k, None)

    # every factor the sweep might touch (fixed + any varied in the grid) determines which
    # input-module connections to open — same AR-R2 pattern as /run.
    factors = {body.factor, *(str(f) for f in grid.get("factor", []))}
    module_kwarg = {"altdata": "alt_conn", "macro": "macro_conn"}
    needed: set[str] = set()
    for f in factors:
        try:
            needed |= required_modules(f)
        except ValueError as exc:  # unknown factor
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    unsupported = needed - set(module_kwarg)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"factor(s) require unsupported module(s): {sorted(unsupported)}")

    extra_conns: list = []
    module_conns: dict = {}
    try:
        for module in sorted(needed):
            try:
                c = connect(module)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"input module {module!r} unavailable: {type(exc).__name__}",
                ) from exc
            extra_conns.append(c)
            module_conns[module_kwarg[module]] = c
        res = gw.sweep(base_spec, grid, n_splits=body.n_splits, **module_conns)
    finally:
        for c in extra_conns:
            c.close()
    if "error" in res:
        return {"ok": False, "sweep_id": None, "n_configs": None, "summary": None,
                "error": res["error"]}
    return {"ok": True, "sweep_id": res.get("sweep_id"), "n_configs": res.get("n_configs"),
            "summary": res.get("summary"), "error": None}


@router.get("/sweeps", response_model=list[SweepSummary])
def list_sweeps(gw: DbBacktestGateway = Depends(_gateway)) -> list[dict]:
    return gw.sweeps()


@router.get("/sweeps/{sweep_id}", response_model=SweepSummary)
def get_sweep(sweep_id: int, gw: DbBacktestGateway = Depends(_gateway)) -> dict:
    s = gw.get_sweep(sweep_id)
    if s is None:
        raise HTTPException(status_code=404, detail="sweep not found")
    return s


@router.get("/runs", response_model=list[RunSummary])
def list_runs(gw: DbBacktestGateway = Depends(_gateway)) -> list[dict]:
    return gw.runs()


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, gw: DbBacktestGateway = Depends(_gateway)) -> dict:
    d = gw.get(run_id)
    if d is None:
        raise HTTPException(status_code=404, detail="run not found")
    return d
