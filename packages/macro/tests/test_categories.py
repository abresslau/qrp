"""Category guards (Story C.1): catalog declarations + gateway reads. DB-free."""

from __future__ import annotations

from datetime import date

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


def test_gateway_series_carries_category():
    row = ("WB:X:US", "worldbank", "n", "g", "u", "annual", "gdp",
           3, date(2023, 12, 31), date(2025, 12, 31), 1.5)
    conn = _Conn({"LEFT JOIN macro.observation": [row]})
    out = DbMacroGateway(conn).series()
    assert out[0]["category"] == "gdp"
