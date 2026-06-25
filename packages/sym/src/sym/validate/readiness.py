"""Universe → returns research-readiness gate (Story V6).

A universe is only usable for research if its current members actually join
``fact_returns``. For each universe this computes the fraction of current members
with returns; below a (configurable) threshold is a fail, with the missing members
itemized and *classified* by reason — unpriced, no calendar, or priced-but-no-
returns (a stale recompute) — so a partially-loaded universe can't masquerade as
ready. Coverage math is pure.
"""

from __future__ import annotations

import psycopg

from sym.validate.results import CheckResult

DEFAULT_THRESHOLD = 0.90


def coverage_pct(total: int, covered: int) -> float:
    """Fraction covered (1.0 when there is nothing to cover)."""
    return covered / total if total else 1.0


def _missing_reason(has_prices: bool, has_calendar: bool) -> str:
    if not has_calendar:
        return "no calendar"
    if not has_prices:
        return "unpriced"
    return "priced but no returns (recompute stale)"


def check_universe_readiness(
    conn: psycopg.Connection,
    u_conn: psycopg.Connection,
    eq_conn: psycopg.Connection,
    threshold: float = DEFAULT_THRESHOLD,
) -> CheckResult:
    """Per universe, gate the % of current members that join ``fact_returns`` (cross-DB).

    ``u_conn`` is the universe DB (the current-member roster); ``eq_conn`` is the equity DB
    (fact_returns/prices); ``conn`` is sym (securities/calendar). The returned/priced figi SETS are
    roster-fetched from equity and the has-calendar flag from sym, joined locally (no cross-DB
    join). Members not in the securities master are excluded (parity with the old INNER JOIN).
    """
    universes = [r[0] for r in u_conn.execute("SELECT universe_id FROM universe").fetchall()]
    failures: list[str] = []
    warnings: list[str] = []
    for uid in universes:
        roster = [
            r[0]
            for r in u_conn.execute(
                "SELECT composite_figi FROM universe_membership "
                "WHERE universe_id = %s AND valid_to IS NULL",
                (uid,),
            ).fetchall()
        ]
        if roster:
            returned = {r[0] for r in eq_conn.execute(
                "SELECT DISTINCT composite_figi FROM fact_returns WHERE composite_figi = ANY(%s)",
                (roster,),
            ).fetchall()}
            priced = {r[0] for r in eq_conn.execute(
                "SELECT DISTINCT composite_figi FROM prices_raw WHERE composite_figi = ANY(%s)",
                (roster,),
            ).fetchall()}
            rows = [
                (figi, figi in returned, figi in priced, hc)
                for figi, hc in conn.execute(
                    """
                    SELECT s.composite_figi,
                           EXISTS (SELECT 1 FROM trading_calendar_version v
                                    WHERE v.is_current AND v.mic = s.mic)
                      FROM securities s
                     WHERE s.composite_figi = ANY(%s)
                    """,
                    (roster,),
                ).fetchall()
            ]
        else:
            rows = []
        total = len(rows)
        if total == 0:
            # An empty universe is not "100% ready" — flag it rather than pass silently.
            warnings.append(f"{uid}: no current members")
            continue
        covered = sum(1 for _f, hr, _hp, _hc in rows if hr)
        pct = coverage_pct(total, covered)
        if pct < threshold:
            missing = [
                f"{f} ({_missing_reason(hp, hc)})" for f, hr, hp, hc in rows if not hr
            ]
            failures.append(
                f"{uid}: {pct:.1%} of {total} members have returns (< {threshold:.0%}); "
                f"missing {len(missing)} e.g. {missing[:5]}"
            )
    return CheckResult.from_items(
        "universe_readiness",
        checked=len(universes),
        failures=failures,
        warnings=warnings,
        detail=f"{len(universes)} universes gated at {threshold:.0%} returns coverage",
    )
