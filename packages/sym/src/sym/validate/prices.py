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


def check_price_calendar_consistency(
    conn: psycopg.Connection, eq_conn: psycopg.Connection
) -> CheckResult:
    """No price after delisting (fail); off-calendar bars are vendor noise (warn).

    An off-calendar price means the vendor disagrees with the *authoritative*
    trading calendar (snapshotted from ``exchange_calendars``). It is benign — the
    returns engine reads sessions from the calendar, so a bar on a non-session day
    is never referenced by PR/TR — so it is a ``warn`` (vendor noise), not a hard
    failure. A price *after* ``delist_date`` is a real lifecycle violation (fail).

    Cross-DB (post equity split): prices live in the equity DB, securities/calendar in sym. We
    roster-fetch the priced figis from equity, resolve their MIC + delist_date from sym, and never
    join across the boundary.
    """
    failures: list[str] = []
    warnings: list[str] = []
    # Priced figis (equity) -> their MIC (sym). The mic set drives the off-calendar scan.
    priced_figis = [r[0] for r in eq_conn.execute(
        "SELECT DISTINCT composite_figi FROM prices_raw"
    ).fetchall()]
    mic_by_figi = {
        r[0]: (r[1].strip() if isinstance(r[1], str) else r[1])
        for r in conn.execute(
            "SELECT composite_figi, mic FROM securities WHERE composite_figi = ANY(%s)",
            (priced_figis,),
        ).fetchall()
    } if priced_figis else {}
    figis_by_mic: dict[str, list[str]] = {}
    for figi, mic in mic_by_figi.items():
        figis_by_mic.setdefault(mic, []).append(figi)
    priced_mics = sorted(figis_by_mic)
    for mic in priced_mics:
        sessions = _current_sessions(conn, mic)
        if not sessions:
            continue  # no calendar -> reported by check_calendar_coverage
        # Bound the comparison to the snapshot's covered span: bars before the
        # calendar's first session (pre-1990 history) or after its last are not
        # "off-calendar vendor noise" — the calendar simply doesn't cover them.
        lo, hi = min(sessions), max(sessions)
        price_dates = {
            r[0] for r in eq_conn.execute(
                "SELECT DISTINCT session_date FROM prices_raw "
                "WHERE composite_figi = ANY(%s) AND session_date BETWEEN %s AND %s",
                (figis_by_mic[mic], lo, hi),
            ).fetchall()
        }
        for d in sorted(off_calendar(price_dates, sessions)):
            warnings.append(f"{mic}: vendor bar on non-session {d} (calendar authoritative)")

    # Post-delist bars: delisted roster (sym) -> their max price date (equity), compared locally.
    delist_by_figi = dict(
        conn.execute(
            "SELECT composite_figi, delist_date FROM securities WHERE delist_date IS NOT NULL"
        ).fetchall()
    )
    if delist_by_figi:
        max_px = eq_conn.execute(
            "SELECT composite_figi, max(session_date) FROM prices_raw "
            "WHERE composite_figi = ANY(%s) GROUP BY composite_figi",
            (list(delist_by_figi),),
        ).fetchall()
        failures += [
            f"{figi}: price {d} after delist"
            for figi, d in max_px
            if d is not None and d > delist_by_figi[figi]
        ]
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


def check_unpriced_securities(
    conn: psycopg.Connection, eq_conn: psycopg.Connection
) -> CheckResult:
    """Classify securities holding no prices into expected vs unexpected.

    Scans ALL lifecycle statuses — an active-only filter would make the
    delisted/suspended → "expected, warn" classification unreachable and leave an
    unpriced delisted security reported by no check at all.

    Cross-DB: the priced-figi set comes from the equity DB; the unpriced set is the difference
    against the sym master (computed locally, no cross-DB join).
    """
    priced = {r[0] for r in eq_conn.execute(
        "SELECT DISTINCT composite_figi FROM prices_raw"
    ).fetchall()}
    secs = conn.execute(
        """
        SELECT s.composite_figi, s.status,
               EXISTS (SELECT 1 FROM trading_calendar_version v
                        WHERE v.is_current AND v.mic = s.mic) AS has_calendar
          FROM securities s
        """
    ).fetchall()
    rows = [(figi, status, has_cal) for figi, status, has_cal in secs if figi not in priced]
    failures: list[str] = []
    warnings: list[str] = []
    for figi, status, has_calendar in rows:
        severity, reason = classify_unpriced(status, has_calendar)
        (failures if severity == "fail" else warnings).append(f"{figi}: {reason}")
    return CheckResult.from_items(
        "unpriced_securities",
        checked=len(secs),
        failures=failures,
        warnings=warnings,
        detail=f"{len(rows)} securities unpriced ({len(failures)} unexpected)",
    )
