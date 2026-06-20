"""Benchmark-index endpoints (MSCI EOD pull story). Route-table + gateway parse, DB-free.

The index level data (e.g. MSCI World NR) is pulled into ``index_levels`` by ``sym msci-pull``;
these endpoints expose it read-only. The gateway is exercised with a fake conn (no DB) that
dispatches by SQL, mirroring the project's DB-free API test style.
"""

from __future__ import annotations

from datetime import date

from qrp_api.main import create_app
from qrp_api.modules.sym.gateway import DbSymGateway


def _route_paths() -> set[str]:
    return {r.path for r in create_app().routes if hasattr(r, "path")}


def test_index_routes_exist():
    paths = _route_paths()
    assert "/api/sym/indexes" in paths
    assert any(p.startswith("/api/sym/indexes/{sym_id}/levels") for p in paths)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Dispatches execute() by SQL fragment to canned rows (no DB)."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN index_levels l" in s:  # gateway.indexes() list query
            return _Result(
                [
                    (2210, "MSCI World Net (USD)", "USD", "990100:NETR", 6646,
                     date(2000, 12, 29), date(2026, 6, 19), 11731.17),
                ]
            )
        if "SELECT session_date, level FROM index_levels" in s:  # series
            return _Result([(date(2000, 12, 29), 2487.61), (date(2026, 6, 19), 11731.17)])
        if "FROM instrument i WHERE i.sym_id" in s:  # series meta
            return _Result([("MSCI World Net (USD)", "USD", "990100:NETR")])
        return _Result([])


def test_indexes_lists_with_variant_split():
    gw = DbSymGateway(_FakeConn())
    out = gw.indexes()
    assert out == [
        {
            "sym_id": 2210, "name": "MSCI World Net (USD)", "currency": "USD",
            "msci_code": "990100", "variant": "NETR", "n_levels": 6646,
            "first_date": "2000-12-29", "last_date": "2026-06-19", "last_level": 11731.17,
        }
    ]


def test_index_levels_series_and_since_start_return():
    gw = DbSymGateway(_FakeConn())
    out = gw.index_levels(2210)
    assert out["sym_id"] == 2210
    assert out["msci_code"] == "990100" and out["variant"] == "NETR"
    assert out["n_levels"] == 2
    assert out["series"][0] == {"date": "2000-12-29", "level": 2487.61}
    # since-start return = last/first - 1
    assert abs(out["since_start_return"] - (11731.17 / 2487.61 - 1.0)) < 1e-9
