"""`sym validate` orchestration + report (Story V7).

Runs the whole Epic-V suite (V1–V6), assembles a structured pass/warn/fail report,
writes a ``validation_run_log`` row, and returns an overall status the CLI maps to
an exit code (fail → non-zero, a CI/operator gate). Actionable findings already
persist (the V1 completeness log) and surface in `universe review`.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from sym.validate.classification import check_classification_coverage
from sym.validate.completeness import evaluate_completeness
from sym.validate.fx import check_fx_coverage
from sym.validate.instrument_bridge import check_equity_instrument_bridge
from sym.validate.integrity import check_referential_integrity
from sym.validate.plans import check_maintenance_plan_coverage
from sym.validate.prices import (
    check_calendar_coverage,
    check_price_calendar_consistency,
    check_unpriced_securities,
)
from sym.validate.projection import check_projection_reconciliation
from sym.validate.readiness import check_universe_readiness
from sym.validate.results import FAIL, PASS, WARN, CheckResult, worst
from sym.validate.symbology import (
    check_identity_completeness,
    check_symbology_transitions,
    check_ticker_collisions,
)


def _fx_coverage(conn: psycopg.Connection) -> CheckResult:
    """FX coverage is cross-DB now (fx lives in its own database). Open the fx connection here so
    a failure to reach it is isolated as a FAIL by run_all's per-check try/except (not a suite
    abort)."""
    from fx.db import connect as fx_connect

    with fx_connect() as fx_conn:
        return check_fx_coverage(conn, fx_conn)


def _with_universe(fn):
    """Run a universe-DB-dependent check with a freshly-opened universe connection, isolated.

    Membership lives in the universe package's own database; open it here so a failure to reach it
    is isolated as a FAIL by run_all's per-check try/except (not a suite abort). ``fn`` receives the
    universe connection (cross-DB checks close over the sym ``conn`` separately)."""
    from universe.db import connect as u_connect

    with u_connect() as u_conn:
        return fn(u_conn)


def run_all(conn: psycopg.Connection, universe_id: str | None = None) -> list[CheckResult]:
    """Run every validation check (V1 refreshes the completeness log; rest read-only).

    Each check is error-isolated: a raising check becomes a FAIL result (with the
    exception as detail) instead of aborting the suite — one missing table must not
    cost the run-log row and every downstream check.
    """
    checks: list[tuple[str, object]] = [
        ("completeness",                                                        # V1 (cross-DB)
         lambda: _with_universe(lambda u: evaluate_completeness(conn, u, universe_id))),
        ("referential_integrity", lambda: check_referential_integrity(conn)),  # V2
        ("equity_instrument_bridge",                                            # B7 — 1:1 bridge
         lambda: check_equity_instrument_bridge(conn)),
        ("identity_completeness", lambda: check_identity_completeness(conn)),  # V3
        ("ticker_collisions", lambda: check_ticker_collisions(conn)),          # V3
        ("symbology_transitions",                                              # V3 — 1.10
         lambda: check_symbology_transitions(conn)),
        ("price_calendar_consistency",                                          # V4
         lambda: check_price_calendar_consistency(conn)),
        ("calendar_coverage", lambda: check_calendar_coverage(conn)),          # V4
        ("unpriced_securities", lambda: check_unpriced_securities(conn)),      # V4
        ("projection_reconciliation",                                       # V5 (universe DB)
         lambda: _with_universe(check_projection_reconciliation)),
        ("universe_readiness",                                              # V6 (cross-DB)
         lambda: _with_universe(lambda u: check_universe_readiness(conn, u))),
        ("fx_coverage", lambda: _fx_coverage(conn)),                           # FX4 — SLA (fx DB)
        ("maintenance_plan_coverage",                              # U3.6 — populate gate (univ DB)
         lambda: _with_universe(check_maintenance_plan_coverage)),
        ("classification_coverage",                          # multi-source classify — AC6 guardrail
         lambda: check_classification_coverage(conn)),
    ]
    results: list[CheckResult] = []
    for name, check in checks:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 — isolate; the suite must always report
            results.append(
                CheckResult.from_items(
                    name, checked=0,
                    failures=[f"check raised: {type(exc).__name__}: {str(exc)[:300]}"],
                    detail="check crashed — treated as FAIL",
                )
            )
    return results


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
