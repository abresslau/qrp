"""``/api/macro`` — central-bank / macroeconomic series (World Bank, ECB; QRP-managed)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qrp_api.db import connect
from qrp_api.modules.macro.gateway import DbMacroGateway

router = APIRouter(prefix="/api/macro", tags=["macro"])


def _gateway() -> Iterator[DbMacroGateway]:
    conn = connect()
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
    first: str | None
    last: str | None
    latest: float | None


class Observation(BaseModel):
    date: str
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
def list_series(gw: DbMacroGateway = Depends(_gateway)) -> list[dict]:
    return gw.series()


@router.get("/series/{series_id:path}", response_model=SeriesDetail)
def get_series(series_id: str, gw: DbMacroGateway = Depends(_gateway)) -> dict:
    d = gw.observations(series_id)
    if d is None:
        raise HTTPException(status_code=404, detail="series not found")
    return d
