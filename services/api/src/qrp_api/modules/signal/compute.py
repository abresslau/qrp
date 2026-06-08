"""Compute derived cross-sectional factors from sym data and store them in `signal`.

Reads sym READ-ONLY (fact_returns, fundamentals, universe_membership); writes only the
QRP-managed `signal` schema. Factors are scored cross-sectionally within a universe as-of
a date: raw value, favourable-oriented z-score, rank (1 = most favourable), and percentile.
Coverage gaps are simply absent rows (never fabricated).
"""

from __future__ import annotations

import statistics as st
from datetime import date, timedelta

import psycopg

# window_id constants (return_window): 1='1D', 7='1M', 11='1Y'.
_W_1D, _W_1M, _W_1Y = 1, 7, 11

FACTORS = {
    "mom_12_1": {
        "name": "12-1 Momentum",
        "description": "Trailing 12-month price return excluding the most recent month "
        "(winsorised at 1/99 pct).",
        "direction": "high",
    },
    "vol_1y": {
        "name": "Volatility (1Y)",
        "description": "Annualised standard deviation of daily price returns (low-vol factor; "
        "winsorised at 1/99 pct).",
        "direction": "low",
    },
    "size": {
        "name": "Size",
        "description": "Market capitalisation (USD); the size factor favours smaller names.",
        "direction": "low",
    },
}


def _ensure_catalog(conn: psycopg.Connection) -> None:
    for key, f in FACTORS.items():
        conn.execute(
            "INSERT INTO signal.factor (factor_key, name, description, direction) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (factor_key) DO UPDATE SET "
            "name=EXCLUDED.name, description=EXCLUDED.description, direction=EXCLUDED.direction",
            (key, f["name"], f["description"], f["direction"]),
        )


def _members(conn: psycopg.Connection, universe_id: str, as_of: date) -> list[str]:
    # Current roster (valid_to IS NULL) — decoupled from the data as-of so build-forward
    # universes (e.g. B3 ibov/ibx, valid_from = refresh date) still score against the latest
    # available fact_returns date.
    rows = conn.execute(
        "SELECT composite_figi FROM universe_membership "
        "WHERE universe_id=%s AND valid_to IS NULL",
        (universe_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _raw_momentum(conn, members, as_of) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT a.composite_figi, (1 + a.pr) / NULLIF(1 + b.pr, 0) - 1
          FROM fact_returns a
          JOIN fact_returns b
            ON b.composite_figi = a.composite_figi AND b.as_of_date = a.as_of_date
         WHERE a.window_id = %s AND b.window_id = %s AND a.as_of_date = %s
           AND a.pr IS NOT NULL AND b.pr IS NOT NULL AND a.composite_figi = ANY(%s)
        """,
        (_W_1Y, _W_1M, as_of, members),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _raw_vol(conn, members, as_of) -> dict[str, float]:
    start = as_of - timedelta(days=365)
    rows = conn.execute(
        """
        SELECT composite_figi, stddev_samp(pr) * sqrt(252)
          FROM fact_returns
         WHERE window_id = %s AND pr IS NOT NULL AND as_of_date > %s
           AND composite_figi = ANY(%s)
         GROUP BY composite_figi HAVING count(*) >= 60
        """,
        (_W_1D, start, members),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _raw_size(conn, members) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
          FROM fundamentals
         WHERE composite_figi = ANY(%s) AND market_cap_usd IS NOT NULL AND market_cap_usd > 0
         ORDER BY composite_figi, as_of_date DESC
        """,
        (members,),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _winsorize(raw: dict[str, float], lo: float = 0.01, hi: float = 0.99) -> dict[str, float]:
    """Clip raw factor values to the [p1, p99] cross-sectional range (standard quant
    winsorisation) so a single extreme name can't dominate the z-score/scaling. Order is
    preserved (monotone clip), so ranks are unchanged except ties at the caps."""
    vals = sorted(raw.values())
    n = len(vals)
    if n < 5:
        return raw
    plo = vals[max(0, int(lo * n))]
    phi = vals[min(n - 1, int(hi * n))]
    return {f: min(max(v, plo), phi) for f, v in raw.items()}


def _store(conn, universe_id, as_of, factor_key, direction, raw: dict[str, float]) -> int:
    if not raw:
        return 0
    raw = _winsorize(raw)  # cap extremes before scaling/ranking (e.g. SNDK momentum +3495%)
    vals = list(raw.values())
    mu = st.mean(vals)
    sd = st.pstdev(vals) if len(vals) > 1 else 0.0
    # Favourable orientation: 'high' -> larger raw better; 'low' -> smaller raw better.
    sign = 1.0 if direction == "high" else -1.0
    ordered = sorted(raw.items(), key=lambda kv: kv[1] * sign, reverse=True)  # best first
    n = len(ordered)
    for i, (figi, val) in enumerate(ordered):
        z = (sign * (val - mu) / sd) if sd > 0 else 0.0
        rank = i + 1
        pctile = (n - i) / n  # 1.0 = most favourable
        conn.execute(
            """
            INSERT INTO signal.score
                (universe_id, as_of_date, factor_key, composite_figi, raw, zscore, rank, pctile)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_id, as_of_date, factor_key, composite_figi)
            DO UPDATE SET raw=EXCLUDED.raw, zscore=EXCLUDED.zscore, rank=EXCLUDED.rank,
                          pctile=EXCLUDED.pctile
            """,
            (universe_id, as_of, factor_key, figi, val, z, rank, pctile),
        )
    return n


def compute_universe(conn: psycopg.Connection, universe_id: str, as_of: date | None = None) -> dict:
    conn.autocommit = True
    _ensure_catalog(conn)
    if as_of is None:
        as_of = conn.execute("SELECT max(as_of_date) FROM fact_returns").fetchone()[0]
    members = _members(conn, universe_id, as_of)
    counts = {
        "mom_12_1": _store(conn, universe_id, as_of, "mom_12_1", "high",
                           _raw_momentum(conn, members, as_of)),
        "vol_1y": _store(conn, universe_id, as_of, "vol_1y", "low",
                         _raw_vol(conn, members, as_of)),
        "size": _store(conn, universe_id, as_of, "size", "low", _raw_size(conn, members)),
    }
    return {"universe_id": universe_id, "as_of": as_of.isoformat(), "members": len(members),
            "scored": counts}


if __name__ == "__main__":
    from qrp_api.db import connect

    conn = connect()
    try:
        for uid in ("sp500", "ibov", "ibx"):
            print(compute_universe(conn, uid))
    finally:
        conn.close()
