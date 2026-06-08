"""``/api/sym`` router — the sym module's read endpoints (Q2.1 Overview)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query

from qrp_api.db import connect
from qrp_api.modules.sym.gateway import DEFAULT_HEATMAP_WINDOW, DbSymGateway

router = APIRouter(prefix="/api/sym", tags=["sym"])


def _gateway() -> Iterator[DbSymGateway]:
    conn = connect()
    try:
        yield DbSymGateway(conn)
    finally:
        conn.close()


@router.get("/health")
def health(gw: DbSymGateway = Depends(_gateway)) -> dict:
    return {"module": "sym", "healthy": gw.healthy()}


@router.get("/overview")
def overview(gw: DbSymGateway = Depends(_gateway)) -> dict:
    o = gw.overview()
    return {
        "securities": o.securities,
        "universes": o.universes,
        "priced_securities": o.priced_securities,
        "latest_session": o.latest_session.isoformat() if o.latest_session else None,
        "freshness": [
            {
                "area": f.area,
                "as_of": f.as_of.isoformat() if f.as_of else None,
                "days_behind": f.days_behind,
                "status": f.status,
            }
            for f in o.freshness
        ],
        "last_run": (
            {
                "run_id": o.last_run.run_id,
                "mode": o.last_run.mode,
                "status": o.last_run.status,
                "started_at": o.last_run.started_at.isoformat() if o.last_run.started_at else None,
                "finished_at": (
                    o.last_run.finished_at.isoformat() if o.last_run.finished_at else None
                ),
                "rows_written": o.last_run.rows_written,
            }
            if o.last_run
            else None
        ),
    }


@router.get("/universes")
def universes(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return [
        {"universe_id": u.universe_id, "name": u.name, "members_resolved": u.members_resolved}
        for u in gw.universes()
    ]


@router.get("/return-windows")
def return_windows(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return [{"code": code, "label": label} for code, label in gw.return_windows()]


@router.get("/universes/{universe_id}/heatmap")
def heatmap(
    universe_id: str,
    window: str = Query(default=DEFAULT_HEATMAP_WINDOW),
    gw: DbSymGateway = Depends(_gateway),
) -> dict:
    return gw.heatmap(universe_id, window)


@router.get("/securities")
def securities(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    gw: DbSymGateway = Depends(_gateway),
) -> dict:
    return gw.securities(q, limit, offset)


@router.get("/securities/{figi}")
def security_detail(figi: str, gw: DbSymGateway = Depends(_gateway)) -> dict:
    detail = gw.security_detail(figi)
    if detail is None:
        raise HTTPException(status_code=404, detail="security not found")
    return detail


@router.get("/attention")
def attention(gw: DbSymGateway = Depends(_gateway)) -> dict:
    return gw.attention()


@router.get("/validation")
def validation(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return gw.validation()


# (attention + validation endpoints added — Q2.4/2.5)
