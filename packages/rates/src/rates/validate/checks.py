"""Curve-store validation checks (the data-quality pre-mortem, as guards).

Each check returns a ``CheckResult`` (PASS / WARN / FAIL), mirroring ``sym.validate``. ``run_all``
orchestrates them in isolation. Highest-value guard: the inflation = nominal − real free check
(exact, FAIL on breach). Forward↔spot reconciliation is a WARN-level diagnostic until a
derive-on-read layer pins BoE's exact compounding (then it becomes exact).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import psycopg

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: str = PASS
    checked: int = 0
    failures: int = 0
    warnings: int = 0
    samples: list[str] = field(default_factory=list)
    detail: str | None = None

    @classmethod
    def from_items(
        cls,
        name: str,
        *,
        checked: int = 0,
        failures: list[str] | None = None,
        warnings: list[str] | None = None,
        detail: str | None = None,
    ) -> CheckResult:
        failures = failures or []
        warnings = warnings or []
        status = FAIL if failures else (WARN if warnings else PASS)
        return cls(
            name=name,
            status=status,
            checked=checked,
            failures=len(failures),
            warnings=len(warnings),
            samples=(failures + warnings)[:10],
            detail=detail,
        )


def _latest_date(conn: psycopg.Connection) -> date | None:
    row = conn.execute("SELECT max(as_of_date) FROM rates.curve_point").fetchone()
    return row[0] if row else None


def _curve(
    conn: psycopg.Connection, curve_set: str, basis: str, rate_type: str, as_of_date: date
) -> dict[float, float]:
    rows = conn.execute(
        """
        SELECT tenor, value FROM rates.curve_point
         WHERE curve_set=%s AND basis=%s AND rate_type=%s AND as_of_date=%s
         ORDER BY tenor
        """,
        (curve_set, basis, rate_type, as_of_date),
    ).fetchall()
    return {float(t): float(v) for t, v in rows}


def check_staleness(conn: psycopg.Connection, *, as_of_date: date | None = None) -> CheckResult:
    """The latest stored curve must be recent vs the business day — never silently carried."""
    today = as_of_date or date.today()
    latest = _latest_date(conn)
    if latest is None:
        return CheckResult.from_items(
            "curve_staleness", checked=0,
            warnings=["rates.curve_point is empty — run `rates curve load`"],
            detail="no curves stored",
        )
    # business-day age (ignore Sat/Sun); BoE doesn't publish on UK weekends/holidays.
    age = 0
    d = today
    while d > latest:
        if d.weekday() < 5:
            age += 1
        d -= timedelta(days=1)
    warnings = (
        [f"latest curve {latest.isoformat()} is {age} business day(s) stale"] if age > 1 else []
    )
    return CheckResult.from_items(
        "curve_staleness", checked=1, warnings=warnings,
        detail=f"latest={latest.isoformat()} (as-of {today.isoformat()})",
    )


def check_plausible_band(
    conn: psycopg.Connection, *, as_of_date: date | None = None
) -> CheckResult:
    """Latest spot curves are within a plausible band and have no missing tenors (holes)."""
    latest = as_of_date or _latest_date(conn)
    if latest is None:
        return CheckResult.from_items("curve_plausible_band", checked=0,
                                      warnings=["no curves stored"], detail="empty")
    failures: list[str] = []
    warnings: list[str] = []
    checked = 0
    pairs = conn.execute(
        "SELECT DISTINCT curve_set, basis FROM rates.curve_point WHERE as_of_date=%s", (latest,)
    ).fetchall()
    for cs, b in pairs:
        spot = _curve(conn, cs, b, "spot", latest)
        checked += len(spot)
        for t, v in spot.items():
            if not (-5.0 < v < 25.0):
                failures.append(f"{cs}/{b}/spot/{t}y = {v:.2f}% out of band")  # corruption → FAIL
        # hole guard: fewer spot tenors than the prior published day. WARN not FAIL — BoE can
        # legitimately trim a tenor (tenor-as-data), so a shrink is suspicious, not corruption.
        prior = conn.execute(
            """
            SELECT count(*) FROM rates.curve_point
             WHERE curve_set=%s AND basis=%s AND rate_type='spot'
               AND as_of_date = (
                   SELECT max(as_of_date) FROM rates.curve_point
                    WHERE curve_set=%s AND basis=%s AND rate_type='spot' AND as_of_date < %s)
            """,
            (cs, b, cs, b, latest),
        ).fetchone()
        prior_n = prior[0] if prior and prior[0] else None
        if prior_n and len(spot) < prior_n:
            warnings.append(
                f"{cs}/{b}/spot: {len(spot)} tenors vs {prior_n} on the prior day (possible holes)"
            )
    return CheckResult.from_items(
        "curve_plausible_band", checked=checked, failures=failures, warnings=warnings,
        detail=f"{checked} latest spot nodes checked on {latest.isoformat()} "
        f"(band=FAIL, tenor-shrink=WARN)",
    )


def check_inflation_reconcile(
    conn: psycopg.Connection, *, as_of_date: date | None = None, tol_pp: float = 0.02
) -> CheckResult:
    """FREE CHECK: implied inflation == nominal - real (gilt spot), matching tenors. RPI not CPI."""
    latest = as_of_date or _latest_date(conn)
    if latest is None:
        return CheckResult.from_items("curve_inflation_reconcile", checked=0,
                                      warnings=["no curves stored"], detail="empty")
    nominal = _curve(conn, "glc", "nominal", "spot", latest)
    real = _curve(conn, "glc", "real", "spot", latest)
    infl = _curve(conn, "glc", "inflation", "spot", latest)
    if not infl or not real:
        return CheckResult.from_items(
            "curve_inflation_reconcile", checked=0,
            warnings=["no real/inflation gilt curve on the latest date — skipped"],
            detail=f"as-of {latest.isoformat()}",
        )
    failures: list[str] = []
    checked = 0
    for t, infl_v in infl.items():
        if t in nominal and t in real:
            checked += 1
            expected = nominal[t] - real[t]
            if abs(infl_v - expected) > tol_pp:
                failures.append(
                    f"{t}y: inflation {infl_v:.3f} vs nominal-real {expected:.3f} "
                    f"(delta {abs(infl_v - expected):.3f}pp)"
                )
    return CheckResult.from_items(
        "curve_inflation_reconcile", checked=checked, failures=failures,
        detail=f"RPI breakeven = nominal-real within {tol_pp}pp on {latest.isoformat()}",
    )


def check_forward_spot_reconcile(
    conn: psycopg.Connection, *, as_of_date: date | None = None, tol_pp: float = 0.50
) -> CheckResult:
    """Diagnostic: spot(t) reconstructed from the cumulative mean of instantaneous forwards should
    track published spot (nominal gilt). Approximate (forward grid doesn't start at 0) -> WARN."""
    latest = as_of_date or _latest_date(conn)
    if latest is None:
        return CheckResult.from_items("curve_forward_spot_reconcile", checked=0,
                                      warnings=["no curves stored"], detail="empty")
    spot = _curve(conn, "glc", "nominal", "spot", latest)
    fwd = _curve(conn, "glc", "nominal", "forward", latest)
    shared = sorted(set(spot) & set(fwd))
    if len(shared) < 3:
        return CheckResult.from_items("curve_forward_spot_reconcile", checked=0,
                                      warnings=["too few shared nominal tenors"], detail="skipped")
    warnings: list[str] = []
    checked = 0
    # trapezoidal cumulative integral of f over the shared grid, anchored at the first node.
    cum = 0.0
    prev_t = shared[0]
    for t in shared[1:]:
        cum += 0.5 * (fwd[t] + fwd[prev_t]) * (t - prev_t)
        # integral of f over [0, t] ~= f(t0)*t0 (flat to 0) + trapezoid(t0..t); spot(t) = that / t
        recon = (fwd[shared[0]] * shared[0] + cum) / t
        checked += 1
        if abs(recon - spot[t]) > tol_pp:
            warnings.append(
                f"{t}y: recon {recon:.3f} vs spot {spot[t]:.3f} (d {abs(recon - spot[t]):.3f}pp)"
            )
        prev_t = t
    return CheckResult.from_items(
        "curve_forward_spot_reconcile", checked=checked, warnings=warnings,
        detail=f"forward->spot reconstruction within {tol_pp}pp on {latest.isoformat()} "
        f"(approximate; exact once derive-on-read pins BoE compounding)",
    )


def run_all(conn: psycopg.Connection, *, as_of_date: date | None = None) -> list[CheckResult]:
    checks = [
        ("curve_staleness", lambda: check_staleness(conn, as_of_date=as_of_date)),
        ("curve_plausible_band", lambda: check_plausible_band(conn, as_of_date=as_of_date)),
        ("curve_inflation_reconcile",
         lambda: check_inflation_reconcile(conn, as_of_date=as_of_date)),
        ("curve_forward_spot_reconcile",
         lambda: check_forward_spot_reconcile(conn, as_of_date=as_of_date)),
    ]
    results: list[CheckResult] = []
    for name, fn in checks:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 — a crashed check is a FAIL, not a crash
            results.append(
                CheckResult.from_items(name, checked=0, failures=[f"check crashed: {exc!r}"],
                                       detail="check raised")
            )
    return results
