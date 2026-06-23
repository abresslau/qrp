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


class SparkPoint(BaseModel):
    as_of_date: str
    value: float


class SpreadSummary(BaseModel):
    key: str
    label: str
    unit: str  # 'bp' (difference) | '%' (level, e.g. breakeven)
    value: float | None  # N/A when a leg tenor isn't published
    zscore: float | None
    percentile: float | None
    as_of_date: str | None
    history: list[SparkPoint]


class SpreadHistory(BaseModel):
    key: str
    label: str
    unit: str
    points: list[SparkPoint]


class CurveMovieFrame(BaseModel):
    as_of_date: str
    points: list[CurvePointOut]


class CurveMovie(BaseModel):
    curve_set: str
    basis: str
    rate_type: str
    frames: list[CurveMovieFrame]


@router.get("/curve/series", response_model=list[CurveSeries])
def list_curve_series(gw: DbRatesGateway = Depends(_gateway)) -> list[dict]:
    return gw.curve_sets()


@router.get("/spreads", response_model=list[SpreadSummary])
def list_spreads(gw: DbRatesGateway = Depends(_gateway)) -> list[dict]:
    return gw.spreads()


@router.get("/spread/{key}", response_model=SpreadHistory)
def get_spread(
    key: str,
    window: str = Query("MAX", description="1Y | 5Y | MAX"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.spread_history(key, window)


@router.get("/curve/movie", response_model=CurveMovie)
def get_curve_movie(
    curve_set: str = Query("glc"),
    basis: str = Query("nominal"),
    rate_type: str = Query("spot"),
    frames: int = Query(120, ge=2, le=240, description="max frames sampled across the window"),
    start_date: date | None = Query(None, description="window start; full history if omitted"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.curve_movie(curve_set, basis, rate_type, frames, start_date)


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
