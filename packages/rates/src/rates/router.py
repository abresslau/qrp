"""``/api/rates`` — fixed-income yield curves (multi-country; QRP-managed `rates` DB)."""

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


class Country(BaseModel):
    country: str
    currency: str | None
    start_date: str | None
    end_date: str | None


class CurveSeries(BaseModel):
    country: str
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
    country: str
    curve_set: str
    basis: str
    rate_type: str
    vintage: str
    as_of_date: str | None
    points: list[CurvePointOut]


class CompareCurve(BaseModel):
    country: str
    currency: str | None
    curve_set: str
    basis: str
    rate_type: str
    as_of_date: str | None
    points: list[CurvePointOut]


class SparkPoint(BaseModel):
    as_of_date: str
    value: float


class CompareTenor(BaseModel):
    country: str
    curve_set: str
    basis: str
    rate_type: str
    tenor: float
    points: list[SparkPoint]


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
    country: str
    curve_set: str
    basis: str
    rate_type: str
    frames: list[CurveMovieFrame]


def _split_countries(countries: str) -> list[str]:
    return [c.strip().upper() for c in countries.split(",") if c.strip()]


@router.get("/countries", response_model=list[Country])
def list_countries(gw: DbRatesGateway = Depends(_gateway)) -> list[dict]:
    return gw.countries()


@router.get("/curve/series", response_model=list[CurveSeries])
def list_curve_series(
    country: str | None = Query(None, description="ISO-2 filter; all countries if omitted"),
    gw: DbRatesGateway = Depends(_gateway),
) -> list[dict]:
    return gw.curve_sets(country)


@router.get("/curve/compare", response_model=list[CompareCurve])
def compare_curves(
    countries: str = Query(..., description="Comma ISO-2 list, e.g. GB,DE,US"),
    as_of_date: date | None = Query(None, description="As-of (latest per country if omitted)"),
    gw: DbRatesGateway = Depends(_gateway),
) -> list[dict]:
    return gw.compare_curves(_split_countries(countries), as_of_date=as_of_date)


@router.get("/curve/compare/tenor", response_model=list[CompareTenor])
def compare_tenor(
    countries: str = Query(..., description="Comma ISO-2 list, e.g. GB,DE,US"),
    tenor: float = Query(10.0, description="Tenor in years to compare across countries"),
    gw: DbRatesGateway = Depends(_gateway),
) -> list[dict]:
    return gw.compare_tenor(_split_countries(countries), tenor)


@router.get("/spreads", response_model=list[SpreadSummary])
def list_spreads(
    country: str = Query("GB", description="ISO-2 country"),
    gw: DbRatesGateway = Depends(_gateway),
) -> list[dict]:
    return gw.spreads(country)


@router.get("/spread/{key}", response_model=SpreadHistory)
def get_spread(
    key: str,
    window: str = Query("MAX", description="1Y | 5Y | MAX"),
    country: str = Query("GB", description="ISO-2 country"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.spread_history(key, window, country)


@router.get("/curve/movie", response_model=CurveMovie)
def get_curve_movie(
    country: str = Query("GB"),
    curve_set: str = Query("glc"),
    basis: str = Query("nominal"),
    rate_type: str = Query("spot"),
    frames: int = Query(120, ge=2, le=240, description="max frames sampled across the window"),
    start_date: date | None = Query(None, description="window start; full history if omitted"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.curve_movie(country, curve_set, basis, rate_type, frames, start_date)


@router.get("/curve", response_model=Curve)
def get_curve(
    country: str = Query("GB", description="ISO-2 country (GB/DE/EU/US/JP/...)"),
    curve_set: str = Query("glc", description="curve family: glc/ois (UK) | govt | irs"),
    basis: str = Query("nominal", description="nominal | real | inflation"),
    rate_type: str = Query("spot", description="spot | forward | par | yield"),
    as_of_date: date | None = Query(None, description="Curve as-of (latest if omitted)"),
    vintage: str = Query("latest", description="latest (restated) | first (first-published, PIT)"),
    gw: DbRatesGateway = Depends(_gateway),
) -> dict:
    return gw.curve(country, curve_set, basis, rate_type, as_of_date, vintage=vintage)
