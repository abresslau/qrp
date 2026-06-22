"""``/api/rates`` — fixed-income yield curves (Bank of England UK curves; QRP-managed)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from rates.db import connect
from rates.gateway import DbRatesGateway

router = APIRouter(prefix="/api/rates", tags=["rates"])


def _gateway() -> Iterator[DbRatesGateway]:
    conn = connect()  # rates owns its own database (DSN resolved by rates.db)
    try:
        yield DbRatesGateway(conn)
    finally:
        conn.close()


class CurveSeries(BaseModel):
    curve_set: str
    basis: str
    rate_type: str
    days: int
    start_date: str | None
    end_date: str | None


class CurvePointOut(BaseModel):
    tenor: float
    value: float


class Curve(BaseModel):
    curve_set: str
    basis: str
    rate_type: str
    vintage: str
    as_of_date: str | None
    points: list[CurvePointOut]


@router.get("/curve/series", response_model=list[CurveSeries])
def list_curve_series(gw: DbRatesGateway = Depends(_gateway)) -> list[dict]:
    return gw.curve_sets()


@router.get("/curve", response_model=Curve)
def get_curve(
    curve_set: str = Query("glc", description="glc (gilt) | ois"),
    basis: str = Query("nominal", description="nominal | real | inflation"),
    rate_type: str = Query("spot", description="spot | forward"),
    as_of_date: date | None = Query(None, description="Curve as-of (latest if omitted)"),
    vintage: str = Query("latest", description="latest (restated) | first (first-published, PIT)"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.curve(curve_set, basis, rate_type, as_of_date, vintage=vintage)
