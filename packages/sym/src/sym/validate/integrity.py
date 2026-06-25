"""Referential-integrity invariants (Story V2).

The layers are joined by deliberate FK-less seams (resolutions, membership,
symbology, names, prices, fundamentals, returns all key on ``composite_figi``
without a foreign key). This check continuously asserts none of them holds a
``composite_figi`` absent from ``securities`` — an orphan that would otherwise
accumulate unseen. The set-diff is a pure function; the live sweep runs an
anti-join per seam.
"""

from __future__ import annotations

import psycopg

from sym.validate.results import CheckResult

# (label, child relation, extra predicate). A resolved universe member with no
# securities row is the bridge failing; every other orphan is a dangling key.
_SEAMS: tuple[tuple[str, str, str], ...] = (
    (
        "universe_member_resolution",
        "universe_member_resolution",
        "c.resolution_status = 'resolved' AND ",
    ),
    ("universe_membership", "universe_membership", ""),
    ("security_symbology", "security_symbology", ""),
    ("security_names", "security_names", ""),
    ("gics_scd", "gics_scd", ""),
    ("prices_raw", "prices_raw", ""),
    ("corporate_actions", "corporate_actions", ""),
    ("fundamentals", "fundamentals", ""),
    ("fact_returns", "fact_returns", ""),
)


def find_orphans(child_figis: set[str], security_figis: set[str]) -> set[str]:
    """CompositeFIGIs present in a child relation but absent from securities (pure)."""
    return {f for f in child_figis if f and f not in security_figis}


# The two universe seams live in the universe DB now — orphan-checked cross-DB (roster-fetch).
_UNIVERSE_SEAMS = {"universe_member_resolution", "universe_membership"}


def check_referential_integrity(
    conn: psycopg.Connection, u_conn: psycopg.Connection
) -> CheckResult:
    """Assert every seam's ``composite_figi`` resolves to a real securities row.

    ``conn`` is sym (securities + the sym seams); ``u_conn`` is the universe DB (the two membership
    seams) — for those, fetch the child figis and diff against sym's securities in Python (no
    cross-DB join)."""
    failures: list[str] = []
    checked = 0
    for label, relation, extra in _SEAMS:
        if relation in _UNIVERSE_SEAMS:
            child = {
                r[0]
                for r in u_conn.execute(
                    f"SELECT DISTINCT c.composite_figi FROM {relation} c "
                    f"WHERE {extra} c.composite_figi IS NOT NULL"  # noqa: S608 - fixed allow-list
                ).fetchall()
            }
            present = (
                {
                    r[0]
                    for r in conn.execute(
                        "SELECT composite_figi FROM securities WHERE composite_figi = ANY(%s)",
                        (list(child),),
                    ).fetchall()
                }
                if child
                else set()
            )
            failures.extend(
                f"{label}: {f} not in securities" for f in sorted(find_orphans(child, present))
            )
        else:
            rows = conn.execute(
                f"""
                SELECT DISTINCT c.composite_figi
                  FROM {relation} c
                 WHERE {extra} c.composite_figi IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM securities s WHERE s.composite_figi = c.composite_figi
                   )
                """  # noqa: S608 - relation/extra come from a fixed internal allow-list
            ).fetchall()
            failures.extend(f"{label}: {r[0]} not in securities" for r in rows)
        checked += 1
    return CheckResult.from_items(
        "referential_integrity",
        checked=checked,
        failures=failures,
        detail=f"{len(_SEAMS)} seams checked; {len(failures)} orphaned composite_figi(s)",
    )
