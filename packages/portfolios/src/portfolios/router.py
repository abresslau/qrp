"""``/api/portfolios`` router — clients' portfolios (weights-first) + return/PnL engine."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from portfolios.db import connect
from portfolios.gateway import DbPortfolioGateway

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _gateway() -> Iterator[DbPortfolioGateway]:
    conn = connect()  # portfolios owns its own database
    try:
        sym = connect("sym")                            # sym package — labels + fact_returns (PnL), in-app
    except Exception:
        conn.close()  # don't leak the first connection when the second connect fails
        raise
    try:
        yield DbPortfolioGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


# ---- request models ----
class CreatePortfolio(BaseModel):
    name: str
    client: str = ""
    base_currency: str = "USD"
    # FR-15 PnL terms: optional reference notional in base_currency
    notional: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class PatchPortfolio(BaseModel):
    """Settable portfolio terms — merge-patch semantics: an OMITTED field is left
    unchanged; explicit ``notional: null`` clears it (return-space PnL)."""

    notional: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class WeightItem(BaseModel):
    identifier: str  # ticker or composite FIGI
    weight: float = Field(..., allow_inf_nan=False)  # NaN/inf would poison stored sums


class UploadWeights(BaseModel):
    as_of_date: date
    items: list[WeightItem]


# ---- response models (so the OpenAPI schema -> generated TS types carry real shapes) ----
class PortfolioSummary(BaseModel):
    portfolio_id: int
    name: str
    client: str
    base_currency: str
    created_at: str | None
    n_weights: int
    latest_as_of_date: str | None


class CreatedPortfolio(BaseModel):
    portfolio_id: int


class Client(BaseModel):
    client_id: int
    name: str
    created_at: str | None
    n_portfolios: int


class CreateClient(BaseModel):
    name: str


class CreatedClient(BaseModel):
    client_id: int


class Weight(BaseModel):
    figi: str
    ticker: str
    name: str | None
    weight: float


class PortfolioDetail(BaseModel):
    portfolio_id: int
    name: str
    client: str
    base_currency: str
    notional: float | None  # FR-15 PnL reference amount (base_currency); null = unset
    created_at: str | None
    as_of_dates: list[str]
    latest_as_of_date: str | None
    shown_as_of_date: str | None  # the vector this response carries (Q4.5 as-of picker)
    net_exposure: float | None  # Σ weight (signed; long − short) over the shown vector; null if none
    gross_exposure: float | None  # Σ |weight| (long + |short|) over the shown vector; null if none
    long_exposure: float | None  # Σ positive weight; null if no vector
    short_exposure: float | None  # Σ |negative weight| (positive magnitude); null if no vector
    weights: list[Weight]


class UploadResult(BaseModel):
    stored: int
    unresolved: list[str]
    as_of_date: str


class RetConstituent(BaseModel):
    ticker: str
    weight: float
    ret: float | None
    contribution: float | None


class PortfolioReturns(BaseModel):
    window: str
    as_of_date: str | None
    returns_as_of_date: str | None = None  # the single fact_returns date all constituents use
    # Current-holdings attribution snapshot, NOT time-weighted performance — the
    # portfolio's TWR + PnL over its effective-dated history is analytics' `returns`.
    semantics: str = "snapshot_attribution"
    n_constituents: int
    n_with_return: int
    total_weight: float
    covered_weight: float
    portfolio_return: float | None
    portfolio_return_normalized: float | None
    constituents: list[RetConstituent]


@router.get("", response_model=list[PortfolioSummary])
def list_portfolios(gw: DbPortfolioGateway = Depends(_gateway)) -> list[dict]:
    return gw.list()


@router.post("", response_model=CreatedPortfolio)
def create_portfolio(
    body: CreatePortfolio = Body(...), gw: DbPortfolioGateway = Depends(_gateway)
) -> dict:
    pid = gw.create(body.name, body.client, body.base_currency, body.notional)
    return {"portfolio_id": pid}


# Declared BEFORE /{pid} so "clients" isn't captured as a portfolio id.
@router.get("/clients", response_model=list[Client])
def list_clients(gw: DbPortfolioGateway = Depends(_gateway)) -> list[dict]:
    return gw.clients()


@router.post("/clients", response_model=CreatedClient)
def create_client(
    body: CreateClient = Body(...), gw: DbPortfolioGateway = Depends(_gateway)
) -> dict:
    try:
        return {"client_id": gw.create_client(body.name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{pid}", response_model=PortfolioDetail)
def get_portfolio(
    pid: int,
    as_of_date: date | None = Query(default=None, description="historical vector to show"),
    gw: DbPortfolioGateway = Depends(_gateway),
) -> dict:
    if as_of_date is None:
        d = gw.get(pid)
    else:
        # the 422 mapping is scoped to the one ValueError this path can raise —
        # a date with no stored vector
        try:
            d = gw.get(pid, as_of_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if d is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return d


@router.patch("/{pid}", response_model=PortfolioDetail)
def patch_portfolio(
    pid: int, body: PatchPortfolio = Body(...), gw: DbPortfolioGateway = Depends(_gateway)
) -> dict:
    # merge-patch: only fields the client actually SENT are applied — `{}` is a
    # no-op, not a notional wipe (explicit `notional: null` still clears).
    if "notional" in body.model_fields_set:
        if not gw.set_notional(pid, body.notional):
            raise HTTPException(status_code=404, detail="portfolio not found")
    d = gw.get(pid)
    if d is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return d


@router.post("/{pid}/weights", response_model=UploadResult)
def upload_weights(
    pid: int, body: UploadWeights = Body(...), gw: DbPortfolioGateway = Depends(_gateway)
) -> dict:
    if gw.get(pid) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return gw.upload_weights(pid, body.as_of_date, [(i.identifier, i.weight) for i in body.items])


@router.get("/{pid}/returns", response_model=PortfolioReturns)
def portfolio_returns(
    pid: int, window: str = Query(default="YTD"), gw: DbPortfolioGateway = Depends(_gateway)
) -> dict:
    if gw.get(pid) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    try:
        return gw.returns(pid, window)
    except ValueError as exc:  # unknown return window
        raise HTTPException(status_code=422, detail=str(exc)) from exc
