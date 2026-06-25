"""Analytics boundaries (Story A.1, chunk-1 D7). DB-free.

The analytics module owns its URL namespace and reads weights through the
portfolios package — one owner per table, one prefix per toggle.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import qrp_api.main as main_mod
from qrp_api.main import create_app


def _route_paths(app=None) -> set[str]:
    app = app or create_app()
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_analytics_routes_live_under_their_own_prefix():
    paths = _route_paths()
    assert "/api/analytics/portfolios/{pid}" in paths
    assert "/api/analytics/benchmarks" in paths
    # the namespace squat is GONE: no analytics route under /api/portfolios/*
    assert "/api/portfolios/{pid}/analytics" not in paths


def test_analytics_toggle_off_removes_the_whole_namespace(monkeypatch):
    # The motivating defect class: an analytics route alive under another
    # module's namespace while toggles disagree. With analytics OFF, nothing
    # analytics-shaped may exist anywhere in the route table.
    import qrp_api.config as config_mod

    real = config_mod.enabled_modules()
    without = [m for m in real if m["key"] != "analytics"]
    monkeypatch.setattr(main_mod, "enabled_modules", lambda: without)
    paths = _route_paths(main_mod.create_app())
    assert not {p for p in paths if p.startswith("/api/analytics")}
    assert "/api/portfolios/{pid}/analytics" not in paths


def test_analytics_package_has_no_weight_sql():
    # AC2 is a PACKAGE claim — walk every source file, not one module.
    import analytics

    pkg_dir = Path(analytics.__file__).parent
    sources = list(pkg_dir.rglob("*.py"))
    assert sources, f"no analytics sources found under {pkg_dir}"
    offenders = [
        p.name for p in sources if "portfolio_weight" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    """Fake conn that RECORDS params so the contract test can prove the
    portfolio_id actually reaches the SQL (a hard-coded pid must fail)."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Cur(
            rows=[
                (date(2026, 6, 1), "BBG000000001", Decimal("0.6")),
                (date(2026, 6, 1), "BBG000000002", Decimal("0.4")),
            ]
        )


def test_read_latest_weights_contract():
    from portfolios.gateway import read_latest_weights

    conn = _Conn()
    as_of_date, weights = read_latest_weights(conn, 7)
    assert as_of_date == date(2026, 6, 1)
    assert weights == {"BBG000000001": Decimal("0.6"), "BBG000000002": Decimal("0.4")}
    # ONE statement (no torn read), and the pid reaches the SQL params.
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert params == (7, 7)
    assert sql.count("%s") == 2

    class _Empty(_Conn):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            return _Cur(rows=[])

    assert read_latest_weights(_Empty(), 7) == (None, {})


def test_portfolio_exists_contract():
    from portfolios.gateway import portfolio_exists

    class _Found(_Conn):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            return _Cur(one=(1,))

    conn = _Found()
    assert portfolio_exists(conn, 7) is True
    assert conn.calls[0][1] == (7,)

    class _Missing(_Conn):
        def execute(self, sql, params=None):
            return _Cur(one=None)

    assert portfolio_exists(_Missing(), 7) is False


def test_unknown_portfolio_is_404_weightless_is_200():
    # Nonexistent pid -> LookupError -> 404; existing-but-weightless keeps the
    # warning-body 200. Exercised at the gateway seam (DB-free).
    import pytest

    from analytics.gateway import DbAnalyticsGateway

    class _NoPortfolio(_Conn):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            return _Cur(one=None, rows=[])

    gw = DbAnalyticsGateway(_NoPortfolio(), _NoPortfolio(), _NoPortfolio())
    with pytest.raises(LookupError):
        gw.analytics(99999, 1, "ALL")

    class _Weightless(_Conn):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "FROM portfolios.portfolio WHERE" in sql:  # existence probe
                return _Cur(one=(1,))
            return _Cur(rows=[])  # portfolio_weight: nothing stored yet

    class _SymEmpty(_Conn):
        def execute(self, sql, params=None):
            return _Cur(one=None, rows=[])

    out = DbAnalyticsGateway(_Weightless(), _SymEmpty(), _SymEmpty()).analytics(7, 1, "ALL")
    assert out["warning"] == "no weights stored for this portfolio"
    assert out["metrics"] is None
