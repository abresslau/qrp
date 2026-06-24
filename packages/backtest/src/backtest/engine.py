"""Walk-forward strategy backtest over sym history, driven by a strategy spec (Q6.3).

At each rebalance the factor is recomputed AT THAT DATE through the signals package's
public seam (``signals.compute.raw_factor`` — the single factor-definition source, Q9.4:
cross-module factors like fiscal_sens work wherever their input history is deep enough;
no look-ahead, never stored-score reads). The favourable top slice (quantile or top-N)
is selected and held — equal- or cap-weighted — until the next rebalance (monthly or
quarterly: first trading day of each month/quarter PRESENT IN THE DATA). Weighting
convention stated honestly: the target weights are applied to each day's returns
(renormalised over priced names), i.e. the holding is modelled as DAILY-REBALANCED to
its target weights between rebalances — not buy-and-hold drift (the original EW engine
had the same semantics; a drifting variant is a ledgered design option). Compared
against an equal-weight-of-roster baseline. Reads source modules READ-ONLY; persists
runs + curves + the full reproducible spec to the `backtest` schema.

Definition reconciliation (Q6.3): the engine's old private vol factor was un-annualised;
delegation to signals' annualised vol_1y is a monotone rescale — selections (ranks) are
identical.
"""

from __future__ import annotations

import json
import math
import statistics as st
from datetime import date

import psycopg
from signals.compute import factor_direction, raw_factor

_W_1D = 1

WEIGHTINGS = ("equal", "cap")
REBALANCES = ("monthly", "quarterly")
DEFAULT_TOP_PCT = 0.2  # the quintile default when neither selection is given


def _members(conn, universe_id: str, as_of_date: date | None = None) -> list[str]:
    """Universe membership: point-in-time as-of a date, or all-ever (``as_of_date=None``).

    All-ever is scaffolding only (trading-day calendar, data range). Holdings and the
    baseline MUST use the as-of roster — selecting today's members (`valid_to IS NULL`)
    across history is survivorship bias.
    """
    if as_of_date is None:
        sql = "SELECT DISTINCT composite_figi FROM universe_membership WHERE universe_id=%s"
        params: tuple = (universe_id,)
    else:
        sql = (
            "SELECT composite_figi FROM universe_membership WHERE universe_id=%s "
            "AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)"
        )
        params = (universe_id, as_of_date, as_of_date)
    return [r[0] for r in conn.execute(sql, params).fetchall()]


def _trading_days(conn, members, start_date, end_date) -> list[date]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT as_of_date FROM fact_returns "
            "WHERE window_id=%s AND as_of_date BETWEEN %s AND %s AND composite_figi = ANY(%s) "
            "ORDER BY as_of_date",
            (_W_1D, start_date, end_date, members),
        ).fetchall()
    ]


def _rebalance_dates(days: list[date], cadence: str) -> list[date]:
    """First trading day of each month/quarter PRESENT IN THE DATA (a series starting
    mid-quarter rebalances at its first available day, not a calendar anchor)."""
    out: list[date] = []
    seen: set[tuple[int, int]] = set()
    for d in days:
        period = d.month if cadence == "monthly" else (d.month - 1) // 3
        key = (d.year, period)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _select_top(
    raw: dict[str, float], direction: str, top_pct: float | None, top_n: int | None
) -> list[str]:
    if not raw:
        return []
    sign = 1.0 if direction == "high" else -1.0
    # secondary key = figi: ties at a quantile/top-N cut select deterministically,
    # so an identical persisted spec reproduces the identical holding
    ordered = sorted(raw.items(), key=lambda kv: (-kv[1] * sign, kv[0]))
    n = min(len(ordered), top_n) if top_n is not None else max(1, math.ceil(len(ordered) * top_pct))
    return [f for f, _ in ordered[:n]]


def _cap_weights(conn, figis: list[str], d: date) -> tuple[dict[str, float], int]:
    """Market-cap weights at ``d`` for the holding.

    Names with no POSITIVE market cap on/before ``d`` are DROPPED from the holding and
    counted (second element) — a zero weight would silently misstate the strategy; an
    equal-weight fallback would misstate the spec. (The seam's size factor already
    filters to positive caps, so ``caps`` entries are usable by construction.)
    """
    caps = {f: v for f, v in raw_factor("size", figis, d, sym_conn=conn).items() if v > 0}
    dropped = len(figis) - len(caps)
    if not caps:
        return {}, dropped
    total = sum(caps.values())
    return {f: v / total for f, v in caps.items()}, dropped


def _daily_weighted(conn, weights: dict[str, float], lo: date, hi: date) -> dict[date, float]:
    """Weighted mean daily return of a fixed-weight holding over (lo, hi].

    Weights are renormalised per date over the names that priced that day (the
    portfolio-analytics convention); a date with no priced holding is absent.
    """
    if not weights:
        return {}
    rows = conn.execute(
        "SELECT as_of_date, composite_figi, pr FROM fact_returns "
        "WHERE window_id=%s AND pr IS NOT NULL AND composite_figi = ANY(%s) "
        "AND as_of_date > %s AND as_of_date <= %s",
        (_W_1D, list(weights), lo, hi),
    ).fetchall()
    agg: dict[date, list[float]] = {}
    for d, figi, pr in rows:
        w = weights.get(figi)
        if w is None:  # defensive: the SQL already scopes to the holding
            continue
        acc = agg.setdefault(d, [0.0, 0.0])
        acc[0] += w * float(pr)
        acc[1] += w
    return {d: s / cw for d, (s, cw) in agg.items() if cw > 0}


def score_weights(
    sym_conn: psycopg.Connection, weights: dict[str, float], start: date, end: date
) -> dict:
    """Score a FIXED weight vector over (start, end] — THE candidate-scoring seam (Q7.4).

    The optimiser calls this to score solved allocations out-of-sample (PRD §4.9 "uses
    backtests to score candidates"): the same daily-rebalanced-to-target weighting and
    stats machinery as a full run, with no persistence. Returns the `_stats` dict plus
    ``n_days``; all-None stats when no holding day priced in the window.
    """
    daily_map = _daily_weighted(sym_conn, weights, start, end)
    days = sorted(daily_map)
    daily = [daily_map[d] for d in days]
    curve: list[float] = []
    cum = 1.0
    for r in daily:
        cum *= 1 + r
        curve.append(cum)
    out = _stats(daily, curve)
    out["n_days"] = len(daily)
    return out


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
        if peak > 0:  # a -100% day drives the curve to 0; don't divide by it
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
    top_pct: float | None = None,
    top_n: int | None = None,
    weighting: str = "equal",
    rebalance: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    cost_bps: float = 10.0,
    return_daily: bool = False,
    alt_conn: psycopg.Connection | None = None,
    macro_conn: psycopg.Connection | None = None,
) -> dict:
    """Run the spec'd strategy. The full spec persists on the run (FR-18 reproducibility).

    Selection: ``top_pct`` XOR ``top_n`` — both given is an ERROR (no silent
    preference); neither given falls back to the documented top-quintile default.
    ``alt_conn``/``macro_conn`` are required only when the chosen factor's declared
    inputs need them (signals.required_modules).
    """
    conn = sym_conn  # all sym reads below
    bt_conn.autocommit = True
    try:
        direction = factor_direction(factor)
    except ValueError as exc:
        return {"error": str(exc)}
    if weighting not in WEIGHTINGS:
        return {"error": f"unknown weighting {weighting!r} (one of {WEIGHTINGS})"}
    if rebalance not in REBALANCES:
        return {"error": f"unknown rebalance {rebalance!r} (one of {REBALANCES})"}
    if top_pct is not None and top_n is not None:
        return {"error": "give top_pct OR top_n, not both"}
    if top_n is not None and top_n < 1:
        return {"error": f"top_n must be >= 1 (got {top_n})"}
    if top_pct is None and top_n is None:
        top_pct = DEFAULT_TOP_PCT  # the documented top-quintile default

    members = _members(conn, universe_id)  # all-ever: calendar + data range only
    if not members:
        return {"error": f"unknown or empty universe {universe_id!r}"}
    rng = conn.execute(
        "SELECT min(as_of_date), max(as_of_date) FROM fact_returns "
        "WHERE window_id=%s AND composite_figi = ANY(%s)",
        (_W_1D, members),
    ).fetchone()
    data_lo, data_hi = rng
    start_date = start_date or (date(data_hi.year - 5, 1, 1) if data_hi else data_lo)
    if data_lo and start_date < data_lo:
        start_date = data_lo
    end_date = end_date or data_hi
    if start_date and end_date and start_date > end_date:
        return {"error": f"start_date {start_date} is after end_date {end_date}"}
    days = _trading_days(conn, members, start_date, end_date)
    if len(days) < 30:
        return {"error": f"insufficient history ({len(days)} trading days)"}
    all_rebals = _rebalance_dates(days, rebalance)

    # Only rebalance when the factor is broadly available (else the early, thinly-covered
    # months bias the result). Skip leading/thin rebalances; the curve starts where the
    # signal is real. min coverage = half the as-of roster (floor 20). This is also the
    # honesty gate that keeps sparse cross-module factors (wiki_attention's 10 names)
    # from driving a broad universe.
    rebals: list[date] = []
    weights_at: dict[date, dict[str, float]] = {}
    members_at: dict[date, list[str]] = {}
    dropped_no_mcap = 0
    for d in all_rebals:
        mem = _members(conn, universe_id, d)  # point-in-time roster — no survivorship bias
        if not mem:
            continue
        try:
            raw = raw_factor(factor, mem, d, sym_conn=conn,
                             alt_conn=alt_conn, macro_conn=macro_conn)
        except ValueError as exc:  # missing required module connection — caller error
            return {"error": str(exc)}
        if len(raw) < max(20, int(0.5 * len(mem))):
            continue
        held = _select_top(raw, direction, top_pct, top_n)
        if weighting == "cap":
            w, dropped = _cap_weights(conn, held, d)
        else:
            w, dropped = ({f: 1.0 / len(held) for f in held} if held else {}), 0
        if not w:
            continue  # a skipped rebalance contributes nothing — including its drops
        dropped_no_mcap += dropped
        rebals.append(d)
        members_at[d] = mem
        weights_at[d] = w
    if len(rebals) < 2:
        return {"error": f"factor {factor!r} lacks broad coverage for {universe_id!r} in range"}

    # Turnover (one-way, ½Σ|Δw| per rebalance vs the prior target) and the cost it implies.
    # v1 charges REBALANCE-DATE turnover at a flat per-unit bps; the daily-rebalance-to-target
    # abstraction's intra-period maintenance trades and an ADV/impact term are ledgered
    # refinements (the deep-research finding refuted a linear-per-ADV impact rule). cost_bps
    # defaults to 10 (liquid large-cap one-way) so a backtest is NET by default — the credible
    # cost is construction-dependent, so pass cost_bps=0 for a gross run or a higher cost for a
    # less-liquid book. Turnover is reported regardless so the assumption is always visible.
    turnover_at: dict[date, float] = {}
    prev_w: dict[str, float] = {}
    for d in rebals:
        w = weights_at[d]
        names = set(w) | set(prev_w)
        turnover_at[d] = 0.5 * sum(abs(w.get(f, 0.0) - prev_w.get(f, 0.0)) for f in names)
        prev_w = w

    strat_daily: dict[date, float] = {}
    base_daily: dict[date, float] = {}
    for i, d in enumerate(rebals):
        nxt = rebals[i + 1] if i + 1 < len(rebals) else end_date
        strat_daily.update(_daily_weighted(conn, weights_at[d], d, nxt))
        # Baseline = equal weight of the SAME as-of roster, rebalanced on the same dates.
        eq = {f: 1.0 / len(members_at[d]) for f in members_at[d]}
        base_daily.update(_daily_weighted(conn, eq, d, nxt))

    common = sorted(set(strat_daily) & set(base_daily))
    if not common:
        return {"error": "no overlapping strategy/baseline trading days in range"}

    # Map each rebalance's cost onto the first scored day on/after it (position established).
    cost_on_date: dict[date, float] = {}
    if cost_bps:
        rate = cost_bps / 1e4
        for d in rebals:
            hit = next((cd for cd in common if cd >= d), None)
            if hit is not None:
                cost_on_date[hit] = cost_on_date.get(hit, 0.0) + turnover_at[d] * rate

    s_cum = b_cum = s_cum_net = 1.0
    s_curve, s_curve_net, b_curve = [], [], []
    s_ser, s_ser_net, b_ser, points = [], [], [], []
    for d in common:
        gross_r = strat_daily[d]
        net_r = gross_r - cost_on_date.get(d, 0.0)
        s_cum *= 1 + gross_r
        s_cum_net *= 1 + net_r
        b_cum *= 1 + base_daily[d]
        s_ser.append(gross_r)
        s_ser_net.append(net_r)
        b_ser.append(base_daily[d])
        s_curve.append(s_cum)
        s_curve_net.append(s_cum_net)
        b_curve.append(b_cum)
        # the persisted curve is the headline: net when costs are modelled, else gross.
        points.append((d, s_cum_net if cost_bps else s_cum, b_cum))

    gross_stats = _stats(s_ser, s_curve)
    base_stats = _stats(b_ser, b_curve)
    strat_stats = _stats(s_ser_net, s_curve_net) if cost_bps else gross_stats

    # Spread t-stat of the (headline) strategy-minus-baseline daily excess. The Harvey-Liu-Zhu
    # multiple-testing hurdle for a NEWLY claimed factor is t>3.0, not the naive 2.0 — surfaced
    # so a sweep's winner is judged against the right bar, not in-sample luck.
    headline = s_ser_net if cost_bps else s_ser
    excess = [headline[i] - b_ser[i] for i in range(len(common))]
    spread_tstat: float | None = None
    if len(excess) > 1:
        me = st.mean(excess)
        sde = st.pstdev(excess)
        spread_tstat = (me / sde * math.sqrt(len(excess))) if sde > 0 else None

    years = (common[-1] - common[0]).days / 365.25
    turnover_total = sum(turnover_at.values())
    spec = {
        "factor": factor,
        "universe": universe_id,
        "top_pct": top_pct,
        "top_n": top_n,
        "weighting": weighting,
        "rebalance": rebalance,
        "cost_bps": cost_bps,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }
    summary = {
        "strategy": strat_stats,
        "baseline": base_stats,
        "excess_total": (
            (strat_stats["total_return"] - base_stats["total_return"])
            if strat_stats["total_return"] is not None and base_stats["total_return"] is not None
            else None
        ),
        "first_rebalance": rebals[0].isoformat(),
        "first_holding_n": len(weights_at[rebals[0]]),
        "dropped_no_mcap": dropped_no_mcap,  # cap-weighting honesty: names dropped, never zeroed
        # turnover + transaction-cost honesty (always reported; cost applied only when cost_bps>0)
        "turnover_ann": (turnover_total / years) if years > 0 else None,
        "turnover_total": turnover_total,
        "cost_bps": cost_bps,
        "cost_drag_total": sum(cost_on_date.values()),
        "strategy_gross": gross_stats if cost_bps else None,  # net is the headline when costed
        # statistical-significance guardrail (Harvey-Liu-Zhu): hurdle is t>3.0, not 2.0
        "spread_tstat": spread_tstat,
        "spread_tstat_hurdle": 3.0,
        "spread_significant": (spread_tstat is not None and spread_tstat > 3.0),
    }

    # One transaction: never persist a run row whose curve points failed to land.
    with bt_conn.transaction():
        run_id = bt_conn.execute(
            """
            INSERT INTO backtest.run
                (factor, universe_id, top_pct, rebalance, start_date, end_date, n_days,
                 n_rebalances, summary, spec)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING run_id
            """,
            (factor, universe_id, top_pct if top_pct is not None else 0.0, rebalance,
             common[0], common[-1], len(common), len(rebals),
             json.dumps(summary), json.dumps(spec)),
        ).fetchone()[0]
        # Persist the curve (sample to <= ~400 points; always keep the final point so the
        # stored curve's last value ties to the summary's total_return).
        step = max(1, len(points) // 400)
        last_idx = len(points) - 1
        with bt_conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO backtest.point (run_id, obs_date, strat_cum, base_cum) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                [(run_id, d, s, b) for idx, (d, s, b) in enumerate(points)
                 if idx % step == 0 or idx == last_idx],
            )
    # Holdings per rebalance date — the paper portfolio's weight vectors over time
    # (Q6.4: a backtest can be materialised as a Portfolio for analytics to measure).
    # Cap-weighted runs carry their actual weights.
    weight_vectors = {
        d.isoformat(): [[f, w] for f, w in weights_at[d].items()]
        for d in rebals
        if weights_at[d]
    }
    out = {"run_id": int(run_id), "factor": factor, "universe_id": universe_id,
           "spec": spec, "n_days": len(common), "n_rebalances": len(rebals),
           "summary": summary, "weight_vectors": weight_vectors}
    if return_daily:
        # the headline daily return series (net when costed) aligned to `common` — the raw
        # series a sweep needs for Deflated Sharpe / PBO (the sampled curve is too lossy).
        out["daily"] = [[d.isoformat(), headline[i]] for i, d in enumerate(common)]
    return out


if __name__ == "__main__":
    from backtest.db import connect

    sym_conn = connect("sym")
    bt_conn = connect()
    try:
        print(json.dumps(run_backtest(sym_conn, bt_conn), indent=2, default=str))
    finally:
        sym_conn.close()
        bt_conn.close()
