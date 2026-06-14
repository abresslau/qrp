"""Category guards (Story C.1): catalog declarations + gateway reads. DB-free."""

from __future__ import annotations

from datetime import date

import pytest

import macro.ingest as ingest
from macro.gateway import DbMacroGateway


def test_every_catalog_entry_declares_a_canonical_category():
    declared = (
        [cat for _, _, _, cat, _, _ in ingest._WB]
        + [cat for _, _, _, _, _, cat in ingest._ECB]
        + [cat for _, _, _, _, _, cat in ingest._EUROSTAT]
    )
    assert declared, "catalogs unexpectedly empty"
    assert set(declared) <= set(ingest.CATEGORIES)
    # the fetcher-built series declare theirs at the run_ingest call sites — covered by
    # test_run_ingest_attaches_declared_categories (params inspected at the SQL boundary)


def test_canonical_categories_are_url_safe_slugs():
    # they appear verbatim in console paths (/macro/<category>)
    for cat in ingest.CATEGORIES:
        assert cat == cat.lower() and cat.isalpha(), cat


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, rows_by_marker):
        self._rows_by_marker = rows_by_marker
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        for marker, rows in self._rows_by_marker.items():
            if marker in sql:
                return _Cursor(rows)
        return _Cursor([])


def test_gateway_categories_reads_distinct_non_null_from_db():
    conn = _Conn({"GROUP BY category": [("inflation", 9), ("rates", 6)]})
    out = DbMacroGateway(conn).categories()
    assert out == [
        {"category": "inflation", "n_series": 9},
        {"category": "rates", "n_series": 6},
    ]
    sql = conn.sql[0]
    assert "category IS NOT NULL" in sql  # uncategorised series never become submenu items
    assert "ORDER BY category" in sql


def test_gateway_series_carries_category_and_enrichment():
    # row shape: ...meta..., n_obs, first, last, latest, v_1m, v_3m, v_12m, v_ye, spark
    row = ("WB:X:US", "worldbank", "n", "g", "u", "annual", "gdp",
           3, date(2023, 12, 31), date(2025, 12, 31), 1.5, 1.4, 1.3, 1.0, 0.9, [1.0, 1.2, 1.5])
    conn = _Conn({"array_agg": [row]})  # marker unique to the enriched series() query
    out = DbMacroGateway(conn).series()[0]
    assert out["category"] == "gdp"
    assert out["latest"] == 1.5
    assert out["chg_1m"] == pytest.approx(0.1)  # latest - v_1m
    assert out["chg_12m"] == pytest.approx(0.5)  # latest - v_12m
    assert out["chg_ytd"] == pytest.approx(0.6)  # latest - prior year-end
    assert out["spark"] == [1.0, 1.2, 1.5]
