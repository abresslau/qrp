"""`sym validate` orchestration + report (Story V7).

Runs the whole Epic-V suite (V1–V6), assembles a structured pass/warn/fail report,
writes a ``validation_run_log`` row, and returns an overall status the CLI maps to
an exit code (fail → non-zero, a CI/operator gate). Actionable findings already
persist (the V1 completeness log) and surface in `universe review`.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from sym.validate.completeness import evaluate_completeness
from sym.validate.fx import check_fx_coverage
from sym.validate.integrity import check_referential_integrity
from sym.validate.prices import (
    check_calendar_coverage,
    check_price_calendar_consistency,
    check_unpriced_securities,
)
from sym.validate.projection import check_projection_reconciliation
from sym.validate.readiness import check_universe_readiness
from sym.validate.results import FAIL, PASS, WARN, CheckResult, worst
from sym.validate.symbology import check_identity_completeness, check_ticker_collisions


def run_all(conn: psycopg.Connection, universe_id: str | None = None) -> list[CheckResult]:
    """Run every validation check (V1 refreshes the completeness log; rest read-only)."""
    return [
        evaluate_completeness(conn, universe_id),       # V1
        check_referential_integrity(conn),              # V2
        check_identity_completeness(conn),              # V3
        check_ticker_collisions(conn),                  # V3
        check_price_calendar_consistency(conn),         # V4
        check_calendar_coverage(conn),                  # V4
        check_unpriced_securities(conn),                # V4
        check_projection_reconciliation(conn),          # V5
        check_universe_readiness(conn),                 # V6
        check_fx_coverage(conn),                        # FX4 — FX coverage SLA
    ]


def summarize(results: list[CheckResult]) -> tuple[int, int, int, str]:
    """(passed, warned, failed, overall_status) over a result list (pure)."""
    passed = sum(1 for r in results if r.status == PASS)
    warned = sum(1 for r in results if r.status == WARN)
    failed = sum(1 for r in results if r.status == FAIL)
    return passed, warned, failed, worst(r.status for r in results)


def format_report(results: list[CheckResult]) -> str:
    """Render the suite as an operator-readable report (pure)."""
    passed, warned, failed, overall = summarize(results)
    lines = ["sym validate:"]
    for r in results:
        lines.append(
            f"  [{r.status.upper():4}] {r.name}: {r.detail or ''} "
            f"(checked={r.checked} fail={r.failures} warn={r.warnings})"
        )
        for s in r.samples[:5]:
            lines.append(f"           - {s}")
    lines.append(
        f"\noverall: {overall.upper()}  "
        f"({passed} pass, {warned} warn, {failed} fail of {len(results)} checks)"
    )
    return "\n".join(lines)


def write_run_log(
    conn: psycopg.Connection, results: list[CheckResult], universe_id: str | None
) -> int:
    """Persist a validation_run_log row; return its run_id."""
    passed, warned, failed, overall = summarize(results)
    detail = {
        r.name: {"status": r.status, "failures": r.failures, "warnings": r.warnings}
        for r in results
    }
    row = conn.execute(
        """
        INSERT INTO validation_run_log
            (universe_id, checks, passed, warned, failed, status, detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING run_id
        """,
        (universe_id, len(results), passed, warned, failed, overall, Jsonb(detail)),
    ).fetchone()
    return row[0]


def validate(
    conn: psycopg.Connection, universe_id: str | None = None
) -> tuple[list[CheckResult], str]:
    """Run all checks, write the run-log, return (results, overall status)."""
    conn.autocommit = True
    results = run_all(conn, universe_id)
    _, _, _, overall = summarize(results)
    write_run_log(conn, results, universe_id)
    return results, overall
