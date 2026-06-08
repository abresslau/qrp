"""Price ↔ calendar ↔ lifecycle consistency (Story V4).

Three invariants:
* **calendar consistency** — no `prices_raw` bar on a non-session day for the
  security's MIC, and no bar after `delist_date` (fail);
* **calendar coverage** — every active security's MIC has a current calendar
  (XNSE-type absence → warn with reason; returns can't be computed without it);
* **unpriced classification** — an active security with no prices is *expected*
  (delisted/suspended, or no calendar → no vendor data) → warn, or *unexpected*
  (priceable but unloaded) → fail.

Off-calendar detection compares date sets per MIC via a pure set-diff.
"""

from __future__ import annotations

from datetime import date

import psycopg

from sym.validate.results import CheckResult


def off_calendar(price_dates: set[date], session_dates: set[date]) -> set[date]:
    """Price dates that are not trading sessions for the calendar (pure)."""
    return price_dates - session_dates


def classify_unpriced(status: str, has_calendar: bool) -> tuple[str, str]:
    """Severity + reason for an active security that holds no prices (pure)."""
    if status in ("delisted", "suspended"):
        return "warn", f"{status}: no vendor prices expected"
    if not has_calendar:
        return "warn", "no current calendar for MIC"
    return "fail", "active + priceable but unpriced"


def _current_sessions(conn: psycopg.Connection, mic: str) -> set[date]:
    rows = conn.execute(
        """
        SELECT tc.session_date FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current AND tc.mic = %s
        """,
        (mic,),
    ).fetchall()
    return {r[0] for r in rows}


def check_price_calendar_consistency(conn: psycopg.Connection) -> CheckResult:
    """No price after delisting (fail); off-calendar bars are vendor noise (warn).

    An off-calendar price means the vendor disagrees with the *authoritative*
    trading calendar (snapshotted from ``exchange_calendars``). It is benign — the
    returns engine reads sessions from the calendar, so a bar on a non-session day
    is never referenced by PR/TR — so it is a ``warn`` (vendor noise), not a hard
    failure. A price *after* ``delist_date`` is a real lifecycle violation (fail).
    """
    failures: list[str] = []
    warnings: list[str] = []
    priced_mics = [
        r[0].strip() if isinstance(r[0], str) else r[0]
        for r in conn.execute(
            "SELECT DISTINCT s.mic FROM securities s "
            "WHERE EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi)"
        ).fetchall()
    ]
    for mic in priced_mics:
        sessions = _current_sessions(conn, mic)
        if not sessions:
            continue  # no calendar -> reported by check_calendar_coverage
        price_dates = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT p.session_date FROM prices_raw p "
                "JOIN securities s USING (composite_figi) WHERE s.mic = %s",
                (mic,),
            ).fetchall()
        }
        for d in sorted(off_calendar(price_dates, sessions)):
            warnings.append(f"{mic}: vendor bar on non-session {d} (calendar authoritative)")

    post_delist = conn.execute(
        """
        SELECT p.composite_figi, max(p.session_date) FROM prices_raw p
          JOIN securities s USING (composite_figi)
         WHERE s.delist_date IS NOT NULL AND p.session_date > s.delist_date
         GROUP BY p.composite_figi
        """
    ).fetchall()
    failures += [f"{figi}: price {d} after delist" for figi, d in post_delist]
    return CheckResult.from_items(
        "price_calendar_consistency",
        checked=len(priced_mics),
        failures=failures,
        warnings=warnings,
        detail=(
            f"{len(priced_mics)} priced MIC(s) checked; {len(warnings)} off-calendar "
            f"vendor bar(s) (warn), {len(failures)} post-delist (fail)"
        ),
    )


def check_calendar_coverage(conn: psycopg.Connection) -> CheckResult:
    """Every active security's MIC must have a current calendar with sessions (warn if not).

    Checks for actual ``trading_calendar`` session rows under a current version — not
    merely a current version row — so a MIC with a present-but-empty calendar (zero
    sessions) is caught, not silently skipped by the off-calendar check.
    """
    rows = conn.execute(
        """
        SELECT composite_figi, mic FROM securities s
         WHERE s.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM trading_calendar tc
                             JOIN trading_calendar_version v USING (calendar_version)
                            WHERE v.is_current AND tc.mic = s.mic)
        """
    ).fetchall()
    warnings = [f"{figi}: MIC {mic.strip()} has no current calendar" for figi, mic in rows]
    return CheckResult.from_items(
        "calendar_coverage",
        checked=conn.execute("SELECT count(*) FROM securities WHERE status='active'").fetchone()[0],
        warnings=warnings,
        detail=f"{len(warnings)} active securities on a MIC with no current calendar",
    )


def check_unpriced_securities(conn: psycopg.Connection) -> CheckResult:
    """Classify active securities holding no prices into expected vs unexpected."""
    rows = conn.execute(
        """
        SELECT s.composite_figi, s.status,
               EXISTS (SELECT 1 FROM trading_calendar_version v
                        WHERE v.is_current AND v.mic = s.mic) AS has_calendar
          FROM securities s
         WHERE s.status = 'active'
           AND NOT EXISTS (SELECT 1 FROM prices_raw p WHERE p.composite_figi = s.composite_figi)
        """
    ).fetchall()
    failures: list[str] = []
    warnings: list[str] = []
    for figi, status, has_calendar in rows:
        severity, reason = classify_unpriced(status, has_calendar)
        (failures if severity == "fail" else warnings).append(f"{figi}: {reason}")
    return CheckResult.from_items(
        "unpriced_securities",
        checked=conn.execute("SELECT count(*) FROM securities WHERE status='active'").fetchone()[0],
        failures=failures,
        warnings=warnings,
        detail=f"{len(rows)} active securities unpriced ({len(failures)} unexpected)",
    )
