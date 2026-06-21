"""FX cross-rate matrix endpoint + gateway. DB-free (a fake conn dispatches the fx_rate as-of query
and the latest-date query), mirroring the project's DB-free API test style.

The matrix is derived from the USD-base ``fx_rate`` star: cell(base, quote) = quote_rate / base_rate
(both per-USD), diagonal 1.0. A currency whose as-of resolution is stale/no_data yields null cells.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from qrp_api.main import create_app
from qrp_api.modules.sym.gateway import DbSymGateway


def _route_paths() -> set[str]:
    return {r.path for r in create_app().routes if hasattr(r, "path")}


def test_fx_matrix_route_exists():
    assert "/api/sym/fx/matrix" in _route_paths()


class _FxConn:
    """Fake conn: latest-date query + the per-currency fx_rate as-of lookup (returns the latest
    observation ≤ the as-of param, so the matrix's prior-session resolution works). USD short-circuits
    in fx_rate. EUR/JPY have a prior + current obs (→ a daily move); XXX is stale (one old obs)."""

    AS_OF = date(2026, 6, 18)
    OBS = {
        "EUR": [(date(2026, 6, 17), Decimal("0.93")), (date(2026, 6, 18), Decimal("0.92"))],
        "JPY": [(date(2026, 6, 17), Decimal("154.0")), (date(2026, 6, 18), Decimal("155.0"))],
        "XXX": [(date(2026, 6, 1), Decimal("3.0"))],  # 17 days before as-of → beyond the 7d cap
    }

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "max(as_of_date) FROM fx_rate" in s:
            return _Result([(self.AS_OF,)])
        if "SELECT as_of_date, rate FROM fx_rate" in s:
            ccy, as_of = params[0], params[1]
            obs = [o for o in self.OBS.get(ccy, []) if o[0] <= as_of]  # latest ≤ as_of (DESC)
            return _Result([max(obs)] if obs else [])
        return _Result([])


def test_fx_matrix_cross_diagonal_and_stale():
    out = DbSymGateway(_FxConn()).fx_matrix(["USD", "EUR", "JPY", "XXX"])
    assert out["currencies"] == ["USD", "EUR", "JPY", "XXX"]
    assert out["as_of_date"] == "2026-06-18"  # defaulted to the latest fx_rate date

    by_meta = {m["currency"]: m for m in out["meta"]}
    assert by_meta["USD"]["status"] == "ok"  # the star base
    assert by_meta["EUR"]["status"] == "ok" and by_meta["EUR"]["observed_date"] == "2026-06-18"
    assert by_meta["XXX"]["status"] == "stale"  # 17 days > 7d outage cap
    # quoting precedence surfaced (EUR outranks USD; an unknown sinks below)
    assert by_meta["EUR"]["quote_rank"] < by_meta["USD"]["quote_rank"]
    assert by_meta["XXX"]["quote_rank"] > by_meta["USD"]["quote_rank"]

    grid = {r["base"]: r["cells"] for r in out["rows"]}
    idx = {c: i for i, c in enumerate(out["currencies"])}

    def cell(base, quote):
        return grid[base][idx[quote]]

    # diagonal = 1.0
    assert cell("USD", "USD")["rate"] == 1.0 and cell("EUR", "EUR")["rate"] == 1.0
    # USD->EUR = EUR per 1 USD = 0.92; EUR->USD = reciprocal
    assert abs(cell("USD", "EUR")["rate"] - 0.92) < 1e-9
    assert abs(cell("EUR", "USD")["rate"] - (1 / 0.92)) < 1e-9
    # EUR->JPY = JPY_rate / EUR_rate = 155 / 0.92 (JPY per 1 EUR)
    assert abs(cell("EUR", "JPY")["rate"] - (155.0 / 0.92)) < 1e-9
    # the daily move (heat map): cross now vs the prior session
    assert cell("USD", "USD")["chg"] == 0.0  # diagonal
    # USD->EUR: EUR moved 0.93 -> 0.92 per USD -> cross 0.92/0.93 - 1 (negative, EUR weaker -> red)
    assert abs(cell("USD", "EUR")["chg"] - (0.92 / 0.93 - 1)) < 1e-9
    # EUR->JPY: (155/0.92) / (154/0.93) - 1 (positive -> green)
    assert abs(cell("EUR", "JPY")["chg"] - ((155.0 / 0.92) / (154.0 / 0.93) - 1)) < 1e-9
    # each cell carries the conventional pair direction (EUR outranks USD -> EUR/USD both ways)
    assert cell("USD", "EUR")["pair"] == "EUR/USD" and cell("EUR", "USD")["pair"] == "EUR/USD"
    # any cell touching the stale XXX leg is null + flagged (never a fabricated cross), no chg
    assert cell("EUR", "XXX")["rate"] is None and cell("EUR", "XXX")["stale"] is True
    assert cell("EUR", "XXX")["chg"] is None
    assert cell("XXX", "JPY")["rate"] is None and cell("XXX", "JPY")["stale"] is True


def test_fx_matrix_route_returns_grid_shape():
    from qrp_api.modules.sym.router import _gateway

    class _Gw:
        def fx_matrix(self, currencies=None, as_of_date=None):
            return {
                "as_of_date": "2026-06-18",
                "currencies": ["USD", "EUR"],
                "meta": [
                    {"currency": "USD", "status": "ok", "observed_date": "2026-06-18", "days_stale": 0, "quote_rank": 50},
                    {"currency": "EUR", "status": "ok", "observed_date": "2026-06-18", "days_stale": 0, "quote_rank": 10},
                ],
                "rows": [
                    {"base": "USD", "cells": [
                        {"rate": 1.0, "chg": 0.0, "stale": False, "pair": "USD/USD"},
                        {"rate": 0.92, "chg": -0.011, "stale": False, "pair": "EUR/USD"},
                    ]},
                    {"base": "EUR", "cells": [
                        {"rate": 1.087, "chg": 0.011, "stale": False, "pair": "EUR/USD"},
                        {"rate": 1.0, "chg": 0.0, "stale": False, "pair": "EUR/EUR"},
                    ]},
                ],
            }

    app = create_app()
    app.dependency_overrides[_gateway] = lambda: _Gw()
    client = TestClient(app)
    ok = client.get("/api/sym/fx/matrix")
    assert ok.status_code == 200
    body = ok.json()
    assert body["currencies"] == ["USD", "EUR"]
    assert body["rows"][0]["cells"][1]["rate"] == 0.92
    # a bad as_of_date is a 422, not a 500
    assert client.get("/api/sym/fx/matrix", params={"as_of_date": "nope"}).status_code == 422
    app.dependency_overrides.clear()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows
