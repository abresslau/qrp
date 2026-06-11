"""``/api/macro`` — central-bank / macroeconomic series (World Bank, ECB, US Treasury
FiscalData, OECD, Eurostat; QRP-managed)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from macro.db import connect
from macro.gateway import DbMacroGateway

router = APIRouter(prefix="/api/macro", tags=["macro"])


def _gateway() -> Iterator[DbMacroGateway]:
    conn = connect()  # macro owns its own database (DSN resolved by macro.config)
    try:
        yield DbMacroGateway(conn)
    finally:
        conn.close()


class SeriesSummary(BaseModel):
    series_id: str
    source: str
    name: str
    geo: str | None
    unit: str | None
    frequency: str | None
    n_obs: int
    start_date: str | None  # observed coverage range (canonical date-naming convention)
    end_date: str | None
    latest: float | None


class Observation(BaseModel):
    obs_date: str
    value: float


class SeriesDetail(BaseModel):
    series_id: str
    source: str
    name: str
    geo: str | None
    unit: str | None
    frequency: str | None
    observations: list[Observation]


@router.get("/series", response_model=list[SeriesSummary])
def list_macro_series(gw: DbMacroGateway = Depends(_gateway)) -> list[dict]:
    return gw.series()


@router.get("/series/{series_id:path}", response_model=SeriesDetail)
def get_macro_series(series_id: str, gw: DbMacroGateway = Depends(_gateway)) -> dict:
    d = gw.observations(series_id)
    if d is None:
        raise HTTPException(status_code=404, detail="series not found")
    return d
