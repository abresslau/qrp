"""Maintenance-plan coverage check (Story U3.6, ledger D4). DB-free.

The populate-gate rule: every POPULATED index universe must have a `## <slug>`
plan section in docs/universe-maintenance.md. The check enforces it; a missing
doc file degrades to WARN (deployments without docs/ must not crash the suite).
"""

from __future__ import annotations

from sym.validate.plans import check_maintenance_plan_coverage, plan_slugs
from sym.validate.results import FAIL, PASS, WARN

DOC = """# Universe maintenance plans

Header prose.

## ibov — Ibovespa (B3)

- fields...

## sp500 — S&P 500

- fields...
"""


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        assert "kind = 'index'" in sql or "kind" in sql
        return _Cur(self._rows)


def _doc(tmp_path, text=DOC):
    p = tmp_path / "universe-maintenance.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_plan_slugs_parses_headings(tmp_path):
    assert plan_slugs(_doc(tmp_path)) == {"ibov", "sp500"}


def test_covered_universes_pass(tmp_path):
    conn = _Conn([("ibov", 78), ("sp500", 503)])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == PASS and result.checked == 2


def test_missing_plan_fails(tmp_path):
    conn = _Conn([("ibov", 78), ("dax", 40)])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == FAIL
    assert any("dax" in s for s in result.samples)


def test_unpopulated_universe_is_ignored(tmp_path):
    # The rule gates POPULATING — a registered-but-empty universe needs no plan yet.
    conn = _Conn([("ibov", 78), ("newuni", 0)])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == PASS


def test_missing_doc_warns_not_crashes(tmp_path):
    conn = _Conn([("ibov", 78)])
    result = check_maintenance_plan_coverage(
        conn, doc_path=tmp_path / "nope" / "universe-maintenance.md"
    )
    assert result.status == WARN and result.failures == 0
