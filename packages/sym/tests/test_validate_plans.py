"""Maintenance-plan coverage check (Story U3.6, ledger D4). DB-free + one real-doc test.

The populate-gate rule: every universe that has EVER been populated must have a
`## <slug>` plan section in docs/universe-maintenance.md carrying the four
mandatory fields (source · monitor · gating · PIT), and `config.calendar_mic`
set (the U3.6 investigation found alignment inert on all 13 universes). A
missing or unreadable doc degrades to WARN; the calendar_mic failure is
doc-independent.
"""

from __future__ import annotations

from sym.validate.plans import (
    REQUIRED_FIELDS,
    check_maintenance_plan_coverage,
    default_doc_path,
    plan_sections,
    plan_slugs,
)
from sym.validate.results import FAIL, PASS, WARN

DOC = """# Universe maintenance plans

Header prose.

## ibov — Ibovespa (B3)

- **Source:** b3 snapshot. **Monitor cadence:** daily. **Gating:** two-stage.
- **PIT boundary:** build-forward.

## Shared notes — not a universe

```text
## fenced — a heading inside a code block must NOT count
```

## sp500 — S&P 500

- **Source:** wikipedia. **Monitor / gating:** shared mechanics. **PIT boundary:** 1994.
"""


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        # rows: (universe_id, member_rows_ever, calendar_mic)
        self._rows = rows

    def execute(self, sql, params=None):
        assert "kind = 'index'" in sql
        return _Cur(self._rows)


def _doc(tmp_path, text=DOC):
    p = tmp_path / "universe-maintenance.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_plan_slugs_parses_headings_and_ignores_fences(tmp_path):
    # "Shared" starts a lowercase-slug heading -> parsed (harmless); the fenced
    # `## fenced` line must NOT be a section.
    slugs = plan_slugs(_doc(tmp_path))
    assert {"ibov", "sp500"} <= slugs
    assert "fenced" not in slugs


def test_covered_universes_pass(tmp_path):
    conn = _Conn([("ibov", 78, "BVMF"), ("sp500", 503, "XNYS")])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == PASS and result.checked == 2


def test_missing_plan_fails(tmp_path):
    conn = _Conn([("ibov", 78, "BVMF"), ("dax", 40, "XETR")])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == FAIL
    assert any("dax" in s for s in result.samples)


def test_stub_section_fails(tmp_path):
    # A bare `## ibov` heading with none of the four mandatory fields must not
    # satisfy the gate.
    doc = _doc(tmp_path, "# plans\n\n## ibov\n\n(stub)\n")
    conn = _Conn([("ibov", 78, "BVMF")])
    result = check_maintenance_plan_coverage(conn, doc_path=doc)
    assert result.status == FAIL
    assert any("mandatory field" in s for s in result.samples)


def test_missing_calendar_mic_fails_even_with_plan(tmp_path):
    # The inert-config failure mode this story uncovered: plan written, but
    # alignment config absent. Doc-independent FAIL.
    conn = _Conn([("ibov", 78, None)])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == FAIL
    assert any("calendar_mic" in s for s in result.samples)


def test_never_populated_universe_is_ignored(tmp_path):
    # The rule gates POPULATING — a registered-but-never-populated universe
    # needs no plan yet. (A fully-EMPTIED universe still needs one: it carries
    # point-in-time history the plan governs — hence member rows EVER, not open.)
    conn = _Conn([("ibov", 78, "BVMF"), ("newuni", 0, None)])
    result = check_maintenance_plan_coverage(conn, doc_path=_doc(tmp_path))
    assert result.status == PASS


def test_missing_doc_warns_not_crashes(tmp_path):
    conn = _Conn([("ibov", 78, "BVMF")])
    result = check_maintenance_plan_coverage(
        conn, doc_path=tmp_path / "nope" / "universe-maintenance.md"
    )
    assert result.status == WARN and result.failures == 0


def test_unreadable_doc_warns_not_crashes(tmp_path):
    doc = tmp_path / "universe-maintenance.md"
    doc.write_bytes(b"\xff\xfe\x00bad utf8 \x9c")
    conn = _Conn([("ibov", 78, "BVMF")])
    result = check_maintenance_plan_coverage(conn, doc_path=doc)
    assert result.status == WARN and result.failures == 0


def test_real_doc_covers_all_known_universes():
    # Integration guard: heading drift in the REAL doc must fail the suite,
    # not wait for a live `sym validate` run.
    path = default_doc_path()
    assert path.is_file(), "docs/universe-maintenance.md not found from package walk-up"
    sections = plan_sections(path)
    expected = {
        "ibov", "ibx", "sp500", "sp400", "sp600", "dax", "cac40", "ftse100",
        "ibex35", "ftsemib", "aex", "smi", "estoxx50",
    }
    missing = expected - set(sections)
    assert not missing, f"plan sections missing: {sorted(missing)}"
    for slug in sorted(expected):
        low = sections[slug].lower()
        absent = [f for f in REQUIRED_FIELDS if f not in low]
        assert not absent, f"{slug}: mandatory fields absent: {absent}"
