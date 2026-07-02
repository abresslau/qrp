"""``/api/optimiser`` — constrained mean-variance solutions with signal tilts (FR-22),
saved as Portfolios and scored out-of-sample via the backtest package (Q7.4)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from optimiser.db import connect
from optimiser.gateway import DbOptimiserGateway

router = APIRouter(prefix="/api/optimiser", tags=["optimiser"])


def _gateway() -> Iterator[DbOptimiserGateway]:
    conn = connect()  # optimiser owns its own database
    try:
        sym = connect("sym")                           # sym package — engine reads on solve
    except Exception:
        conn.close()  # don't leak the first connection when the second connect fails
        raise
    try:
        yield DbOptimiserGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


class SignalTilt(BaseModel):
    """Q9.4: a signals factor biases the objective (−strength·wᵀz)."""

    factor: str
    strength: float = Field(..., gt=0, allow_inf_nan=False)


class SolveSpec(BaseModel):
    """The reproducible solve definition persisted on the solution (FR-22, Q7.3)."""

    universe: str
    method: str
    n: int
    lookback: int
    max_weight: float | None = None
    cov_method: str | None = None  # 'shrinkage' | 'sample' (NULL on pre-1C solutions)
    signal_tilt: SignalTilt | None = None
    holdout_days: int = 0
    save_portfolio: bool = False
    train_start: str | None = None
    train_end: str | None = None
    # long/short (min_variance_long_short) fields — present only on L/S solutions
    factor: str | None = None
    long_n: int | None = None
    long_pct: float | None = None
    short_n: int | None = None
    short_pct: float | None = None
    net_target: float | None = None
    gross_target: float | None = None


class OptSolutionSummary(BaseModel):
    solution_id: int
    created_at: str | None
    universe_id: str
    method: str
    n_assets: int
    lookback_days: int
    exp_return: float | None  # in-sample (training window) expectation
    exp_vol: float | None
    sharpe: float | None
    ew_vol: float | None
    summary: dict | None  # incl. the out-of-sample `holdout` block when requested
    spec: SolveSpec | None = None  # NULL on pre-Q7.3 solutions


class OptWeight(BaseModel):
    figi: str
    ticker: str | None
    weight: float


class OptSolutionDetail(OptSolutionSummary):
    weights: list[OptWeight] = []


class OptSolveRequest(BaseModel):
    universe: str = "sp500"
    method: str = "min_variance"  # 'min_variance' | 'max_sharpe'
    n: int = Field(default=40, ge=5, le=80)
    lookback: int = Field(default=252, ge=60, le=1000)
    # Q7.3 constraint archetype: per-position cap (None = unconstrained long-only)
    max_weight: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    # 1C risk model: Ledoit-Wolf const-correlation shrinkage (default) vs the raw sample covariance
    cov_method: str = "shrinkage"  # 'shrinkage' | 'sample'
    # Q9.4: optional signal tilt
    signal_tilt: SignalTilt | None = None
    # Q7.4b: score the solution out-of-sample on a trailing holdout via backtest
    holdout_days: int = Field(default=0, ge=0, le=252)
    # Q7.4a: persist the allocation as a portfolios Portfolio
    save_portfolio: bool = False
    # method='min_variance_long_short': the covariance-aware dollar-neutral long/short solve. The
    # ranking factor pre-signs names (top=long, bottom=short); each leg is sized by _n XOR _pct.
    # net_target/gross_target set the leg masses (0 / 1 = dollar-neutral).
    factor: str = "sharpe_tr"
    long_n: int | None = Field(default=None, gt=0)
    long_pct: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    short_n: int | None = Field(default=None, gt=0)
    short_pct: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    net_target: float = Field(default=0.0, ge=-1, le=1, allow_inf_nan=False)
    gross_target: float = Field(default=1.0, gt=0, le=4, allow_inf_nan=False)


class OptSolveResult(BaseModel):
    ok: bool
    solution_id: int | None = None
    portfolio_id: int | None = None  # set when save_portfolio = true
    # a failed portfolio save is ATTRIBUTED (the committed solution still stands)
    portfolio_error: str | None = None
    error: str | None = None


@router.post("/solve", response_model=OptSolveResult)
def solve_ep(body: OptSolveRequest = Body(...), gw: DbOptimiserGateway = Depends(_gateway)) -> dict:
    # No silent clamping/preferences: out-of-range params are 422s via the request
    # model; an unknown method is the caller's error.
    if body.method not in ("min_variance", "max_sharpe", "min_variance_long_short"):
        raise HTTPException(status_code=422,
                            detail=f"unknown method {body.method!r}")
    if body.cov_method not in ("shrinkage", "sample"):
        raise HTTPException(status_code=422,
                            detail=f"unknown cov_method {body.cov_method!r}")
    is_long_short = body.method == "min_variance_long_short"
    # The long-only max_weight*n feasibility check does not apply to L/S (the cap is per LEG, not
    # over n) — that feasibility is validated in the engine helper against the aligned leg sizes.
    if not is_long_short and body.max_weight is not None and body.max_weight * body.n < 1.0:
        raise HTTPException(
            status_code=422,
            detail=f"infeasible max_weight {body.max_weight} for n={body.n} "
                   "(max_weight * n must be >= 1)",
        )
    if is_long_short:
        if body.long_n is not None and body.long_pct is not None:
            raise HTTPException(status_code=422, detail="give long_n OR long_pct, not both")
        if body.short_n is not None and body.short_pct is not None:
            raise HTTPException(status_code=422, detail="give short_n OR short_pct, not both")
    elif body.signal_tilt is None and (
        body.long_n or body.long_pct or body.short_n or body.short_pct
    ):
        # long/short selectors are meaningless for a long-only method — reject, don't silently drop
        raise HTTPException(
            status_code=422,
            detail="long_n/long_pct/short_n/short_pct require method='min_variance_long_short'")

    # The tilt factor's input modules are read over their OWN connections, opened only
    # when the factor's declared inputs demand them (AR-R2 — the Q6.3 router pattern).
    module_kwarg = {"altdata": "alt_conn", "macro": "macro_conn"}
    module_conns: dict = {}
    extra_conns: list = []
    if body.signal_tilt is not None:
        from signals.compute import required_modules

        try:
            needed = required_modules(body.signal_tilt.factor)
        except ValueError as exc:  # unknown factor
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        unsupported = needed - set(module_kwarg)
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=f"factor {body.signal_tilt.factor!r} requires unsupported "
                       f"module(s): {', '.join(sorted(unsupported))}",
            )
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

    pconn = pgw = None
    if body.save_portfolio:
        from portfolio.gateway import DbPortfolioGateway

        pconn = connect("portfolio")  # write the paper portfolio to its own DB
        pgw = DbPortfolioGateway(pconn, gw._sym)  # reuse the sym package for figi labels
    try:
        res = gw.solve(
            body.universe, body.method, body.n, body.lookback,
            max_weight=body.max_weight, cov_method=body.cov_method,
            signal_tilt=body.signal_tilt.model_dump() if body.signal_tilt else None,
            holdout_days=body.holdout_days, portfolios_gw=pgw,
            factor=body.factor, long_n=body.long_n, long_pct=body.long_pct,
            short_n=body.short_n, short_pct=body.short_pct,
            net_target=body.net_target, gross_target=body.gross_target,
            **module_conns,
        )
    finally:
        if pconn is not None:
            pconn.close()
        for c in extra_conns:
            c.close()
    if "error" in res:
        return {"ok": False, "solution_id": None, "portfolio_id": None,
                "portfolio_error": None, "error": res["error"]}
    return {"ok": True, "solution_id": res["solution_id"],
            "portfolio_id": res.get("portfolio_id"),
            "portfolio_error": res.get("portfolio_error"), "error": None}


@router.get("/solutions", response_model=list[OptSolutionSummary])
def list_solutions(gw: DbOptimiserGateway = Depends(_gateway)) -> list[dict]:
    return gw.solutions()


@router.get("/solutions/{solution_id}", response_model=OptSolutionDetail)
def get_solution(solution_id: int, gw: DbOptimiserGateway = Depends(_gateway)) -> dict:
    d = gw.get(solution_id)
    if d is None:
        raise HTTPException(status_code=404, detail="solution not found")
    return d
