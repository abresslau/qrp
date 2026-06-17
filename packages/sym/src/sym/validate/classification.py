"""GICS classification coverage gate (multi-source classification — the AC6 guardrail).

Now that ``sym classify`` runs unattended in the daily EOD, a silent regression — a source
breaking, a wave of newly-joined members left unclassified — must be caught automatically, not
by eyeballing the nightly classify output. It gates whole-universe coverage at the SAME threshold
the ``sym classify`` command uses, reusing the SAME coverage definition
(:func:`read_active_coverage`) so the validate gate and the classify gate can never disagree. It
always reports the by-source
breakdown, so source drift is visible in every daily ``sym validate`` log even when it passes.

The fixed floor catches gross regression (a source fully breaking drops coverage well below the
threshold); finer drift above the floor is surfaced in the breakdown detail rather than gated (a
hard ceiling would false-FAIL the morning a new universe's members await the next nightly classify).
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from sym.classification.gics import DEFAULT_COVERAGE_THRESHOLD, read_active_coverage
from sym.validate.results import CheckResult


def coverage_detail(
    classified: int,
    total: int,
    by_source: Sequence[tuple[str | None, int]],
    threshold: float,
) -> tuple[list[str], str]:
    """Pure: ``(failures, detail)`` from the coverage counts + by-source breakdown.

    ``failures`` is non-empty (one FAIL line) only when coverage is below ``threshold``; the
    ``detail`` (always shown) carries the figure + the by-source breakdown for drift visibility.
    """
    pct = classified / total if total else 1.0
    breakdown = ", ".join(f"{src or 'unknown'} {n}" for src, n in by_source) or "none"
    detail = f"{classified}/{total} active classified = {pct:.1%}; by source: {breakdown}"
    failures: list[str] = []
    if pct < threshold:
        failures.append(
            f"whole-universe GICS coverage {classified}/{total} = {pct:.1%} "
            f"(below the {threshold:.0%} threshold); by source: {breakdown}"
        )
    return failures, detail


def check_classification_coverage(
    conn: psycopg.Connection, threshold: float = DEFAULT_COVERAGE_THRESHOLD
) -> CheckResult:
    """Gate whole-universe GICS coverage + surface the by-source breakdown."""
    classified, total = read_active_coverage(conn)
    by_source = conn.execute(
        """
        SELECT g.source, count(*)
          FROM gics_scd g
          JOIN securities s ON s.composite_figi = g.composite_figi
         WHERE s.status = 'active'
           AND g.valid_to IS NULL
           AND g.sector_name IS NOT NULL
         GROUP BY g.source
         ORDER BY count(*) DESC
        """
    ).fetchall()
    failures, detail = coverage_detail(classified, total, by_source, threshold)
    return CheckResult.from_items(
        "classification_coverage",
        checked=total,
        failures=failures,
        detail=detail,
    )
