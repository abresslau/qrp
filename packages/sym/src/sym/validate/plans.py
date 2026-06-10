"""Maintenance-plan coverage check (Story U3.6 — the populate-gate rule, enforced).

Every POPULATED index universe must have a written maintenance plan (source ·
monitor cadence · gating · PIT boundary) in ``docs/universe-maintenance.md`` —
the standing rule the 2026-06 review found violated by 12 of 13 universes. A
universe with open members and no ``## <slug>`` plan section is a FAIL; a
registered-but-empty universe needs no plan yet (the rule gates *populating*).
A missing doc file degrades to WARN — a deployment without ``docs/`` must not
crash the validation suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

from sym.validate.results import CheckResult

# `## <slug> — Title` (or `## <slug>` bare); the slug is the universe_id.
_HEADING = re.compile(r"^##\s+([a-z0-9_-]+)\b", re.MULTILINE)


def default_doc_path() -> Path:
    """Locate ``docs/universe-maintenance.md`` by walking up from this package.

    The doc lives at the repo root, not inside the package — walking up keeps
    the check working from any install layout that retains the repo tree.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "universe-maintenance.md"
        if candidate.is_file():
            return candidate
    return Path("docs") / "universe-maintenance.md"


def plan_slugs(doc_path: Path) -> set[str]:
    """The universe slugs with a ``## <slug>`` plan section in the doc."""
    return set(_HEADING.findall(doc_path.read_text(encoding="utf-8")))


def check_maintenance_plan_coverage(
    conn: psycopg.Connection, *, doc_path: Path | None = None
) -> CheckResult:
    """Every populated index universe must have a maintenance-plan section."""
    doc_path = doc_path or default_doc_path()
    rows = conn.execute(
        """
        SELECT u.universe_id,
               (SELECT count(*) FROM universe_membership m
                 WHERE m.universe_id = u.universe_id AND m.valid_to IS NULL) AS open_members
          FROM universe u
         WHERE u.kind = 'index'
         ORDER BY u.universe_id
        """
    ).fetchall()
    populated = [uid for uid, open_members in rows if open_members > 0]
    if not doc_path.is_file():
        return CheckResult.from_items(
            "maintenance_plan_coverage",
            checked=len(populated),
            warnings=[f"plan doc not found at {doc_path} — coverage unverifiable"],
            detail="docs/universe-maintenance.md missing",
        )
    slugs = plan_slugs(doc_path)
    failures = [
        f"{uid}: populated but no maintenance plan in {doc_path.name}"
        for uid in populated
        if uid not in slugs
    ]
    return CheckResult.from_items(
        "maintenance_plan_coverage",
        checked=len(populated),
        failures=failures,
        detail=f"{len(populated)} populated index universes vs {doc_path.name}",
    )
