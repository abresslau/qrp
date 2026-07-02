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

WEIGHTINGS = ("equal", "cap", "inverse_vol")
REBALANCES = ("monthly", "quarterly")
DEFAULT_TOP_PCT = 0.2  # the quintile default when neither selection is given
DEFAULT_STICKY_KEEP_MULT = 1.5  # a held name is retained while it stays within 1.5x the entry cut
_W_1Y = 11  # fact_asset_metrics window for the 1Y vol/Sharpe reads (matches signals._W_1Y)
# Minimum daily-return observations for an inverse-vol weight. fact_asset_metrics publishes a
# non-NULL vol_tr from as few as MIN_OBS=2 returns; a 2-obs vol can be near-zero, so 1/vol_tr would
# explode and concentrate the leg on a fragile name. Match signals.vol_1y's >=60 floor.
_MIN_VOL_OBS = 60


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


def _select_long_short(
    raw: dict[str, float],
    direction: str,
    long_pct: float | None,
    long_n: int | None,
    short_pct: float | None,
    short_n: int | None,
    held_long: set[str],
    held_short: set[str],
    keep_mult: float,
) -> tuple[list[str], list[str]]:
    """Long the favourable end and short the unfavourable end of ``raw``, with STICKY selection.

    ``direction`` orients favourability (``high`` → largest raw is best, so longs=top by value,
    shorts=bottom). Each side is sized by its ``_pct`` (a fraction of the covered names, ceil-ed,
    floor 1) XOR ``_n``. **Sticky (hysteresis):** a name already held on a side (``held_long`` /
    ``held_short``) is retained while it stays within the wider ``keep_mult × entry_cut`` band and
    only replaced once it exits — this damps the name churn a hard cutoff produces each rebalance.
    Held-and-still-eligible names fill the side first (rank order), then top-ranked newcomers fill
    the remaining slots up to the target size. Longs and shorts are disjoint (a name can't be both).
    """
    if not raw:
        return [], []
    sign = 1.0 if direction == "high" else -1.0
    # best-first for longs; the reverse is worst-first for shorts. figi tiebreak = reproducible.
    long_order = [f for f, _ in sorted(raw.items(), key=lambda kv: (-kv[1] * sign, kv[0]))]
    short_order = list(reversed(long_order))
    total = len(long_order)

    def _size(pct: float | None, n: int | None) -> int:
        if n is not None:
            return min(total, n)
        return max(1, math.ceil(total * (pct if pct is not None else DEFAULT_TOP_PCT)))

    def _pick(order: list[str], size: int, held: set[str], exclude: set[str]) -> list[str]:
        keep_cut = min(total, max(size, math.ceil(size * keep_mult)))
        # held names still inside the keep band, in rank order — retained over fresh entrants
        picked = [f for f in order[:keep_cut] if f in held and f not in exclude]
        picked = picked[:size]
        for f in order:  # fill remaining slots with the top-ranked names not already picked
            if len(picked) >= size:
                break
            if f not in picked and f not in exclude:
                picked.append(f)
        return picked

    longs = _pick(long_order, _size(long_pct, long_n), held_long, exclude=set())
    shorts = _pick(short_order, _size(short_pct, short_n), held_short, exclude=set(longs))
    return longs, shorts


def _neutral_weights(
    eq_conn,
    longs: list[str],
    shorts: list[str],
    d: date,
    weighting: str,
    long_mass: float,
    short_mass: float,
) -> tuple[dict[str, float], int, int]:
    """Signed target weights: longs to ``+long_mass``, shorts to ``−short_mass`` (net & gross set
    by the masses the caller passes — dollar-neutral L/S uses 0.5/0.5 → net 0, gross 1).

    ``weighting='inverse_vol'`` sets each name ∝ ``1/vol_tr`` (1Y ``fact_asset_metrics``,
    ``gated=false``, positive vol) within its side; ``'equal'`` splits the side's mass evenly. A
    name lacking a positive ``vol_tr`` is DROPPED from its side under inverse-vol (counted, never
    zero-weighted — a zero weight would silently misstate the book). Returns
    ``(weights, dropped_long, dropped_short)``; a side with no usable name contributes nothing (the
    caller decides whether the rebalance is still valid).
    """
    vol: dict[str, float] = {}
    if weighting == "inverse_vol":
        names = list(longs) + list(shorts)
        if names:
            rows = eq_conn.execute(
                "SELECT composite_figi, vol_tr FROM fact_asset_metrics "
                "WHERE window_id=%s AND gated=false AND vol_tr IS NOT NULL AND vol_tr > 0 "
                "AND n_obs >= %s AND as_of_date=%s AND composite_figi = ANY(%s)",
                (_W_1Y, _MIN_VOL_OBS, d, names),
            ).fetchall()
            vol = {f: float(v) for f, v in rows if v is not None and float(v) > 0}

    def _side(names: list[str], mass: float, sgn: float) -> tuple[dict[str, float], int]:
        if weighting == "inverse_vol":
            iv = {f: 1.0 / vol[f] for f in names if f in vol}
            dropped = len(names) - len(iv)
            tot = sum(iv.values())
            if tot <= 0.0:
                return {}, dropped
            return {f: sgn * mass * (v / tot) for f, v in iv.items()}, dropped
        # equal-weight the side's mass
        if not names:
            return {}, 0
        w = sgn * mass / len(names)
        return {f: w for f in names}, 0

    lw, dl = _side(longs, long_mass, 1.0)
    sw, ds = _side(shorts, short_mass, -1.0)
    weights = {**lw, **sw}
    return weights, dl, ds


def _cap_weights(conn, eq_conn, figis: list[str], d: date) -> tuple[dict[str, float], int]:
    """Market-cap weights at ``d`` for the holding.

    Names with no POSITIVE market cap on/before ``d`` are DROPPED from the holding and
    counted (second element) — a zero weight would silently misstate the strategy; an
    equal-weight fallback would misstate the spec. (The seam's size factor already
    filters to positive caps, so ``caps`` entries are usable by construction.)
    """
    caps = {
        f: v
        for f, v in raw_factor("size", figis, d, sym_conn=conn, eq_conn=eq_conn).items()
        if v > 0
    }
    dropped = len(figis) - len(caps)
    if not caps:
        return {}, dropped
    total = sum(caps.values())
    return {f: v / total for f, v in caps.items()}, dropped


def _daily_weighted(conn, weights: dict[str, float], lo: date, hi: date) -> dict[date, float]:
    """Portfolio daily return of a fixed-weight holding over (lo, hi], rescaled by GROSS present.

    Daily P&L is the inner product ``Σ(wᵢ·prᵢ)`` over the names that priced that day, divided by
    the **gross** weight present that day (``Σ|wᵢ|``) — a partial-coverage rescale, NOT a ``÷Σwᵢ``
    net normalisation. For a long-only book (all ``wᵢ ≥ 0``, ``Σwᵢ = 1``) gross == net, so this is
    byte-identical to the historical ``Σ(w·pr)/Σw``. For a **signed dollar-neutral** book
    (``Σwᵢ = 0``, ``Σ|wᵢ| = 1``) the old net normalisation divided by ~0 and the ``cw > 0`` gate
    dropped EVERY day (an empty backtest) — dividing by the gross fixes that (the net-zero trap).
    A date with no priced holding is absent.
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
        acc[1] += abs(w)  # GROSS present — long-only reduces to Σw; dollar-neutral stays > 0
    return {d: s / gross for d, (s, gross) in agg.items() if gross > 0}


def score_weights(
    eq_conn: psycopg.Connection, weights: dict[str, float], start: date, end: date
) -> dict:
    """Score a FIXED weight vector over (start, end] — THE candidate-scoring seam (Q7.4).

    The optimiser calls this to score solved allocations out-of-sample (PRD §4.9 "uses
    backtests to score candidates"): the same daily-rebalanced-to-target weighting and
    stats machinery as a full run, with no persistence. Returns the `_stats` dict plus
    ``n_days``; all-None stats when no holding day priced in the window. ``eq_conn`` is the
    equity DB (fact_returns).
    """
    daily_map = _daily_weighted(eq_conn, weights, start, end)
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
    *args,
    universe_conn: psycopg.Connection | None = None,
    equity_conn: psycopg.Connection | None = None,
    **kwargs,
) -> dict:
    """Public entry: guarantee universe-membership + equity (fact_returns) connections (their own
    DBs), closing each iff we opened it. All other args pass straight to :func:`_run_backtest`."""
    from contextlib import ExitStack

    from backtest.db import connect as _connect

    with ExitStack() as stack:
        if universe_conn is None:
            from universe.db import connect as _u_connect
            universe_conn = stack.enter_context(_u_connect())
        if equity_conn is None:
            equity_conn = stack.enter_context(_connect("equity"))
        return _run_backtest(
            *args, universe_conn=universe_conn, equity_conn=equity_conn, **kwargs
        )


def _run_backtest(
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
    long_pct: float | None = None,
    long_n: int | None = None,
    short_pct: float | None = None,
    short_n: int | None = None,
    sticky_keep_mult: float = DEFAULT_STICKY_KEEP_MULT,
    return_daily: bool = False,
    alt_conn: psycopg.Connection | None = None,
    macro_conn: psycopg.Connection | None = None,
    universe_conn: psycopg.Connection | None = None,
    equity_conn: psycopg.Connection | None = None,
) -> dict:
    """Run the spec'd strategy. The full spec persists on the run (FR-18 reproducibility).

    Selection: ``top_pct`` XOR ``top_n`` — both given is an ERROR (no silent
    preference); neither given falls back to the documented top-quintile default.
    ``alt_conn``/``macro_conn`` are required only when the chosen factor's declared
    inputs need them (signals.required_modules). ``universe_conn`` reads point-in-time
    membership from the universe package's own DB; ``equity_conn`` reads fact_returns from the
    equity package's own DB (both guaranteed by the public ``run_backtest`` wrapper).
    """
    conn = sym_conn  # sym reads (fundamentals via _cap_weights/size)
    eq_conn = equity_conn  # fact_returns reads (the equity DB; the wrapper guarantees one)
    u_conn = universe_conn  # membership reads (its own DB; the public wrapper guarantees one)
    bt_conn.autocommit = True
    try:
        direction = factor_direction(factor)
    except ValueError as exc:
        return {"error": str(exc)}
    if weighting not in WEIGHTINGS:
        return {"error": f"unknown weighting {weighting!r} (one of {WEIGHTINGS})"}
    if rebalance not in REBALANCES:
        return {"error": f"unknown rebalance {rebalance!r} (one of {REBALANCES})"}
    # Long/short mode is engaged the moment either short selector is given. A dollar-neutral book
    # can't be cap-weighted (mcap has no meaning on the short leg) — reject that combo loudly.
    want_shorts = short_pct is not None or short_n is not None
    if long_pct is not None and long_n is not None:
        return {"error": "give long_pct OR long_n, not both"}
    if short_pct is not None and short_n is not None:
        return {"error": "give short_pct OR short_n, not both"}
    if long_n is not None and long_n < 1:
        return {"error": f"long_n must be >= 1 (got {long_n})"}
    if short_n is not None and short_n < 1:
        return {"error": f"short_n must be >= 1 (got {short_n})"}
    if want_shorts and weighting == "cap":
        return {"error": "cap weighting is long-only; use 'equal' or 'inverse_vol' with shorts"}
    if sticky_keep_mult < 1.0:
        return {"error": f"sticky_keep_mult must be >= 1.0 (got {sticky_keep_mult})"}
    if not want_shorts:
        # LONG-ONLY path — unchanged: selection/weighting run through the historical top_pct/top_n
        # + _select_top so an existing long-only spec is byte-identical. long_*/short_* are the
        # long/short API only — a long_* without a short selector is a misconfig, not a silent
        # no-op. (inverse_vol is a new long-only-compatible weighting.)
        if long_pct is not None or long_n is not None:
            return {"error": "long_pct/long_n require a short selector; long-only sizes with "
                             "top_pct/top_n"}
        if top_pct is not None and top_n is not None:
            return {"error": "give top_pct OR top_n, not both"}
        if top_n is not None and top_n < 1:
            return {"error": f"top_n must be >= 1 (got {top_n})"}
        if top_pct is None and top_n is None:
            top_pct = DEFAULT_TOP_PCT  # the documented top-quintile default
    else:
        # LONG/SHORT path — the long leg is sized by long_*; top_* is meaningless here (would be
        # silently dropped), so reject it rather than accept-and-ignore.
        if top_pct is not None or top_n is not None:
            return {"error": "top_pct/top_n are long-only; a long/short run sizes its long leg "
                             "with long_pct/long_n"}
        if long_pct is None and long_n is None:
            long_pct = DEFAULT_TOP_PCT  # L/S long side defaults to the top quintile

    members = _members(u_conn, universe_id)  # all-ever: calendar + data range only
    if not members:
        return {"error": f"unknown or empty universe {universe_id!r}"}
    rng = eq_conn.execute(
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
    days = _trading_days(eq_conn, members, start_date, end_date)
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
    dropped_no_mcap = 0     # long-only cap-weighting drops (unchanged)
    dropped_no_vol = 0      # inverse-vol names with no positive vol_tr (long/short)
    held_long: set[str] = set()   # carried across rebalances for sticky selection
    held_short: set[str] = set()
    # dollar-neutral L/S puts ±0.5 on each side (net 0, gross 1); long-only puts the full 1.0 long.
    long_mass, short_mass = (0.5, 0.5) if want_shorts else (1.0, 0.0)
    for d in all_rebals:
        mem = _members(u_conn, universe_id, d)  # point-in-time roster — no survivorship bias
        if not mem:
            continue
        try:
            raw = raw_factor(factor, mem, d, sym_conn=conn, eq_conn=eq_conn,
                             alt_conn=alt_conn, macro_conn=macro_conn)
        except ValueError as exc:  # missing required module connection — caller error
            return {"error": str(exc)}
        if len(raw) < max(20, int(0.5 * len(mem))):
            continue
        if want_shorts:
            longs, shorts = _select_long_short(
                raw, direction, long_pct, long_n, short_pct, short_n,
                held_long, held_short, sticky_keep_mult,
            )
            if not longs or not shorts:
                continue  # can't hold a dollar-neutral book without both legs
            w, dl, ds = _neutral_weights(eq_conn, longs, shorts, d, weighting,
                                         long_mass, short_mass)
            dropped_no_vol += dl + ds
            # inverse-vol can empty a leg (all names lacked a positive vol) — skip, don't un-neutral
            if not any(v > 0 for v in w.values()) or not any(v < 0 for v in w.values()):
                continue
            held_long, held_short = set(longs), set(shorts)
        else:
            held = _select_top(raw, direction, top_pct, top_n)  # long-only: byte-identical
            if weighting == "cap":
                w, dropped = _cap_weights(conn, eq_conn, held, d)
                dropped_no_mcap += dropped
            elif weighting == "inverse_vol":
                w, dl, _ = _neutral_weights(eq_conn, held, [], d, "inverse_vol", 1.0, 0.0)
                dropped_no_vol += dl
            else:  # equal — the historical default, untouched
                w = {f: 1.0 / len(held) for f in held} if held else {}
            held_long = set(held)
        if not w:
            continue  # a skipped rebalance contributes nothing — including its drops
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
        strat_daily.update(_daily_weighted(eq_conn, weights_at[d], d, nxt))
        # Baseline = equal weight of the SAME as-of roster, rebalanced on the same dates.
        eq = {f: 1.0 / len(members_at[d]) for f in members_at[d]}
        base_daily.update(_daily_weighted(eq_conn, eq, d, nxt))

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
    if want_shorts:  # long/short-only spec fields (long-only runs keep the historical spec shape)
        spec.update({
            "long_pct": long_pct, "long_n": long_n,
            "short_pct": short_pct, "short_n": short_n,
            "sticky_keep_mult": sticky_keep_mult,
        })
    # Book exposure diagnostics at the first rebalance (net ≈ 0 / gross ≈ 1 for a dollar-neutral
    # L/S book; net = gross = 1 for a long-only book) — makes "low vol / market-neutral" measurable.
    w0 = weights_at[rebals[0]]
    net_exposure = sum(w0.values())
    gross_exposure = sum(abs(v) for v in w0.values())
    n_long = sum(1 for v in w0.values() if v > 0)
    n_short = sum(1 for v in w0.values() if v < 0)
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
        # book exposure at the first rebalance (dollar-neutrality + leg counts)
        "net_exposure": net_exposure,
        "gross_exposure": gross_exposure,
        "n_long": n_long,
        "n_short": n_short,
        "dropped_no_mcap": dropped_no_mcap,  # cap-weighting honesty: names dropped, never zeroed
        "dropped_no_vol": dropped_no_vol,    # inverse-vol names dropped for no positive vol_tr
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
