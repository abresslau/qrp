"""``/api/portfolios`` router — clients' portfolios (weights-first) + return/PnL engine."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from qrp_api.db import connect
from qrp_api.modules.portfolios.gateway import DbPortfolioGateway

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _gateway() -> Iterator[DbPortfolioGateway]:
    conn = connect()
    try:
        yield DbPortfolioGateway(conn)
    finally:
        conn.close()


# ---- request models ----
class CreatePortfolio(BaseModel):
    name: str
    client: str = ""
    base_currency: str = "USD"


class WeightItem(BaseModel):
    identifier: str  # ticker or composite FIGI
    weight: float


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
    latest_as_of: str | None


class CreatedPortfolio(BaseModel):
    portfolio_id: int


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
    created_at: str | None
    as_of_dates: list[str]
    latest_as_of: str | None
    weights: list[Weight]


class UploadResult(BaseModel):
    stored: int
    unresolved: list[str]
    as_of: str


class RetConstituent(BaseModel):
    ticker: str
    weight: float
    ret: float | None
    contribution: float | None


class PortfolioReturns(BaseModel):
    window: str
    as_of: str | None
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
    pid = gw.create(body.name, body.client, body.base_currency)
    return {"portfolio_id": pid}


@router.get("/{pid}", response_model=PortfolioDetail)
def get_portfolio(pid: int, gw: DbPortfolioGateway = Depends(_gateway)) -> dict:
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
    return gw.returns(pid, window)
