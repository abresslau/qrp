"""``/api/altdata`` — alternative-data series (Wikimedia pageviews, SEC EDGAR filing activity)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from altdata.db import connect
from altdata.gateway import DbAltdataGateway

router = APIRouter(prefix="/api/altdata", tags=["altdata"])


def _gateway() -> Iterator[DbAltdataGateway]:
    conn = connect()  # altdata owns its own database
    try:
        yield DbAltdataGateway(conn)
    finally:
        conn.close()


class AltSeries(BaseModel):
    composite_figi: str
    ticker: str | None
    name: str | None
    source: str
    metric: str
    detail: str | None  # source-native key (wikipedia article / SEC CIK) — series provenance
    unit: str | None
    n_obs: int
    as_of_date: str | None  # latest observation date (canonical date-naming convention)
    latest_value: float | None
    avg7: float | None  # sum over trailing 7 days / 7 — calendar-day rate, series-anchored
    avg30: float | None  # sum over trailing 30 days / 30
    attention_spike: float | None  # avg7 / avg30 (>1 = rising activity)


class AltObservation(BaseModel):
    obs_date: str
    value: float


class AltSeriesDetail(BaseModel):
    composite_figi: str
    ticker: str | None
    name: str | None
    source: str
    metric: str
    detail: str | None
    unit: str | None
    observations: list[AltObservation]


@router.get("/series", response_model=list[AltSeries])
def list_altdata_series(gw: DbAltdataGateway = Depends(_gateway)) -> list[dict]:
    return gw.series()


@router.get("/series/{figi}", response_model=AltSeriesDetail)
def get_altdata_series(
    figi: str, source: str, metric: str, gw: DbAltdataGateway = Depends(_gateway)
) -> dict:
    # A security can carry several series (one per source × metric) — the query params
    # pick one; both are required.
    d = gw.observations(figi, source, metric)
    if d is None:
        raise HTTPException(status_code=404, detail="series not found")
    return d
