"""Curve-store validation checks (the data-quality pre-mortem, as guards).

Each check returns a ``CheckResult`` (PASS / WARN / FAIL), mirroring ``sym.validate``. ``run_all``
runs the country-agnostic checks (staleness, plausible band) for every country present, plus the two
UK-only exact FREE checks (inflation = nominal − real; the forward↔spot continuous-compounding
identity) which depend on the BoE gilt real/forward curves. Staleness adapts its threshold to each
series' own cadence so a monthly series (e.g. ECB 10y) isn't flagged as stale against a daily yard-
stick. The plausible-band tenor-shrink guard is WARN (a legitimate grid trim).
"""

from __future__ import annotations

import statistics as st
from dataclasses import dataclass, field
from datetime import date

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


def _countries(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT country FROM rates.curve_point ORDER BY country").fetchall()]


def _latest_date(conn: psycopg.Connection, country: str) -> date | None:
    row = conn.execute(
        "SELECT max(as_of_date) FROM rates.curve_point WHERE country=%s", (country,)
    ).fetchone()
    return row[0] if row else None


def _recent_dates(conn: psycopg.Connection, country: str, n: int = 20) -> list[date]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT as_of_date FROM rates.curve_point WHERE country=%s "
        "ORDER BY as_of_date DESC LIMIT %s", (country, n)).fetchall()]


def _curve(
    conn: psycopg.Connection, country: str, curve_set: str, basis: str, rate_type: str,
    as_of_date: date,
) -> dict[float, float]:
    rows = conn.execute(
        """
        SELECT tenor, value FROM rates.curve_point
         WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s AND as_of_date=%s
         ORDER BY tenor
        """,
        (country, curve_set, basis, rate_type, as_of_date),
    ).fetchall()
    return {float(t): float(v) for t, v in rows}


def check_staleness(
    conn: psycopg.Connection, country: str, *, as_of_date: date | None = None
) -> CheckResult:
    """The latest stored curve must be recent vs the series' own cadence — never silently carried.
    Threshold scales to the median spacing of recent observations (daily vs monthly feeds)."""
    today = as_of_date or date.today()
    recent = _recent_dates(conn, country)
    if not recent:
        return CheckResult.from_items(
            f"staleness[{country}]", checked=0, warnings=["no curves stored"], detail="empty")
    latest = recent[0]
    gaps = [(recent[i] - recent[i + 1]).days for i in range(min(len(recent) - 1, 10))]
    median_gap = st.median(gaps) if gaps else 1
    allowed = max(5, 2 * median_gap)  # daily → ~5d grace; monthly → ~60d grace
    age = (today - latest).days
    warnings = (
        [f"latest {latest.isoformat()} is {age}d old "
         f"(cadence ~{median_gap:.0f}d, allow {allowed:.0f}d)"]
        if age > allowed else []
    )
    return CheckResult.from_items(
        f"staleness[{country}]", checked=1, warnings=warnings,
        detail=f"latest={latest.isoformat()} cadence~{median_gap:.0f}d (as-of {today.isoformat()})",
    )


def check_plausible_band(
    conn: psycopg.Connection, country: str, *, as_of_date: date | None = None
) -> CheckResult:
    """Latest curves are within a plausible band and have no missing tenors (holes). Band is wide
    enough for EM nominal yields and deep history (-5..40%); a hole (fewer tenors than the prior
    day) is WARN (a legitimate grid trim), an out-of-band value is FAIL (corruption)."""
    latest = as_of_date or _latest_date(conn, country)
    if latest is None:
        return CheckResult.from_items(
            f"plausible_band[{country}]", checked=0, warnings=["no curves stored"], detail="empty")
    failures: list[str] = []
    warnings: list[str] = []
    checked = 0
    series = conn.execute(
        "SELECT DISTINCT curve_set, basis, rate_type FROM rates.curve_point "
        "WHERE country=%s AND as_of_date=%s", (country, latest)
    ).fetchall()
    for cs, b, rt in series:
        curve = _curve(conn, country, cs, b, rt, latest)
        checked += len(curve)
        for t, v in curve.items():
            if not (-5.0 < v < 40.0):
                failures.append(f"{cs}/{b}/{rt}/{t}y = {v:.2f}% out of band")
        prior = conn.execute(
            """
            SELECT count(*) FROM rates.curve_point
             WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
               AND as_of_date = (
                   SELECT max(as_of_date) FROM rates.curve_point
                    WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
                      AND as_of_date < %s)
            """,
            (country, cs, b, rt, country, cs, b, rt, latest),
        ).fetchone()
        prior_n = prior[0] if prior and prior[0] else None
        if prior_n and len(curve) < prior_n:
            warnings.append(
                f"{cs}/{b}/{rt}: {len(curve)} tenors vs {prior_n} on the prior day (possible holes)"
            )
    return CheckResult.from_items(
        f"plausible_band[{country}]", checked=checked, failures=failures, warnings=warnings,
        detail=f"{checked} latest nodes on {latest.isoformat()} (band=FAIL, tenor-shrink=WARN)",
    )


def check_inflation_reconcile(
    conn: psycopg.Connection, *, as_of_date: date | None = None, tol_pp: float = 0.02
) -> CheckResult:
    """FREE CHECK (GB): implied inflation == nominal - real (gilt spot), matching tenors. RPI."""
    latest = as_of_date or _latest_date(conn, "GB")
    if latest is None:
        return CheckResult.from_items("inflation_reconcile[GB]", checked=0,
                                      warnings=["no GB curves stored"], detail="empty")
    nominal = _curve(conn, "GB", "glc", "nominal", "spot", latest)
    real = _curve(conn, "GB", "glc", "real", "spot", latest)
    infl = _curve(conn, "GB", "glc", "inflation", "spot", latest)
    if not infl or not real:
        return CheckResult.from_items(
            "inflation_reconcile[GB]", checked=0,
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
        "inflation_reconcile[GB]", checked=checked, failures=failures,
        detail=f"RPI breakeven = nominal-real within {tol_pp}pp on {latest.isoformat()}",
    )


def check_forward_spot_reconcile(
    conn: psycopg.Connection, *, as_of_date: date | None = None, tol_pp: float = 0.50
) -> CheckResult:
    """FREE CHECK (GB): the continuous-compounding identity s(t)·t = integral(f, 0..t) — confirmed
    from the BoE FAQ. Reconstruct spot(t) as the mean instantaneous forward over [0,t]; FAIL on a
    breach beyond ``tol_pp`` (above the trapezoidal-discretization residual, ~0.36pp max)."""
    latest = as_of_date or _latest_date(conn, "GB")
    if latest is None:
        return CheckResult.from_items("forward_spot_reconcile[GB]", checked=0,
                                      warnings=["no GB curves stored"], detail="empty")
    spot = _curve(conn, "GB", "glc", "nominal", "spot", latest)
    fwd = _curve(conn, "GB", "glc", "nominal", "forward", latest)
    shared = sorted(set(spot) & set(fwd))
    if len(shared) < 3:
        return CheckResult.from_items("forward_spot_reconcile[GB]", checked=0,
                                      warnings=["too few shared nominal tenors"], detail="skipped")
    failures: list[str] = []
    checked = 0
    cum = 0.0
    prev_t = shared[0]
    for t in shared[1:]:
        cum += 0.5 * (fwd[t] + fwd[prev_t]) * (t - prev_t)
        recon = (fwd[shared[0]] * shared[0] + cum) / t
        checked += 1
        if abs(recon - spot[t]) > tol_pp:
            failures.append(
                f"{t}y: recon {recon:.3f} vs spot {spot[t]:.3f} (d {abs(recon - spot[t]):.3f}pp)"
            )
        prev_t = t
    return CheckResult.from_items(
        "forward_spot_reconcile[GB]", checked=checked, failures=failures,
        detail=f"continuous-compounding fwd->spot within {tol_pp}pp on {latest.isoformat()}",
    )


def run_all(conn: psycopg.Connection, *, as_of_date: date | None = None) -> list[CheckResult]:
    """Per-country staleness + plausible-band, plus the two GB-only free checks."""
    results: list[CheckResult] = []

    def _run(name: str, fn) -> None:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 — a crashed check is a FAIL, not a crash
            results.append(CheckResult.from_items(
                name, checked=0, failures=[f"check crashed: {exc!r}"], detail="check raised"))

    for country in _countries(conn):
        _run(f"staleness[{country}]",
             lambda c=country: check_staleness(conn, c, as_of_date=as_of_date))
        _run(f"plausible_band[{country}]",
             lambda c=country: check_plausible_band(conn, c, as_of_date=as_of_date))
    _run("inflation_reconcile[GB]",
         lambda: check_inflation_reconcile(conn, as_of_date=as_of_date))
    _run("forward_spot_reconcile[GB]",
         lambda: check_forward_spot_reconcile(conn, as_of_date=as_of_date))
    return results
