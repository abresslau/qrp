"""``/api/sym`` router — the sym module's read endpoints (Q2.1 Overview)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from qrp_api.db import connect
from qrp_api.modules.sym.gateway import DEFAULT_HEATMAP_WINDOW, DbSymGateway
from qrp_api.modules.sym.quotes import QuoteSourceUnreachable

router = APIRouter(prefix="/api/sym", tags=["sym"])


def _gateway() -> Iterator[DbSymGateway]:
    conn = connect()
    try:
        yield DbSymGateway(conn)
    finally:
        conn.close()


# ---- response models (typed seam: OpenAPI -> generated TS types carry real shapes) ----
class SymHealth(BaseModel):
    module: str
    healthy: bool


class FreshnessItem(BaseModel):
    area: str
    as_of_date: str | None
    days_behind: int | None
    status: str


class LastRun(BaseModel):
    run_id: str | None
    mode: str | None
    status: str | None
    started_at: str | None
    finished_at: str | None
    rows_written: int | None


class SymOverview(BaseModel):
    securities: int
    universes: int
    priced_securities: int
    latest_session: str | None
    freshness: list[FreshnessItem]
    last_run: LastRun | None


class UniverseSummary(BaseModel):
    universe_id: str
    name: str | None
    members_resolved: int


class ReturnWindow(BaseModel):
    code: str
    label: str


class HeatmapCell(BaseModel):
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap_usd: float
    market_cap_lcy: float | None
    currency: str | None
    price: float | None
    ret: float | None


class Heatmap(BaseModel):
    universe_id: str
    universe_name: str | None
    window: str
    members_resolved: int
    shown: int
    missing_mcap: int
    merged_share_classes: int
    cells: list[HeatmapCell]


class SecurityRow(BaseModel):
    figi: str
    ticker: str
    name: str | None
    mic: str | None
    currency: str | None
    status: str | None


class SecuritiesPage(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[SecurityRow]


class PriceInfo(BaseModel):
    close: float | None
    session_date: str | None


class FundamentalsInfo(BaseModel):
    market_cap_lcy: float | None
    market_cap_usd: float | None
    shares_outstanding: float | None
    currency: str | None
    as_of_date: str | None


class WindowReturn(BaseModel):
    code: str
    label: str | None
    pr: float | None
    tr: float | None
    as_of_date: str | None


class SecurityDetail(BaseModel):
    figi: str
    ticker: str
    name: str | None
    mic: str | None
    currency: str | None
    status: str | None
    delist_date: str | None
    sector: str | None
    industry: str | None
    sub_industry: str | None
    price: PriceInfo
    fundamentals: FundamentalsInfo | None
    returns: list[WindowReturn]


class ReviewItem(BaseModel):
    review_id: str
    source_key: str | None
    source_input: str | None
    status: str | None
    created_at: str | None


class PriceGap(BaseModel):
    figi: str
    ticker: str | None
    session_date: str | None
    source: str | None
    detected_at: str | None


class PriceGaps(BaseModel):
    total: int
    recent: list[PriceGap]


class MembershipProposal(BaseModel):
    proposal_id: str
    universe_id: str | None
    raw_identifier: str | None
    change: str | None
    status: str | None
    created_at: str | None


class Attention(BaseModel):
    review_queue: list[ReviewItem]
    price_gaps: PriceGaps
    membership_proposals: list[MembershipProposal]


class Quote(BaseModel):
    """A live/delayed quote — best-effort, NOT persisted (Story QH.2). `live_return` is the
    price return vs the quote's own previous close; `freshness` ∈ live|delayed|unavailable."""

    figi: str
    ticker: str | None
    yahoo_symbol: str | None
    price: float | None
    prev_close: float | None
    live_return: float | None
    currency: str | None
    quote_time: str | None
    freshness: str
    age_seconds: int | None


class ValidationRun(BaseModel):
    run_id: str
    run_at: str | None
    universe_id: str | None
    checks: int | None
    passed: int | None
    warned: int | None
    failed: int | None
    status: str | None


@router.get("/health", response_model=SymHealth)
def sym_health(gw: DbSymGateway = Depends(_gateway)) -> dict:
    return {"module": "sym", "healthy": gw.healthy()}


@router.get("/overview", response_model=SymOverview)
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
                "as_of_date": f.as_of_date.isoformat() if f.as_of_date else None,
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


@router.get("/universes", response_model=list[UniverseSummary])
def universes(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return [
        {"universe_id": u.universe_id, "name": u.name, "members_resolved": u.members_resolved}
        for u in gw.universes()
    ]


@router.get("/return-windows", response_model=list[ReturnWindow])
def return_windows(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return [{"code": code, "label": label} for code, label in gw.return_windows()]


@router.get("/universes/{universe_id}/heatmap", response_model=Heatmap)
def heatmap(
    universe_id: str,
    window: str = Query(default=DEFAULT_HEATMAP_WINDOW),
    gw: DbSymGateway = Depends(_gateway),
) -> dict:
    try:
        return gw.heatmap(universe_id, window)
    except LookupError as exc:  # unknown universe
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:  # unknown return window
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/securities", response_model=SecuritiesPage)
def securities(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    gw: DbSymGateway = Depends(_gateway),
) -> dict:
    return gw.securities(q, limit, offset)


@router.get("/securities/{figi}", response_model=SecurityDetail)
def security_detail(figi: str, gw: DbSymGateway = Depends(_gateway)) -> dict:
    detail = gw.security_detail(figi)
    if detail is None:
        raise HTTPException(status_code=404, detail="security not found")
    return detail


@router.get("/quotes", response_model=list[Quote])
def quotes(
    figis: str = Query(..., description="comma-separated composite FIGIs (1..50)"),
    gw: DbSymGateway = Depends(_gateway),
) -> list[dict]:
    """Live/delayed quotes (Story QH.2). External fetch at serve time — degrades to the honest
    503 envelope if the provider is wholly unreachable; a per-symbol miss is an `unavailable`
    row, never a request failure. Nothing is persisted."""
    ids = [f.strip() for f in figis.split(",") if f.strip()]
    if not ids or len(ids) > 50:
        raise HTTPException(status_code=422, detail="figis must be 1..50 comma-separated FIGIs")
    try:
        return gw.quotes(ids)
    except QuoteSourceUnreachable as exc:
        raise HTTPException(status_code=503, detail=f"quote provider unreachable: {exc}") from exc


@router.get("/attention", response_model=Attention)
def attention(gw: DbSymGateway = Depends(_gateway)) -> dict:
    return gw.attention()


@router.get("/validation", response_model=list[ValidationRun])
def validation(gw: DbSymGateway = Depends(_gateway)) -> list[dict]:
    return gw.validation()


# (attention + validation endpoints added — Q2.4/2.5)
