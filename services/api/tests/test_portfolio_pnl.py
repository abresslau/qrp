"""Daily/MTD/YTD P&L summary (analytics.gateway.pnl_summary). DB-free: the portfolios seam and
the EOD daily-return series are monkeypatched. Asserts the month/year boundaries, the notional →
money mapping, the empty series, and the 404 route mapping."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from analytics import gateway as gw_mod
from analytics import router as router_mod
from analytics.gateway import DbAnalyticsGateway

# A series straddling a year boundary (2025 vs 2026) and a month boundary (May vs June 2026).
SERIES = {
    date(2025, 12, 31): 0.10,  # prior YEAR — excluded from YTD
    date(2026, 1, 15): 0.05,
    date(2026, 5, 30): 0.02,   # prior MONTH — excluded from MTD
    date(2026, 6, 10): 0.03,
    date(2026, 6, 18): 0.0164,  # latest session — the "Daily"
}


def _wire(monkeypatch, *, terms, series=SERIES, exists=True):
    monkeypatch.setattr(gw_mod, "portfolio_exists", lambda conn, pid: exists)
    monkeypatch.setattr(gw_mod, "read_portfolio_terms", lambda conn, pid: terms)
    last = max(series) if series else None
    monkeypatch.setattr(
        DbAnalyticsGateway, "_portfolio_daily",
        lambda self, pid: (last, dict(series), {}, ["USD"], []),
    )


def _gw():
    return DbAnalyticsGateway(conn=object(), sym_conn=object())


def test_pnl_daily_mtd_ytd_boundaries(monkeypatch):
    _wire(monkeypatch, terms=(None, "USD"))
    out = _gw().pnl_summary(7)
    assert out["as_of_date"] == "2026-06-18" and out["n_days"] == 5
    assert out["daily_return"] == pytest.approx(0.0164)
    # MTD = June only: (1.03)(1.0164) − 1
    assert out["mtd_return"] == pytest.approx(1.03 * 1.0164 - 1)
    # YTD = 2026 only (Dec-2025 excluded): (1.05)(1.02)(1.03)(1.0164) − 1
    assert out["ytd_return"] == pytest.approx(1.05 * 1.02 * 1.03 * 1.0164 - 1)
    # no notional → return-space only
    assert out["daily_pnl"] is None and out["mtd_pnl"] is None and out["ytd_pnl"] is None


def test_pnl_money_when_notional_set(monkeypatch):
    _wire(monkeypatch, terms=(Decimal("1000000"), "USD"))
    out = _gw().pnl_summary(7)
    assert out["notional"] == 1_000_000 and out["base_currency"] == "USD"
    assert out["daily_pnl"] == pytest.approx(1_000_000 * 0.0164)
    assert out["ytd_pnl"] == pytest.approx(1_000_000 * (1.05 * 1.02 * 1.03 * 1.0164 - 1))


def test_pnl_empty_series_is_all_null(monkeypatch):
    _wire(monkeypatch, terms=(None, "USD"), series={})
    out = _gw().pnl_summary(7)
    assert out["n_days"] == 0 and out["as_of_date"] is None
    assert out["daily_return"] is None and out["mtd_return"] is None and out["ytd_return"] is None


def test_route_missing_portfolio_404():
    class _Gw:
        def pnl_summary(self, pid):
            raise LookupError("portfolio 999 not found")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_pnl(pid=999, gw=_Gw())
    assert exc.value.status_code == 404
