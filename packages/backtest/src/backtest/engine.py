"""Walk-forward factor-strategy backtest over sym history.

At each monthly rebalance the factor is recomputed FROM fact_returns AT THAT DATE (no
look-ahead), the favourable top quantile is selected and held equal-weight until the next
rebalance; daily portfolio returns come from the 1D series. Compared against an
equal-weight-universe baseline. Reads sym READ-ONLY; persists to the `backtest` schema.
"""

from __future__ import annotations

import json
import math
import statistics as st
from datetime import date

import psycopg

_W_1D, _W_1M, _W_1Y = 1, 7, 11
_DIRECTION = {"mom_12_1": "high", "vol_1y": "low", "size": "low"}


def _members(conn, universe_id: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT composite_figi FROM universe_membership "
            "WHERE universe_id=%s AND valid_to IS NULL",
            (universe_id,),
        ).fetchall()
    ]


def _trading_days(conn, members, start, end) -> list[date]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT as_of_date FROM fact_returns "
            "WHERE window_id=%s AND as_of_date BETWEEN %s AND %s AND composite_figi = ANY(%s) "
            "ORDER BY as_of_date",
            (_W_1D, start, end, members),
        ).fetchall()
    ]


def _rebalance_dates(days: list[date]) -> list[date]:
    """First trading day of each month."""
    out: list[date] = []
    seen: set[tuple[int, int]] = set()
    for d in days:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _factor_at(conn, members, d: date, factor: str) -> dict[str, float]:
    if factor == "mom_12_1":
        rows = conn.execute(
            """
            SELECT a.composite_figi, (1 + a.pr) / NULLIF(1 + b.pr, 0) - 1
              FROM fact_returns a JOIN fact_returns b
                ON b.composite_figi=a.composite_figi AND b.as_of_date=a.as_of_date
             WHERE a.window_id=%s AND b.window_id=%s AND a.as_of_date=%s
               AND a.pr IS NOT NULL AND b.pr IS NOT NULL AND a.composite_figi = ANY(%s)
            """,
            (_W_1Y, _W_1M, d, members),
        ).fetchall()
    elif factor == "vol_1y":
        rows = conn.execute(
            """
            SELECT composite_figi, stddev_samp(pr)
              FROM fact_returns
             WHERE window_id=%s AND pr IS NOT NULL AND composite_figi = ANY(%s)
               AND as_of_date > (%s::date - 365) AND as_of_date <= %s
             GROUP BY composite_figi HAVING count(*) >= 60
            """,
            (_W_1D, members, d, d),
        ).fetchall()
    else:  # size: latest fundamentals market cap on/before d
        rows = conn.execute(
            """
            SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
              FROM fundamentals
             WHERE composite_figi = ANY(%s) AND market_cap_usd IS NOT NULL AND as_of_date <= %s
             ORDER BY composite_figi, as_of_date DESC
            """,
            (members, d),
        ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _select_top(raw: dict[str, float], factor: str, top_pct: float) -> list[str]:
    if not raw:
        return []
    sign = 1.0 if _DIRECTION.get(factor, "high") == "high" else -1.0
    ordered = sorted(raw.items(), key=lambda kv: kv[1] * sign, reverse=True)
    n = max(1, math.ceil(len(ordered) * top_pct))
    return [f for f, _ in ordered[:n]]


def _daily_mean(conn, figis, lo: date, hi: date) -> dict[date, float]:
    if not figis:
        return {}
    rows = conn.execute(
        "SELECT as_of_date, avg(pr) FROM fact_returns "
        "WHERE window_id=%s AND pr IS NOT NULL AND composite_figi = ANY(%s) "
        "AND as_of_date > %s AND as_of_date <= %s GROUP BY as_of_date",
        (_W_1D, figis, lo, hi),
    ).fetchall()
    return {d: float(v) for d, v in rows if v is not None}


def _stats(daily: list[float], curve: list[float]) -> dict:
    if not daily:
        return {"total_return": None, "ann_return": None, "ann_vol": None, "sharpe": None,
                "max_drawdown": None}
    n = len(daily)
    total = curve[-1] - 1.0
    ann = curve[-1] ** (252 / n) - 1.0 if curve[-1] > 0 else None
    mu = st.mean(daily)
    sd = st.pstdev(daily) if n > 1 else 0.0
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return {
        "total_return": total,
        "ann_return": ann,
        "ann_vol": sd * math.sqrt(252),
        "sharpe": (mu / sd * math.sqrt(252)) if sd > 0 else None,
        "max_drawdown": mdd,
    }


def run_backtest(
    sym_conn: psycopg.Connection,
    bt_conn: psycopg.Connection,
    factor: str = "mom_12_1",
    universe_id: str = "sp500",
    top_pct: float = 0.2,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    # sym_conn reads the hub (fact_returns/fundamentals/universe_membership); bt_conn writes
    # runs/points to the backtest database (DB-per-package; cross-DB read via psycopg).
    conn = sym_conn  # all reads below go to the sym hub
    bt_conn.autocommit = True
    members = _members(conn, universe_id)
    rng = conn.execute(
        "SELECT min(as_of_date), max(as_of_date) FROM fact_returns "
        "WHERE window_id=%s AND composite_figi = ANY(%s)",
        (_W_1D, members),
    ).fetchone()
    data_lo, data_hi = rng
    start = start or (date(data_hi.year - 5, 1, 1) if data_hi else data_lo)
    if data_lo and start < data_lo:
        start = data_lo
    end = end or data_hi
    days = _trading_days(conn, members, start, end)
    if len(days) < 30:
        return {"error": f"insufficient history ({len(days)} trading days)"}
    all_rebals = _rebalance_dates(days)

    # Only rebalance when the factor is broadly available (else the early, thinly-covered
    # months bias the result). Skip leading/thin rebalances; the curve starts where the
    # signal is real. min coverage = half the universe (floor 20).
    min_cov = max(20, int(0.5 * len(members)))
    rebals: list[date] = []
    holdings: dict[date, list[str]] = {}
    for d in all_rebals:
        raw = _factor_at(conn, members, d, factor)
        if len(raw) >= min_cov:
            rebals.append(d)
            holdings[d] = _select_top(raw, factor, top_pct)
    if len(rebals) < 2:
        return {"error": f"factor {factor!r} lacks broad coverage for {universe_id!r} in range"}

    strat_daily: dict[date, float] = {}
    for i, d in enumerate(rebals):
        nxt = rebals[i + 1] if i + 1 < len(rebals) else end
        strat_daily.update(_daily_mean(conn, holdings[d], d, nxt))
    first_holding = holdings[rebals[0]]
    base_daily = _daily_mean(conn, members, rebals[0], end)

    common = sorted(set(strat_daily) & set(base_daily))
    s_cum, b_cum = 1.0, 1.0
    s_curve, b_curve, s_ser, b_ser, points = [], [], [], [], []
    for d in common:
        s_cum *= 1 + strat_daily[d]
        b_cum *= 1 + base_daily[d]
        s_ser.append(strat_daily[d])
        b_ser.append(base_daily[d])
        s_curve.append(s_cum)
        b_curve.append(b_cum)
        points.append((d, s_cum, b_cum))

    strat_stats = _stats(s_ser, s_curve)
    base_stats = _stats(b_ser, b_curve)
    summary = {
        "strategy": strat_stats,
        "baseline": base_stats,
        "excess_total": (
            (strat_stats["total_return"] - base_stats["total_return"])
            if strat_stats["total_return"] is not None and base_stats["total_return"] is not None
            else None
        ),
        "first_rebalance": rebals[0].isoformat(),
        "first_holding_n": len(first_holding),
    }

    run_id = bt_conn.execute(
        """
        INSERT INTO backtest.run
            (factor, universe_id, top_pct, rebalance, start_date, end_date, n_days,
             n_rebalances, summary)
        VALUES (%s, %s, %s, 'monthly', %s, %s, %s, %s, %s::jsonb) RETURNING run_id
        """,
        (factor, universe_id, top_pct, common[0] if common else start,
         common[-1] if common else end, len(common), len(rebals), json.dumps(summary)),
    ).fetchone()[0]
    # Persist the curve (sample to <= ~400 points to keep it light).
    step = max(1, len(points) // 400)
    with bt_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO backtest.point (run_id, obs_date, strat_cum, base_cum) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            [(run_id, d, s, b) for idx, (d, s, b) in enumerate(points) if idx % step == 0],
        )
    # Equal-weight holdings per rebalance date — the paper portfolio's weight vectors over time
    # (Q6.4: a backtest can be materialised as a Portfolio for analytics to measure).
    weight_vectors = {
        d.isoformat(): [[f, 1.0 / len(holdings[d])] for f in holdings[d]]
        for d in rebals
        if holdings[d]
    }
    return {"run_id": int(run_id), "factor": factor, "universe_id": universe_id,
            "n_days": len(common), "n_rebalances": len(rebals), "summary": summary,
            "weight_vectors": weight_vectors}


if __name__ == "__main__":
    from backtest.db import connect, hub

    sym_conn = hub()
    bt_conn = connect()
    try:
        print(json.dumps(run_backtest(sym_conn, bt_conn), indent=2, default=str))
    finally:
        sym_conn.close()
        bt_conn.close()
