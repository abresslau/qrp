"""Maintenance-plan coverage check (Story U3.6 — the populate-gate rule, enforced).

Every index universe that has EVER been populated must have a written
maintenance plan in ``docs/universe-maintenance.md`` — a ``## <slug>`` section
carrying the four mandatory fields (**source · monitor · gating · PIT**) — and
``config.calendar_mic`` set (the U3.6 investigation found session-snapping and
event alignment inert on every universe because nobody had set it). A bare
heading stub does not satisfy the gate, and a fully-emptied universe still
needs its plan: it carries point-in-time history the plan governs.

Doc problems degrade to WARN (a deployment without ``docs/`` must not crash the
suite); the ``calendar_mic`` requirement is doc-independent and always FAILs.

Heading convention the parser relies on: a plan section starts ``## <slug>``
where the slug is the lowercase ``universe_id``; prose headings must start with
an uppercase letter (e.g. ``## Wikipedia-sourced universes``) so they don't
register as plans. Fenced code blocks are stripped before parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

from sym.validate.results import CheckResult

# Section boundaries are ANY `## ...` heading; only lowercase-slug headings are plans.
_ANY_HEADING = re.compile(r"^##\s+(.*)$", re.MULTILINE)
_SLUG = re.compile(r"^([a-z0-9_-]+)\b")
_FENCE = re.compile(r"```.*?```", re.DOTALL)

# Keywords every plan section must mention (case-insensitive) — the four
# mandatory fields of the populate-gate rule.
REQUIRED_FIELDS = ("source", "monitor", "gating", "pit")


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


def plan_sections(doc_path: Path) -> dict[str, str]:
    """``{slug: section body}`` for every ``## <slug>`` plan section in the doc.

    Fenced code blocks are stripped first (a ``##`` line inside an example must
    not mint a phantom plan); non-slug headings still terminate the previous
    section so prose between plans is never attributed to a universe.
    """
    text = _FENCE.sub("", doc_path.read_text(encoding="utf-8"))
    headings = list(_ANY_HEADING.finditer(text))
    sections: dict[str, str] = {}
    for i, heading in enumerate(headings):
        slug_match = _SLUG.match(heading.group(1))
        if slug_match is None:
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections[slug_match.group(1)] = text[heading.end():end]
    return sections


def plan_slugs(doc_path: Path) -> set[str]:
    """The universe slugs with a ``## <slug>`` plan section in the doc."""
    return set(plan_sections(doc_path))


def check_maintenance_plan_coverage(
    conn: psycopg.Connection, *, doc_path: Path | None = None
) -> CheckResult:
    """Every ever-populated index universe: plan section + calendar_mic."""
    doc_path = doc_path or default_doc_path()
    rows = conn.execute(
        """
        SELECT u.universe_id,
               (SELECT count(*) FROM universe_membership m
                 WHERE m.universe_id = u.universe_id) AS member_rows,
               u.config->>'calendar_mic' AS calendar_mic
          FROM universe u
         WHERE u.kind = 'index'
         ORDER BY u.universe_id
        """
    ).fetchall()
    populated = [(uid, mic) for uid, member_rows, mic in rows if member_rows > 0]

    failures: list[str] = [
        f"{uid}: populated but config.calendar_mic is not set (alignment inert)"
        for uid, mic in populated
        if not mic
    ]
    warnings: list[str] = []
    sections: dict[str, str] | None = None
    if not doc_path.is_file():
        warnings.append(f"plan doc not found at {doc_path} — coverage unverifiable")
    else:
        try:
            sections = plan_sections(doc_path)
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"plan doc unreadable ({exc}) — coverage unverifiable")
    if sections is not None:
        for uid, _mic in populated:
            body = sections.get(uid)
            if body is None:
                failures.append(
                    f"{uid}: populated but no maintenance plan in {doc_path.name}"
                )
                continue
            body_lower = body.lower()
            absent = [f for f in REQUIRED_FIELDS if f not in body_lower]
            if absent:
                failures.append(
                    f"{uid}: plan section missing mandatory field(s): {', '.join(absent)}"
                )
    return CheckResult.from_items(
        "maintenance_plan_coverage",
        checked=len(populated),
        failures=failures,
        warnings=warnings,
        detail=f"{len(populated)} populated index universes vs {doc_path.name}",
    )
