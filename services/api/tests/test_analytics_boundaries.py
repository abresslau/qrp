"""Analytics boundaries (Story A.1, chunk-1 D7). DB-free.

The analytics module owns its URL namespace and reads weights through the
portfolios package — one owner per table, one prefix per toggle.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal


from qrp_api.main import create_app


def _route_paths() -> set[str]:
    app = create_app()
    return {r.path for r in app.routes if hasattr(r, "path")}


def test_analytics_routes_live_under_their_own_prefix():
    paths = _route_paths()
    assert "/api/analytics/portfolios/{pid}" in paths
    assert "/api/analytics/benchmarks" in paths
    # the namespace squat is GONE: no analytics route under /api/portfolios/*
    assert "/api/portfolios/{pid}/analytics" not in paths


def test_analytics_package_has_no_weight_sql():
    import inspect

    import analytics.gateway as ag

    assert "portfolio_weight" not in inspect.getsource(ag)


def test_read_latest_weights_contract():
    from portfolios.gateway import read_latest_weights

    class _Cur:
        def __init__(self, one=None, rows=None):
            self._one, self._rows = one, rows or []

        def fetchone(self):
            return self._one

        def fetchall(self):
            return self._rows

    class _Conn:
        def execute(self, sql, params=None):
            if "max(as_of_date)" in sql:
                return _Cur(one=(date(2026, 6, 1),))
            return _Cur(rows=[("BBG000000001", Decimal("0.6")),
                              ("BBG000000002", Decimal("0.4"))])

    as_of_date, weights = read_latest_weights(_Conn(), 7)
    assert as_of_date == date(2026, 6, 1)
    assert weights == {"BBG000000001": Decimal("0.6"), "BBG000000002": Decimal("0.4")}

    class _Empty(_Conn):
        def execute(self, sql, params=None):
            return _Cur(one=(None,))

    assert read_latest_weights(_Empty(), 7) == (None, {})
