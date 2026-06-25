"""Compute derived cross-sectional factors and store them in the `signals` database.

FR-21 (Story Q9.2): factors draw on MULTIPLE modules — sym (fact_returns, fundamentals,
universe_membership), altdata (Wikipedia attention), macro (US Treasury debt flows) —
each read over its OWN read-only connection and assembled app-side (AR-R2; never a
cross-database SQL join). Writes only the signals-owned schema. Every factor records its
module-qualified ``inputs`` and a ``method`` statement (Q9.3 traceability) so a derived
score is reproducible and its provenance explicit.

Factors are scored cross-sectionally within a universe as-of a date: raw value,
favourable-oriented z-score, rank (1 = most favourable), and percentile. Coverage gaps are
simply absent rows (never fabricated); a factor whose source connection is unavailable is
SKIPPED with an attributed reason, never silently zero. All reads are bounded at
``as_of_date`` on OBSERVATION dates; per-source publication lags (e.g. UST:DEBT for date
d publishes on d+1) are stated in the affected factor's method text, not silently
adjusted for.
"""

from __future__ import annotations

import json
import math
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
        "inputs": ["sym:fact_returns:1Y", "sym:fact_returns:1M", "universe:universe_membership"],
        "method": "(1+pr_1Y)/(1+pr_1M)-1 per name as of the scoring date; winsorised 1/99; "
        "direction high (recent-year winners ex the last month favoured).",
    },
    "vol_1y": {
        "name": "Volatility (1Y)",
        "description": "Annualised standard deviation of daily price returns (low-vol factor; "
        "winsorised at 1/99 pct).",
        "direction": "low",
        "inputs": ["sym:fact_returns:1D", "universe:universe_membership"],
        "method": "stddev of daily pr over the 365 days up to the scoring date x sqrt(252), "
        ">=60 obs; winsorised 1/99; direction low (the low-vol factor).",
    },
    "size": {
        "name": "Size",
        "description": "Market capitalisation (USD); the size factor favours smaller names.",
        "direction": "low",
        "inputs": ["sym:fundamentals:market_cap_usd", "universe:universe_membership"],
        "method": "latest market_cap_usd on or before the scoring date; winsorised 1/99; "
        "direction low (smaller names favoured).",
    },
    "wiki_attention": {
        "name": "Wikipedia Attention",
        "description": "7d/30d average Wikipedia pageviews — rising public attention "
        "(altdata-derived; curated-name coverage, sparse by honesty).",
        "direction": "high",
        "inputs": ["altdata:wikipedia:pageviews", "universe:universe_membership"],
        "method": "mean daily pageviews over (as_of-7d, as_of] / mean over (as_of-30d, as_of]; "
        ">=5 and >=15 obs respectively, else absent; winsorised 1/99; direction high "
        "(rising attention favoured). Coverage limited to altdata's curated wiki map.",
    },
    "fiscal_sens": {
        "name": "Fiscal-Flow Sensitivity",
        "description": "Absolute 1Y beta of daily returns to daily %-changes in US total "
        "public debt outstanding (macro UST:DEBT; low |beta| = insensitive/defensive).",
        "direction": "low",
        "inputs": ["sym:fact_returns:1D", "macro:UST:DEBT", "universe:universe_membership"],
        "method": "ABSOLUTE OLS beta |cov/var| of daily pr vs UST:DEBT daily %-change, matched "
        "on date over (as_of-365d, as_of], >=60 matched days, else absent; winsorised 1/99. "
        "Direction low favours genuinely insensitive names (|beta| near zero) — reading that "
        "as defensive is a DEFINITION choice, not an empirical claim. Caveats: macro "
        "observations are current-vintage, not point-in-time, and UST:DEBT for date d is "
        "PUBLISHED on d+1 — a score as-of d embeds that availability lag.",
    },
}


def required_modules(factor_key: str) -> frozenset[str]:
    """The non-sym input modules a factor needs (parsed from its declared inputs).

    The traceability metadata (Q9.3) is load-bearing here: consumers (e.g. the
    backtest engine, Q9.4) use it to know which module connections a factor requires
    before calling :func:`raw_factor`.
    """
    if factor_key not in FACTORS:
        raise ValueError(f"unknown factor {factor_key!r} (one of {sorted(FACTORS)})")
    modules = {ref.split(":", 1)[0] for ref in FACTORS[factor_key]["inputs"]}
    # sym + universe are always-opened core reads (fact_returns/fundamentals + the member
    # roster), not optional module connections the caller must gate on.
    return frozenset(modules - {"sym", "universe"})


def factor_direction(factor_key: str) -> str:
    """'high' or 'low' — which end of the raw value is favourable."""
    if factor_key not in FACTORS:
        raise ValueError(f"unknown factor {factor_key!r} (one of {sorted(FACTORS)})")
    return FACTORS[factor_key]["direction"]


def raw_factor(
    factor_key: str,
    members: list[str],
    as_of_date: date,
    *,
    sym_conn: psycopg.Connection,
    alt_conn: psycopg.Connection | None = None,
    macro_conn: psycopg.Connection | None = None,
) -> dict[str, float]:
    """Raw factor values per member as-of a date — THE public factor seam (Q9.4).

    The single definition source: consumers (backtest's per-rebalance recompute, the
    scoring run here) call this instead of re-implementing factor SQL. Recomputes from
    the source modules at ``as_of_date`` (no look-ahead, no stored-score reads). A
    factor whose required module connection is missing raises a ValueError NAMING the
    module — never a silent sym-only result.
    """
    needed = required_modules(factor_key)  # also validates the key
    have = {m for m, c in (("altdata", alt_conn), ("macro", macro_conn)) if c is not None}
    missing = needed - have
    if missing:
        raise ValueError(
            f"factor {factor_key!r} requires module connection(s): {', '.join(sorted(missing))}"
        )
    if factor_key == "mom_12_1":
        return _raw_momentum(sym_conn, members, as_of_date)
    if factor_key == "vol_1y":
        return _raw_vol(sym_conn, members, as_of_date)
    if factor_key == "size":
        return _raw_size(sym_conn, members, as_of_date)
    if factor_key == "wiki_attention":
        return _raw_wiki_attention(alt_conn, members, as_of_date)
    if factor_key == "fiscal_sens":
        return _raw_fiscal_sens(sym_conn, macro_conn, members, as_of_date)
    # unreachable while every FACTORS key has a branch above — a factor added to the
    # catalog without a dispatch branch must FAIL here, not silently compute the
    # wrong definition (the single-definition-source guarantee)
    raise ValueError(f"factor {factor_key!r} has no raw-computation dispatch")


def _ensure_catalog(conn: psycopg.Connection) -> None:
    for key, f in FACTORS.items():
        conn.execute(
            "INSERT INTO signals.factor (factor_key, name, description, direction, inputs, method) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (factor_key) DO UPDATE SET "
            "name=EXCLUDED.name, description=EXCLUDED.description, "
            "direction=EXCLUDED.direction, inputs=EXCLUDED.inputs, method=EXCLUDED.method",
            (key, f["name"], f["description"], f["direction"], json.dumps(f["inputs"]),
             f["method"]),
        )


def _members(conn: psycopg.Connection, universe_id: str, as_of_date: date) -> list[str]:
    # Point-in-time roster as-of the scoring date (no survivorship bias). Build-forward
    # universes (e.g. B3 ibov/ibx — membership starts at their first refresh) are honestly
    # empty before their seed date; score recent as-of dates for those.
    rows = conn.execute(
        "SELECT composite_figi FROM universe_membership "
        "WHERE universe_id=%s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)",
        (universe_id, as_of_date, as_of_date),
    ).fetchall()
    return [r[0] for r in rows]


def _raw_momentum(conn, members, as_of_date) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT a.composite_figi, (1 + a.pr) / NULLIF(1 + b.pr, 0) - 1
          FROM fact_returns a
          JOIN fact_returns b
            ON b.composite_figi = a.composite_figi AND b.as_of_date = a.as_of_date
         WHERE a.window_id = %s AND b.window_id = %s AND a.as_of_date = %s
           AND a.pr IS NOT NULL AND b.pr IS NOT NULL AND a.composite_figi = ANY(%s)
        """,
        (_W_1Y, _W_1M, as_of_date, members),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _raw_vol(conn, members, as_of_date) -> dict[str, float]:
    start_date = as_of_date - timedelta(days=365)
    # Both bounds matter: without the upper one, scoring an older as_of_date while newer
    # returns exist would quietly include future data in "1Y vol as of d".
    rows = conn.execute(
        """
        SELECT composite_figi, stddev_samp(pr) * sqrt(252)
          FROM fact_returns
         WHERE window_id = %s AND pr IS NOT NULL AND as_of_date > %s AND as_of_date <= %s
           AND composite_figi = ANY(%s)
         GROUP BY composite_figi HAVING count(*) >= 60
        """,
        (_W_1D, start_date, as_of_date, members),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _raw_size(conn, members, as_of_date) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
          FROM fundamentals
         WHERE composite_figi = ANY(%s) AND market_cap_usd IS NOT NULL AND market_cap_usd > 0
           AND as_of_date <= %s
         ORDER BY composite_figi, as_of_date DESC
        """,
        (members, as_of_date),
    ).fetchall()
    return {f: float(v) for f, v in rows if v is not None}


def _raw_wiki_attention(alt_conn, members, as_of_date) -> dict[str, float]:
    """7d/30d mean pageviews per member from the altdata package (read-only).

    Windows are anchored at ``as_of_date`` and read STRICTLY on-or-before it (no
    look-ahead); minimum-obs gates (5 in 7d, 15 in 30d) make thin names absent, never
    zero-scored. Coverage is altdata's curated wiki map — sparse by honesty.
    """
    rows = alt_conn.execute(
        """
        SELECT composite_figi,
               avg(value) FILTER (WHERE obs_date > %s::date - 7)  AS avg7,
               count(*)   FILTER (WHERE obs_date > %s::date - 7)  AS n7,
               avg(value) AS avg30,
               count(*)   AS n30
          FROM altdata.observation
         WHERE source = 'wikipedia' AND metric = 'pageviews'
           AND composite_figi = ANY(%s)
           AND obs_date > %s::date - 30 AND obs_date <= %s
         GROUP BY composite_figi
        """,
        (as_of_date, as_of_date, members, as_of_date, as_of_date),
    ).fetchall()
    out: dict[str, float] = {}
    for figi, avg7, n7, avg30, n30 in rows:
        if n7 >= 5 and n30 >= 15 and avg30 and float(avg30) > 0:
            v = float(avg7) / float(avg30)
            if math.isfinite(v):
                out[figi] = v
    return out


def _raw_fiscal_sens(sym_conn, macro_conn, members, as_of_date) -> dict[str, float]:
    """ABSOLUTE 1Y OLS beta of daily returns to UST:DEBT daily %-changes, matched on date.

    The raw value is |beta|: the factor measures SENSITIVITY magnitude, so direction
    'low' genuinely favours insensitive names (a signed beta would rank the most
    negative beta "best" — the opposite of the stated defensive reading). Two reads
    (sym daily pr; macro UST:DEBT observations), joined app-side (AR-R2). Degenerate
    cases (no debt-change variance, <60 matched days, non-finite beta) are absent,
    never NaN/inf — a non-finite score would 500 the JSON layer downstream.
    """
    start_date = as_of_date - timedelta(days=365)
    debt = macro_conn.execute(
        "SELECT obs_date, value FROM macro.observation "
        "WHERE series_id = 'UST:DEBT' AND obs_date > %s AND obs_date <= %s "
        "ORDER BY obs_date",
        (start_date - timedelta(days=7), as_of_date),  # small lead-in for the first delta
    ).fetchall()
    if len(debt) < 60:
        return {}
    changes: dict[date, float] = {}
    for (_d_prev, v_prev), (d_cur, v_cur) in zip(debt, debt[1:], strict=False):
        if v_prev and float(v_prev) != 0.0 and d_cur > start_date:
            changes[d_cur] = float(v_cur) / float(v_prev) - 1.0
    if len(changes) < 60:
        return {}
    rows = sym_conn.execute(
        "SELECT composite_figi, as_of_date, pr FROM fact_returns "
        "WHERE window_id = %s AND pr IS NOT NULL AND composite_figi = ANY(%s) "
        "AND as_of_date > %s AND as_of_date <= %s",
        (_W_1D, members, start_date, as_of_date),
    ).fetchall()
    by_figi: dict[str, list[tuple[float, float]]] = {}
    for figi, d, pr in rows:
        x = changes.get(d)
        if x is not None:  # unmatched dates dropped — matched pairs only
            by_figi.setdefault(figi, []).append((x, float(pr)))
    out: dict[str, float] = {}
    for figi, pairs in by_figi.items():
        if len(pairs) < 60:
            continue
        xs = [x for x, _ in pairs]
        ys = [y for _, y in pairs]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        var_x = sum((x - mx) ** 2 for x in xs)
        if var_x <= 0.0:
            continue  # no debt-change variance: beta undefined, absent not fabricated
        beta = sum((x - mx) * (y - my) for x, y in pairs) / var_x
        if math.isfinite(beta):
            out[figi] = abs(beta)  # sensitivity MAGNITUDE (see docstring)
    return out


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


def _store(conn, universe_id, as_of_date, factor_key, direction, raw: dict[str, float]) -> int:
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
            INSERT INTO signals.score
                (universe_id, as_of_date, factor_key, composite_figi, raw, zscore, rank, pctile)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_id, as_of_date, factor_key, composite_figi)
            DO UPDATE SET raw=EXCLUDED.raw, zscore=EXCLUDED.zscore, rank=EXCLUDED.rank,
                          pctile=EXCLUDED.pctile
            """,
            (universe_id, as_of_date, factor_key, figi, val, z, rank, pctile),
        )
    return n


def compute_universe(
    *args,
    universe_conn: psycopg.Connection | None = None,
    **kwargs,
) -> dict:
    """Public entry: guarantee a universe-membership connection (its own DB), closing it
    iff we opened it. All other args pass straight through to :func:`_compute_universe`."""
    if universe_conn is not None:
        return _compute_universe(*args, universe_conn=universe_conn, **kwargs)
    from universe.db import connect as _u_connect

    with _u_connect() as owned:  # psycopg3: closed on block exit (no leak on early returns)
        return _compute_universe(*args, universe_conn=owned, **kwargs)


def _compute_universe(
    sym_conn: psycopg.Connection,
    sig_conn: psycopg.Connection,
    universe_id: str,
    as_of_date: date | None = None,
    alt_conn: psycopg.Connection | None = None,
    macro_conn: psycopg.Connection | None = None,
    universe_conn: psycopg.Connection | None = None,
) -> dict:
    """Compute all factors for a universe as-of a date; write scores to the signals DB.

    Each input module is read over its OWN read-only connection (sym, altdata, macro —
    AR-R2 app-side assembly). A factor whose module connection was not supplied is
    SKIPPED and named on ``skipped`` with the reason — never silently zero-scored.
    ``universe_conn`` reads point-in-time membership from the universe package's own DB.
    """
    sig_conn.autocommit = True
    _ensure_catalog(sig_conn)
    if as_of_date is None:
        as_of_date = sym_conn.execute("SELECT max(as_of_date) FROM fact_returns").fetchone()[0]
        if as_of_date is None:
            return {"universe_id": universe_id, "as_of_date": None, "members": 0,
                    "scored": {}, "skipped": {}, "error": "no fact_returns data to score against"}
    members = _members(universe_conn, universe_id, as_of_date)
    counts = {
        "mom_12_1": _store(sig_conn, universe_id, as_of_date, "mom_12_1", "high",
                           _raw_momentum(sym_conn, members, as_of_date)),
        "vol_1y": _store(sig_conn, universe_id, as_of_date, "vol_1y", "low",
                         _raw_vol(sym_conn, members, as_of_date)),
        "size": _store(sig_conn, universe_id, as_of_date, "size", "low",
                       _raw_size(sym_conn, members, as_of_date)),
    }
    skipped: dict[str, str] = {}
    if alt_conn is not None:
        counts["wiki_attention"] = _store(
            sig_conn, universe_id, as_of_date, "wiki_attention", "high",
            _raw_wiki_attention(alt_conn, members, as_of_date))
    else:
        skipped["wiki_attention"] = "no altdata connection"
    if macro_conn is not None:
        counts["fiscal_sens"] = _store(
            sig_conn, universe_id, as_of_date, "fiscal_sens", "low",
            _raw_fiscal_sens(sym_conn, macro_conn, members, as_of_date))
    else:
        skipped["fiscal_sens"] = "no macro connection"
    return {"universe_id": universe_id, "as_of_date": as_of_date.isoformat(),
            "members": len(members), "scored": counts, "skipped": skipped}


def _try_connect(dbname: str):
    """A module connection, or None — an unreachable INPUT module must degrade to the
    attributed-skip path, not abort the whole run (sym-only factors still score)."""
    from signals.db import connect

    try:
        return connect(dbname)
    except Exception as exc:  # noqa: BLE001 — reported, then degraded to skip
        print(f"{dbname} unavailable ({type(exc).__name__}) — its factors will be skipped")
        return None


if __name__ == "__main__":
    from signals.db import connect

    sym_conn = connect("sym")          # sym package — read-only upstream peer (required)
    sig_conn = connect()               # signals DB — the derived store (required)
    alt_conn = _try_connect("altdata")  # optional input modules: skip-attributed if down
    macro_conn = _try_connect("macro")
    try:
        for uid in ("sp500", "ibov", "ibx"):
            print(compute_universe(sym_conn, sig_conn, uid,
                                   alt_conn=alt_conn, macro_conn=macro_conn))
    finally:
        for c in (sym_conn, sig_conn, alt_conn, macro_conn):
            if c is not None:
                c.close()
