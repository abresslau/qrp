"""``/api/signals`` — derived cross-sectional factors (momentum, low-vol, size) over universes."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from signals.db import connect
from signals.gateway import DbSignalGateway

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _gateway() -> Iterator[DbSignalGateway]:
    conn = connect()  # signal owns its own database (DB-per-package topology)
    try:
        sym = connect("sym")               # sym package — security labels, enriched in-app by the gateway
    except Exception:
        conn.close()  # don't leak the first connection when the second connect fails
        raise
    try:
        yield DbSignalGateway(conn, sym)
    finally:
        conn.close()
        sym.close()


class FactorSummary(BaseModel):
    factor_key: str
    name: str
    description: str | None
    direction: str
    universes: int
    scores: int
    as_of_date: str | None


class FactorConstituent(BaseModel):
    ticker: str
    name: str | None
    raw: float
    zscore: float | None
    rank: int
    pctile: float | None


class FactorRanking(BaseModel):
    factor_key: str
    name: str
    description: str | None
    direction: str
    universe_id: str
    as_of_date: str | None
    bottom: bool
    constituents: list[FactorConstituent]


@router.get("/factors", response_model=list[FactorSummary])
def list_factors(gw: DbSignalGateway = Depends(_gateway)) -> list[dict]:
    return gw.factors()


@router.get("/factors/{factor_key}", response_model=FactorRanking)
def factor_ranking(
    factor_key: str,
    universe: str = Query(..., description="universe_id, e.g. sp500 | ibov | ibx"),
    limit: int = Query(default=25, ge=1, le=200),
    bottom: bool = Query(default=False, description="show least-favourable end instead of top"),
    gw: DbSignalGateway = Depends(_gateway),
) -> dict:
    d = gw.ranked(factor_key, universe, limit, bottom)
    if d is None:
        raise HTTPException(status_code=404, detail="no scores for this factor/universe")
    return d
