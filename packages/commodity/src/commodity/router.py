"""``/api/commodities`` — daily commodity prices (Tier-A continuous; QRP `commodities` DB)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from commodity.db import connect
from commodity.gateway import DbCommoditiesGateway

router = APIRouter(prefix="/api/commodities", tags=["commodities"])


def _gateway() -> Iterator[DbCommoditiesGateway]:
    conn = connect()  # commodities owns its own database (DSN resolved by commodity.db)
    try:
        yield DbCommoditiesGateway(conn)
    finally:
        conn.close()


class BoardRow(BaseModel):
    code: str
    name: str
    sector: str
    sector_label: str
    exchange: str
    currency: str
    unit: str
    as_of_date: str | None
    last: float | None
    prev: float | None
    chg_1d: float | None
    pct_1d: float | None
    pct_1w: float | None
    pct_1m: float | None
    pct_ytd: float | None
    pct_1y: float | None
    volume: float | None
    spark: list[float]


class HistoryPoint(BaseModel):
    as_of_date: str
    settle: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


class History(BaseModel):
    code: str
    name: str
    sector: str | None
    unit: str | None
    currency: str | None
    exchange: str | None
    points: list[HistoryPoint]


class Coverage(BaseModel):
    code: str
    name: str
    sector: str | None
    days: int
    start_date: str | None
    end_date: str | None
    source: str | None


@router.get("/board", response_model=list[BoardRow])
def get_board(gw: DbCommoditiesGateway = Depends(_gateway)) -> list[dict]:
    return gw.board()


@router.get("/history/{code}", response_model=History)
def get_history(
    code: str,
    window: str = Query("MAX", description="1Y | 5Y | MAX"),
    gw: DbCommoditiesGateway = Depends(_gateway),
) -> dict:
    return gw.history(code.upper(), window)


@router.get("/coverage", response_model=list[Coverage])
def get_coverage(gw: DbCommoditiesGateway = Depends(_gateway)) -> list[dict]:
    return gw.coverage()
