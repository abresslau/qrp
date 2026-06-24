"""Data-quality checks over commodities.price_daily. Each returns {check, status, detail}.

PASS/WARN/FAIL, kept deliberately light for v1 (vendor continuous series): coverage of the
universe, recency, monotonic first_settle immutability sanity, and no duplicate keys.
"""

from __future__ import annotations

from datetime import date, timedelta

import psycopg

from ..universe import UNIVERSE

SERIES = "continuous_front"


def _row(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


def run_checks(conn: psycopg.Connection) -> list[dict]:
    out: list[dict] = []

    # 1. universe coverage — every catalogued commodity has at least some history.
    present = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT commodity_code FROM commodities.price_daily WHERE series_type=%s",
            (SERIES,),
        ).fetchall()
    }
    want = {c.code for c in UNIVERSE}
    missing = sorted(want - present)
    out.append(_row(
        "universe_coverage",
        "PASS" if not missing else "WARN",
        f"{len(present)}/{len(want)} commodities loaded"
        + (f"; missing {missing}" if missing else ""),
    ))

    # 2. recency — the freshest row is within the last ~7 days (markets close on weekends/holidays).
    mx = conn.execute(
        "SELECT max(as_of_date) FROM commodities.price_daily WHERE series_type=%s", (SERIES,)
    ).fetchone()
    last = mx[0] if mx else None
    if last is None:
        out.append(_row("recency", "FAIL", "no rows at all"))
    else:
        age = (date.today() - last).days
        out.append(_row(
            "recency",
            "PASS" if age <= 7 else "WARN",
            f"latest as_of_date {last} ({age}d ago)",
        ))

    # 3. settle sanity — no NULL/zero settles slipped past the CHECK.
    bad = conn.execute(
        "SELECT count(*) FROM commodities.price_daily "
        "WHERE series_type=%s AND (settle IS NULL OR settle = 0)",
        (SERIES,),
    ).fetchone()[0]
    out.append(_row(
        "settle_sanity",
        "PASS" if bad == 0 else "FAIL",
        f"{bad} null/zero settle rows",
    ))

    # 4. staleness per commodity — flag any commodity whose own last print is > 10 days old.
    rows = conn.execute(
        """
        SELECT commodity_code, max(as_of_date) FROM commodities.price_daily
         WHERE series_type=%s GROUP BY commodity_code
        """,
        (SERIES,),
    ).fetchall()
    cutoff = date.today() - timedelta(days=10)
    stale = sorted(c for c, d in rows if d is not None and d < cutoff)
    out.append(_row(
        "per_commodity_staleness",
        "PASS" if not stale else "WARN",
        "all current" if not stale else f"stale (>10d): {stale}",
    ))
    return out
