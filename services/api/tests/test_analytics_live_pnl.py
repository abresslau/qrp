"""Live portfolio PnL (Story QH.2, Part B). DB-free — the portfolios seam + the quote fetch
are monkeypatched; the sym conn is faked. Asserts the coverage-honest weighted sum, the
freshness/as_of roll-up, the missing-portfolio 404, and the whole-source 503."""

from __future__ import annotations

from datetime import date, timezone, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from analytics import gateway as gw_mod
from analytics import quotes
from analytics import router as router_mod
from analytics.gateway import DbAnalyticsGateway
from analytics.quotes import QuoteSourceUnreachable, RawQuote


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _SymConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return _Cur(self._rows)


def _wire(monkeypatch, *, weights, terms=(Decimal("1000000"), "USD"), exists=True):
    monkeypatch.setattr(gw_mod, "portfolio_exists", lambda conn, pid: exists)
    monkeypatch.setattr(gw_mod, "read_latest_weights", lambda conn, pid: (date(2026, 6, 1), weights))
    monkeypatch.setattr(gw_mod, "read_portfolio_terms", lambda conn, pid: terms)


_EPOCH = 1781553601


def test_live_pnl_weighted_sum_with_partial_coverage(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("0.6"), "F2": Decimal("0.4")})
    sym = _SymConn([("F1", "AAPL", "XNAS"), ("F2", "PETR4", "BVMF")])

    def fake_fetch(ysym, **kw):
        if ysym == "AAPL":
            return RawQuote(price=110.0, prev_close=100.0, currency="USD", quote_epoch=_EPOCH)
        return None  # PETR4.SA: reachable but no data -> uncovered

    monkeypatch.setattr(quotes, "fetch_raw_quote", fake_fetch)
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).live_pnl(1, now=_EPOCH + 10)

    assert out["n_constituents"] == 2 and out["n_priced"] == 1
    assert out["total_weight"] == pytest.approx(1.0)
    assert out["covered_weight"] == pytest.approx(0.6)
    assert out["live_return"] == pytest.approx(0.6 * 0.10)             # Σ w·r (signed)
    assert out["live_return_normalized"] == pytest.approx(0.10)        # / covered |w|
    assert out["pnl"] == pytest.approx(1_000_000 * 0.10)              # notional × normalized
    assert out["freshness"] == "live"                                  # the one priced name is fresh
    assert out["as_of"] == datetime.fromtimestamp(_EPOCH, tz=timezone.utc).isoformat()
    # most-contributing constituent first
    assert out["constituents"][0]["figi"] == "F1"


def test_live_pnl_delayed_when_a_priced_name_is_stale(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "AAPL", "XNAS")])
    monkeypatch.setattr(
        quotes, "fetch_raw_quote",
        lambda ysym, **kw: RawQuote(110.0, 100.0, "USD", _EPOCH),
    )
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).live_pnl(1, now=_EPOCH + 600)
    assert out["freshness"] == "delayed"


def test_live_pnl_priced_but_timeless_quote_is_delayed_not_live(monkeypatch):
    # A priced quote with no regularMarketTime must NOT paint the portfolio 'live'
    # (it has no proof of freshness). classify_freshness(None) -> 'delayed'.
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "AAPL", "XNAS")])
    monkeypatch.setattr(
        quotes, "fetch_raw_quote",
        lambda ysym, **kw: RawQuote(110.0, 100.0, "USD", None),  # priced, no timestamp
    )
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).live_pnl(1, now=_EPOCH)
    assert out["n_priced"] == 1
    assert out["freshness"] == "delayed"           # never 'live' without a fresh stamp
    assert out["as_of"] is None                    # no epoch to anchor as_of
    assert out["constituents"][0]["freshness"] == "delayed"  # vocabulary stays live/delayed/unavailable


def test_live_pnl_all_unreachable_raises(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("0.5"), "F2": Decimal("0.5")})
    sym = _SymConn([("F1", "AAPL", "XNAS"), ("F2", "MSFT", "XNAS")])

    def boom(ysym, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_raw_quote", boom)
    with pytest.raises(QuoteSourceUnreachable):
        DbAnalyticsGateway(conn=object(), sym_conn=sym).live_pnl(1, now=_EPOCH)


def test_live_pnl_no_weights_is_empty(monkeypatch):
    _wire(monkeypatch, weights={})
    out = DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).live_pnl(1, now=_EPOCH)
    assert out["n_constituents"] == 0 and out["live_return_normalized"] is None
    assert out["pnl"] is None and out["freshness"] == "unavailable"


def test_route_missing_portfolio_404(monkeypatch):
    _wire(monkeypatch, weights={}, exists=False)

    class _Gw:
        def live_pnl(self, pid):
            return DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).live_pnl(pid)

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_live(pid=999, gw=_Gw())
    assert exc.value.status_code == 404


def test_route_maps_unreachable_to_503():
    class _Gw:
        def live_pnl(self, pid):
            raise QuoteSourceUnreachable("down")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_live(pid=1, gw=_Gw())
    assert exc.value.status_code == 503
    assert "quote provider unreachable" in exc.value.detail
