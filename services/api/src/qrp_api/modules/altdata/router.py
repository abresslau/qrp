"""``/api/altdata`` — alternative-data signals (Wikimedia pageviews attention proxy)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from qrp_api.config import package_dsn
from qrp_api.db import connect
from qrp_api.modules.altdata.gateway import DbAltdataGateway

router = APIRouter(prefix="/api/altdata", tags=["altdata"])


def _gateway() -> Iterator[DbAltdataGateway]:
    conn = connect(package_dsn("altdata"))  # altdata owns its own database
    try:
        yield DbAltdataGateway(conn)
    finally:
        conn.close()


class AltSeries(BaseModel):
    composite_figi: str
    ticker: str | None
    name: str | None
    article: str
    n_obs: int
    last: str | None
    latest_views: int | None
    avg7: float | None
    avg30: float | None
    attention_spike: float | None


class AltObservation(BaseModel):
    date: str
    views: int


class AltSeriesDetail(BaseModel):
    composite_figi: str
    ticker: str | None
    name: str | None
    article: str
    observations: list[AltObservation]


@router.get("/series", response_model=list[AltSeries])
def list_series(gw: DbAltdataGateway = Depends(_gateway)) -> list[dict]:
    return gw.series()


@router.get("/series/{figi}", response_model=AltSeriesDetail)
def get_series(figi: str, gw: DbAltdataGateway = Depends(_gateway)) -> dict:
    d = gw.observations(figi)
    if d is None:
        raise HTTPException(status_code=404, detail="series not found")
    return d
