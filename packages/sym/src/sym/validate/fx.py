"""FX coverage validation (Epic FX, FX4) — the operational SLA.

The check that keeps the FX layer honest: for the currencies actually needed by
currently-priced instruments (the denominator), is a non-stale USD rate resolvable?
Coverage is a *completeness/freshness* signal, so every gap is a **warn**, not a fail —
integrity is already enforced hard by the `fx_rate` constraints + the ingest plausibility
band. A missing or stale currency is typically a known source limitation (e.g. Frankfurter
dropped TWD in 2020 → pending the fallback source), surfaced for the operator rather than
breaking the gate; an empty `fx_rate` table warns "not yet populated".
"""

from __future__ import annotations

from datetime import date

import psycopg

from sym.fx.resolve import WEEKEND_SPAN_DAYS, fx_rate
from sym.validate.results import CheckResult


def needed_currencies(conn: psycopg.Connection) -> list[str]:
    """Non-USD currencies of currently-priced securities (the coverage denominator)."""
    rows = conn.execute(
        """
        SELECT DISTINCT s.currency_code
          FROM securities s
         WHERE s.currency_code IS NOT NULL AND s.currency_code <> 'USD'
           AND EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi)
         ORDER BY s.currency_code
        """
    ).fetchall()
    return [r[0] for r in rows]


def check_fx_coverage(conn: psycopg.Connection, *, as_of: date | None = None) -> CheckResult:
    """Every priced-instrument currency must resolve a non-stale USD rate as-of ``as_of``."""
    as_of = as_of or date.today()
    needed = needed_currencies(conn)
    fx_count = conn.execute("SELECT count(*) FROM fx_rate").fetchone()[0]
    if fx_count == 0:
        return CheckResult.from_items(
            "fx_coverage",
            checked=len(needed),
            warnings=[f"{c}: no FX (table empty)" for c in needed],
            detail="fx_rate is empty - run `sym fx backfill`.",
        )
    warnings: list[str] = []
    for ccy in needed:
        r = fx_rate(conn, ccy, as_of)
        if r.status == "no_data":
            warnings.append(f"{ccy}: no USD rate on/before {as_of} (source gap)")
        elif r.status == "stale":
            warnings.append(f"{ccy}: stale {r.days_stale}d (last observed {r.observed_date})")
        elif r.is_filled and r.days_stale > WEEKEND_SPAN_DAYS:
            warnings.append(f"{ccy}: carried {r.days_stale}d (last observed {r.observed_date})")
    return CheckResult.from_items("fx_coverage", checked=len(needed), warnings=warnings)
