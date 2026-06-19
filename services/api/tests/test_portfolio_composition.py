"""Live portfolio composition — the heat-map (sized by position size) + sector/position pizza
surface (story portfolios-live-heatmap-and-pizza). DB-free: the portfolios seam is monkeypatched,
the sym conn is faked, the quote fan-out is monkeypatched. Asserts the per-holding cell shape with
SIGNED weights preserved, the per-sector |weight| rollup (slice size + weighted live return), the
honest freshness/coverage roll-up, the writes-nothing property, and the 404/422/503 mappings.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
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
    """Fake sym read conn — returns the SAME meta rows for any query, and RECORDS the SQL it
    sees so a test can assert the live path issues no INSERT/UPDATE."""

    def __init__(self, rows):
        self._rows = rows
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        return _Cur(self._rows)


def _wire(monkeypatch, *, weights, exists=True):
    monkeypatch.setattr(gw_mod, "portfolio_exists", lambda conn, pid: exists)
    monkeypatch.setattr(gw_mod, "read_latest_weights", lambda conn, pid: (date(2026, 6, 1), weights))


_EPOCH = 1781553601


def test_composition_assembly_signed_weight_and_sector_rollup(monkeypatch):
    # One long (priced) IT name + one short (uncovered) Energy name.
    _wire(monkeypatch, weights={"F1": Decimal("0.6"), "F2": Decimal("-0.2")})
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Information Technology", "Tech HW", "Apple Inc", "USD"),
        ("F2", "PETR4", "BVMF", "Energy", "Oil & Gas", "Petrobras", "BRL"),
    ])

    def fake_batch(symbols, **kw):
        return {
            "AAPL": RawQuote(price=110.0, prev_close=100.0, currency="USD", quote_epoch=_EPOCH),
            "PETR4.SA": None,  # reachable, no data -> uncovered
        }

    monkeypatch.setattr(quotes, "fetch_quotes_batch", fake_batch)
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH + 10)

    assert out["n_holdings"] == 2 and out["n_priced"] == 1
    assert out["total_weight"] == pytest.approx(0.8)   # |0.6| + |-0.2|
    assert out["net_weight"] == pytest.approx(0.4)     # 0.6 + (-0.2)
    assert out["freshness"] == "live"
    assert out["as_of"] == datetime.fromtimestamp(_EPOCH, tz=timezone.utc).isoformat()

    # holdings sorted by position SIZE (|weight|) desc: F1 (0.6) before F2 (0.2)
    h0, h1 = out["holdings"]
    assert h0["figi"] == "F1"
    assert h0["weight"] == pytest.approx(0.6) and h0["live_return"] == pytest.approx(0.10)
    assert h0["sector"] == "Information Technology" and h0["name"] == "Apple Inc"
    assert h0["freshness"] == "live" and h0["price"] == pytest.approx(110.0)
    assert h1["figi"] == "F2"
    assert h1["weight"] == pytest.approx(-0.2)          # SIGN preserved (short)
    assert h1["live_return"] is None and h1["freshness"] == "unavailable"

    # sector slices: Σ|weight| per sector, summing to gross; uncovered sector return is None
    secs = {s["sector"]: s for s in out["sectors"]}
    assert secs["Information Technology"]["weight"] == pytest.approx(0.6)
    assert secs["Information Technology"]["live_return"] == pytest.approx(0.10)
    assert secs["Energy"]["weight"] == pytest.approx(0.2)
    assert secs["Energy"]["live_return"] is None
    assert sum(s["weight"] for s in out["sectors"]) == pytest.approx(out["total_weight"])


def test_composition_sector_return_is_weight_weighted(monkeypatch):
    # Two priced holdings in ONE sector with different returns -> |weight|-weighted rollup.
    _wire(monkeypatch, weights={"F1": Decimal("0.6"), "F3": Decimal("0.4")})
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD"),
        ("F3", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD"),
    ])
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {
        "AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH),   # +10%
        "MSFT": RawQuote(120.0, 100.0, "USD", _EPOCH),   # +20%
    })
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    tech = next(s for s in out["sectors"] if s["sector"] == "Tech")
    # (0.6*0.10 + 0.4*0.20) / (0.6 + 0.4) = 0.14
    assert tech["live_return"] == pytest.approx(0.14)


def test_composition_unmapped_mic_is_unavailable(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "FOO", "XZZZ", "Unclassified", None, "Foo Co", None)])  # XZZZ unmapped
    monkeypatch.setattr(quotes, "fetch_quotes_batch", lambda s, **kw: {})
    out = DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    assert out["n_priced"] == 0 and out["freshness"] == "unavailable"
    assert out["holdings"][0]["live_return"] is None
    assert out["holdings"][0]["freshness"] == "unavailable"


def test_composition_all_unreachable_raises(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("0.5"), "F2": Decimal("0.5")})
    sym = _SymConn([
        ("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD"),
        ("F2", "MSFT", "XNAS", "Tech", None, "Microsoft", "USD"),
    ])

    def boom(symbols, **kw):
        raise QuoteSourceUnreachable("down")

    monkeypatch.setattr(quotes, "fetch_quotes_batch", boom)
    with pytest.raises(QuoteSourceUnreachable):
        DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)


def test_composition_no_weights_is_empty(monkeypatch):
    _wire(monkeypatch, weights={})
    out = DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).composition(1, now=_EPOCH)
    assert out["n_holdings"] == 0 and out["n_priced"] == 0
    assert out["holdings"] == [] and out["sectors"] == []
    assert out["freshness"] == "unavailable" and out["total_weight"] == 0.0


def test_composition_over_cap_raises_value_error(monkeypatch):
    big = {f"F{i}": Decimal("0.001") for i in range(gw_mod.COMPOSITION_MAX + 1)}
    _wire(monkeypatch, weights=big)
    with pytest.raises(ValueError):
        DbAnalyticsGateway(conn=object(), sym_conn=_SymConn([])).composition(1, now=_EPOCH)


def test_composition_writes_nothing(monkeypatch):
    _wire(monkeypatch, weights={"F1": Decimal("1.0")})
    sym = _SymConn([("F1", "AAPL", "XNAS", "Tech", None, "Apple", "USD")])
    monkeypatch.setattr(quotes, "fetch_quotes_batch",
                        lambda s, **kw: {"AAPL": RawQuote(110.0, 100.0, "USD", _EPOCH)})
    DbAnalyticsGateway(conn=object(), sym_conn=sym).composition(1, now=_EPOCH)
    joined = " ".join(sym.seen).upper()
    assert "INSERT" not in joined and "UPDATE" not in joined and "DELETE" not in joined


def test_route_missing_portfolio_404():
    class _Gw:
        def composition(self, pid):
            raise LookupError("portfolio 999 not found")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=999, gw=_Gw())
    assert exc.value.status_code == 404


def test_route_over_cap_422():
    class _Gw:
        def composition(self, pid):
            raise ValueError("portfolio too large for a live composition")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=1, gw=_Gw())
    assert exc.value.status_code == 422


def test_route_maps_unreachable_to_503():
    class _Gw:
        def composition(self, pid):
            raise QuoteSourceUnreachable("down")

    with pytest.raises(HTTPException) as exc:
        router_mod.portfolio_composition(pid=1, gw=_Gw())
    assert exc.value.status_code == 503
    assert "quote provider unreachable" in exc.value.detail
