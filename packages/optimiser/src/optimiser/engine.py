"""Pure-Python mean-variance optimiser with constraints + signal tilts (no numpy).

Builds the daily-return covariance for a capped set of names from sym (read-only), then
solves long-only weights by projected gradient on the CAPPED simplex
{w : Σw=1, 0 ≤ wᵢ ≤ max_weight} (Story Q7.3 — the max-position constraint archetype;
``max_weight=None`` is the plain simplex):

- min_variance: minimise wᵀΣw
- max_sharpe: trace a small risk-aversion path (minimise λ·wᵀΣw − wᵀμ) and keep the
  allocation with the best realised Sharpe.

An optional SIGNAL TILT (Q9.4 — FR-21 "consumable by optimiser") adds −strength·wᵀz to
the objective, where z is the chosen signals factor's raw values at the covariance end
date (the signals seam — recompute-at-date, no stored-score reads), favourable-oriented
and z-scored cross-sectionally; names the factor does not cover get z=0 (NEUTRAL — an
unscored name is neither favoured nor punished, never fabricated).

Candidate scoring (Q7.4 — PRD §4.9): with ``holdout_days``, the covariance window
EXCLUDES the trailing holdout and the solution + equal-weight baseline are scored
OUT-OF-SAMPLE on it via the backtest package's ``score_weights`` seam. In-sample
expected stats remain labelled as such.

Annualised with 252. rf = 0. Reads source modules READ-ONLY; persists solutions +
weights + the full reproducible spec to the `optimiser` schema.
"""

from __future__ import annotations

import json
import math
import statistics as st
from datetime import date

import psycopg
from backtest.engine import score_weights
from signals.compute import factor_direction, raw_factor

_W_1D = 1
ANN = 252

METHODS = ("min_variance", "max_sharpe")
COV_METHODS = ("shrinkage", "sample")  # default = Ledoit-Wolf const-correlation shrinkage


def _select_names(u_conn, sym_conn, universe_id: str, n: int) -> list[str]:
    """The n largest current members by latest market cap (keeps the covariance tractable).

    Cross-DB roster-fetch: the current-member roster comes from the universe DB (``u_conn``);
    their latest ``market_cap_usd`` from sym ``fundamentals`` (``sym_conn``). Sorted + topped
    locally — no cross-DB join."""
    roster = [
        r[0]
        for r in u_conn.execute(
            "SELECT composite_figi FROM universe_membership "
            "WHERE universe_id = %s AND valid_to IS NULL",
            (universe_id,),
        ).fetchall()
    ]
    if not roster:
        return []
    # Latest market cap per roster member (sym fundamentals), then top-n by cap in Python — a
    # roster-bounded ANY(...) read (no set-returning-function scan, no cross-DB join).
    caps = sym_conn.execute(
        """
        SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
          FROM fundamentals
         WHERE composite_figi = ANY(%s) AND market_cap_usd IS NOT NULL
         ORDER BY composite_figi, as_of_date DESC
        """,
        (roster,),
    ).fetchall()
    caps.sort(key=lambda r: r[1], reverse=True)
    return [r[0] for r in caps[:n]]


def _return_matrix(
    conn, figis, lookback
) -> tuple[list[str], list[list[float]], list[date]]:
    """Aligned daily returns: keep names present on a common set of recent dates.

    Returns (kept_figis, matrix, dates) where matrix[i] is the daily series for
    kept_figis[i] and dates are the aligned trading dates (ascending).
    """
    rows = conn.execute(
        """
        SELECT as_of_date, composite_figi, pr
          FROM fact_returns
         WHERE window_id = %s AND pr IS NOT NULL AND composite_figi = ANY(%s)
           AND as_of_date > (SELECT max(as_of_date) FROM fact_returns WHERE window_id = %s)
                            - %s::int
         ORDER BY as_of_date
        """,
        (_W_1D, figis, _W_1D, lookback),
    ).fetchall()
    by_date: dict = {}
    for d, f, pr in rows:
        by_date.setdefault(d, {})[f] = float(pr)
    # Keep dates where every requested name has a return (clean covariance).
    fset = set(figis)
    dates = [d for d in sorted(by_date) if fset.issubset(by_date[d].keys())]
    if len(dates) < 30:
        # fall back: keep names that are present on the most common date set
        present = sorted(
            figis, key=lambda f: sum(1 for d in by_date if f in by_date[d]), reverse=True
        )
        # trim names with poor coverage until >=30 common dates; EVERY kept-set is
        # tested, including the final 5-name one (a feasible 5-name covariance must
        # not die as "insufficient history")
        kept = list(present)
        while len(kept) >= 5:
            ds = [d for d in sorted(by_date) if set(kept).issubset(by_date[d].keys())]
            if len(ds) >= 30:
                dates = ds
                break
            if len(kept) == 5:
                break  # the smallest allowed set still lacks history — caller errors
            kept.pop()  # drop the worst-covered name
        figis = kept
    series = {f: [by_date[d][f] for d in dates] for f in figis}
    return list(figis), [series[f] for f in figis], dates


def _mean_cov(matrix: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    n = len(matrix)
    t = len(matrix[0])
    mean = [sum(row) / t for row in matrix]
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = 0.0
            mi, mj = mean[i], mean[j]
            ri, rj = matrix[i], matrix[j]
            for k in range(t):
                s += (ri[k] - mi) * (rj[k] - mj)
            c = s / (t - 1)
            cov[i][j] = cov[j][i] = c
    return mean, cov


def _const_corr_shrinkage(matrix: list[list[float]]) -> tuple[list[list[float]], float]:
    """Ledoit-Wolf (2004) shrinkage of the sample covariance toward a constant-correlation
    target, with the closed-form optimal intensity — NO tuning parameter.

    Why (research-backed, deep-research 2026-06-23): the plain sample covariance carries
    estimation error of exactly the kind a mean-variance optimiser latches onto ("error
    maximisation", Michaud 1989); worst when n is large vs t and it can be singular. The
    shrunk estimate ``Σ̂ = δF + (1−δ)S`` is ALWAYS positive-definite (F is PD, S is PSD) and
    out-of-sample-better. Ref: Ledoit & Wolf, "Honey, I Shrunk the Sample Covariance Matrix",
    JPM 2004 (SSRN 433840).

    Target F: constant-correlation — ``f_ii = s_ii``, ``f_ij = r̄·√(s_ii·s_jj)`` with r̄ the
    average pairwise sample correlation. Optimal intensity ``δ = max(0, min(1, κ/t))`` with
    ``κ = (π − ρ)/γ``: π = Σ asymptotic variances of S's entries, ρ = Σ asymptotic covariances
    between F and S (derived from first principles for the const-corr target, holding r̄ fixed),
    γ = ‖F − S‖²_F. Estimators use the 1/t MLE covariance on demeaned data (the convention the
    LW asymptotics require); returns ``(cov, δ)``. O(n²·t) pure-Python — fine for the n≲60 the
    optimiser selects; a numpy/factor-model path is the ledgered upgrade for larger n.
    """
    n = len(matrix)
    t = len(matrix[0])
    means = [sum(r) / t for r in matrix]
    x = [[matrix[i][k] - means[i] for k in range(t)] for i in range(n)]  # demeaned
    s = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            v = sum(x[i][k] * x[j][k] for k in range(t)) / t  # 1/t MLE cov
            s[i][j] = s[j][i] = v
    var = [s[i][i] for i in range(n)]
    sd = [math.sqrt(v) if v > 0 else 0.0 for v in var]
    # average pairwise correlation r̄
    num, cnt = 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            if sd[i] > 0 and sd[j] > 0:
                num += s[i][j] / (sd[i] * sd[j])
                cnt += 1
    rbar = (num / cnt) if cnt else 0.0
    f = [[0.0] * n for _ in range(n)]  # constant-correlation target
    for i in range(n):
        f[i][i] = var[i]
        for j in range(i + 1, n):
            f[i][j] = f[j][i] = rbar * sd[i] * sd[j]
    # π: Σ asymptotic variances of the sample-cov entries. π_ij = (1/t)Σ(x_i·x_j)² − s_ij²
    pi_diag = 0.0
    pi = 0.0
    for i in range(n):
        for j in range(i, n):
            m = sum((x[i][k] * x[j][k]) ** 2 for k in range(t)) / t - s[i][j] ** 2
            pi += m if i == j else 2 * m  # symmetric: count off-diagonals twice
            if i == j:
                pi_diag += m
    # ρ: diagonal entries match F exactly (f_ii=s_ii) → their asy-cov IS their asy-var (π_ii).
    # Off-diagonals (holding r̄ fixed): ½·r̄·[√(σjj/σii)·ϑ_ii,ij + √(σii/σjj)·ϑ_jj,ij] per pair,
    # ϑ_ii,ij = (1/t)Σ x_i³x_j − σ_ii·s_ij. Summing the first term over ALL ordered i≠j pairs
    # equals the symmetric per-pair sum (the (j,i) pass supplies the second term).
    rho = pi_diag
    for i in range(n):
        for j in range(n):
            if i == j or sd[i] <= 0 or sd[j] <= 0:
                continue
            t1 = sum((x[i][k] ** 3) * x[j][k] for k in range(t)) / t
            rho += rbar * 0.5 * math.sqrt(var[j] / var[i]) * (t1 - var[i] * s[i][j])
    gamma = sum((f[i][j] - s[i][j]) ** 2 for i in range(n) for j in range(n))
    if gamma <= 0:  # sample already matches the const-corr target — nothing to shrink
        delta = 0.0
    else:
        delta = max(0.0, min(1.0, ((pi - rho) / gamma) / t))
    cov = [[delta * f[i][j] + (1 - delta) * s[i][j] for j in range(n)] for i in range(n)]
    return cov, delta


def _matvec(m, v):
    return [sum(m[i][j] * v[j] for j in range(len(v))) for i in range(len(m))]


def _project_simplex(v: list[float]) -> list[float]:
    """Euclidean projection onto {w : sum(w)=1, w>=0} (Wang & Carreira-Perpiñán)."""
    return _project_simplex_mass(v, 1.0)


def _project_capped_simplex(v: list[float], cap: float) -> list[float]:
    """Euclidean projection onto {w : Σw=1, 0 ≤ wᵢ ≤ cap}.

    Iterative cap-and-redistribute: project the free coordinates onto the simplex of
    the remaining mass; any that exceed the cap are fixed AT the cap and removed from
    the free set; repeat. Each pass fixes ≥1 more coordinate, so it terminates (≤ n
    passes), and the result is the exact Euclidean projection (the KKT active-set for
    this box-and-sum constraint). Caller guarantees feasibility (cap·n ≥ 1).
    """
    n = len(v)
    fixed: dict[int, float] = {}
    free = list(range(n))
    while True:
        mass = 1.0 - cap * len(fixed)
        sub = _project_simplex_mass([v[i] for i in free], mass)
        over = [idx for idx, w in zip(free, sub, strict=True) if w > cap + 1e-12]
        if not over:
            out = [0.0] * n
            for idx, w in zip(free, sub, strict=True):
                out[idx] = w
            for idx, w in fixed.items():
                out[idx] = w
            return out
        for idx in over:
            fixed[idx] = cap
        free = [i for i in free if i not in fixed]
        if not free:  # everything capped: feasible only when cap*n == 1 (mass exact)
            return [fixed.get(i, 0.0) for i in range(n)]


def _project_simplex_mass(v: list[float], mass: float) -> list[float]:
    """Projection onto {w : sum(w)=mass, w>=0} (the standard simplex scaled)."""
    if mass <= 0:
        return [0.0] * len(v)
    u = sorted(v, reverse=True)
    css = 0.0
    theta = 0.0
    for i, ui in enumerate(u):
        css += ui
        t = (css - mass) / (i + 1)
        if ui - t > 0:
            theta = t
    return [max(x - theta, 0.0) for x in v]


def _pgd(cov, mean, lam: float, tilt: list[float] | None = None,
         cap: float | None = None, iters: int = 800) -> list[float]:
    """Minimise lam·wᵀΣw − wᵀμ − wᵀtilt over the (capped) simplex."""
    n = len(cov)
    w = [1.0 / n] * n
    # Step from a Gershgorin bound on the largest eigenvalue of 2*lam*Σ.
    l_max = max(sum(abs(cov[i][j]) for j in range(n)) for i in range(n)) * 2 * lam + 1e-9
    step = 1.0 / l_max
    z = tilt or [0.0] * n
    project = (lambda x: _project_capped_simplex(x, cap)) if cap is not None else _project_simplex
    for _ in range(iters):
        sig_w = _matvec(cov, w)
        grad = [2 * lam * sig_w[i] - mean[i] - z[i] for i in range(n)]
        w = project([w[i] - step * grad[i] for i in range(n)])
    return w


def _stats(w, mean, cov):
    var = sum(w[i] * _matvec(cov, w)[i] for i in range(len(w)))
    exp_ret = sum(w[i] * mean[i] for i in range(len(w))) * ANN
    exp_vol = math.sqrt(max(var, 0.0) * ANN)
    sharpe = exp_ret / exp_vol if exp_vol > 0 else None
    return exp_ret, exp_vol, sharpe


def _tilt_scores(
    factor: str, figis: list[str], as_of_date: date, *,
    sym_conn, eq_conn, alt_conn=None, macro_conn=None,
) -> tuple[list[float], int]:
    """Favourable-oriented cross-sectional z-scores for the tilt term (Q9.4).

    Raw values come from the signals seam AT the covariance end date (recompute-at-date,
    the Q6.3 precedent). Orientation: direction 'low' flips sign so a HIGHER z is always
    more favourable. Names without a score get z=0 — neutral, never fabricated. Returns
    ``(z, n_scored)`` — the caller refuses a tilt that cannot apply (n_scored < 2 or a
    degenerate cross-section) rather than recording a silent no-op.
    """
    raw = raw_factor(factor, figis, as_of_date, sym_conn=sym_conn, eq_conn=eq_conn,
                     alt_conn=alt_conn, macro_conn=macro_conn)
    if len(raw) < 2:
        return [0.0] * len(figis), len(raw)
    sign = 1.0 if factor_direction(factor) == "high" else -1.0
    vals = list(raw.values())
    mu = st.mean(vals)
    sd = st.pstdev(vals)
    if sd <= 0:
        return [0.0] * len(figis), 0  # degenerate cross-section: no usable tilt
    return [sign * (raw[f] - mu) / sd if f in raw else 0.0 for f in figis], len(raw)


def solve(sym_conn: psycopg.Connection, opt_conn: psycopg.Connection,
          universe_id="sp500", method="min_variance", n=40, lookback=252,
          max_weight: float | None = None,
          signal_tilt: dict | None = None,
          holdout_days: int = 0,
          cov_method: str = "shrinkage",
          portfolios_gw=None,
          alt_conn=None, macro_conn=None,
          u_conn=None, eq_conn=None) -> dict:
    """Solve the spec'd allocation; persist solution + weights + the full spec.

    ``signal_tilt`` = ``{"factor": <signals key>, "strength": float > 0}``;
    ``holdout_days`` > 0 carves the trailing holdout OUT of the covariance window and
    scores the solution there via the backtest package; ``portfolios_gw`` saves the
    weights as a Portfolio (Q7.4). Module conns are needed only when the tilt factor's
    declared inputs demand them.
    """
    conn = sym_conn  # sym reads (fundamentals)
    opt_conn.autocommit = True
    if method not in METHODS:
        return {"error": f"unknown method {method!r} (one of {METHODS})"}
    if cov_method not in COV_METHODS:
        return {"error": f"unknown cov_method {cov_method!r} (one of {COV_METHODS})"}
    if max_weight is not None and max_weight * n < 1.0:
        return {"error": f"infeasible max_weight {max_weight} for n={n} (cap*n must be >= 1)"}
    tilt_factor = (signal_tilt or {}).get("factor")
    tilt_strength = float((signal_tilt or {}).get("strength") or 0.0)
    if signal_tilt is not None and (not tilt_factor or tilt_strength <= 0):
        return {"error": "signal_tilt needs a factor and a strength > 0"}
    if tilt_factor and method == "min_variance":
        # Honest refusal, not a fake knob: min_variance uses λ=1e6, which numerically
        # annihilates the un-scaled tilt term (~1e-6 weight shift) — the spec would
        # record a tilt that contributed nothing.
        return {"error": "signal_tilt is not meaningful under min_variance "
                         "(the variance term dominates at λ=1e6) — use max_sharpe"}

    names = _select_names(u_conn, conn, universe_id, n)
    if len(names) < 5:
        return {"error": f"too few members with market cap for {universe_id!r}"}
    figis, matrix, dates = _return_matrix(eq_conn, names, lookback)
    if len(figis) < 5 or len(matrix[0]) < 30:
        return {"error": "insufficient aligned daily history for a covariance"}
    if max_weight is not None and max_weight * len(figis) < 1.0:
        # Re-validated against the SURVIVING names: alignment can trim the set, and an
        # infeasible cap would make the projection return weights summing < 1 silently.
        return {"error": f"infeasible max_weight {max_weight} for the {len(figis)} names "
                         f"surviving alignment (cap*names must be >= 1; requested n={n})"}

    # Q7.4 holdout: the covariance window EXCLUDES the trailing holdout days, so the
    # backtest score on them is genuinely out-of-sample (no look-ahead into the score).
    holdout_dates: list[date] = []
    if holdout_days > 0:
        if len(dates) - holdout_days < 30:
            return {"error": f"holdout_days {holdout_days} leaves <30 training days "
                             f"({len(dates)} aligned)"}
        holdout_dates = dates[-holdout_days:]
        dates = dates[:-holdout_days]
        matrix = [row[: len(dates)] for row in matrix]
    cov_end = dates[-1]

    mean, sample_cov = _mean_cov(matrix)
    # Risk model: Ledoit-Wolf const-correlation shrinkage by default (the sample covariance
    # error-maximises a mean-variance solver); `sample` stays available for comparison.
    if cov_method == "shrinkage":
        cov, shrink_delta = _const_corr_shrinkage(matrix)
    else:
        cov, shrink_delta = sample_cov, None
    t = len(matrix[0])

    tilt_vec: list[float] | None = None
    tilt_coverage: int | None = None
    if tilt_factor:
        try:
            z, n_scored = _tilt_scores(tilt_factor, figis, cov_end, sym_conn=conn,
                                       eq_conn=eq_conn, alt_conn=alt_conn, macro_conn=macro_conn)
        except ValueError as exc:  # unknown factor / missing module conn — attributed
            return {"error": str(exc)}
        if n_scored < 2:
            # A tilt that cannot apply is an error, not a silently-recorded no-op.
            return {"error": f"signal_tilt factor {tilt_factor!r} scored only {n_scored} "
                             f"of {len(figis)} selected names at {cov_end} — tilt cannot apply"}
        tilt_coverage = n_scored
        tilt_vec = [tilt_strength * zi for zi in z]

    chosen_lam: float | None = None
    if method == "min_variance":
        w = _pgd(cov, mean, lam=1e6, cap=max_weight)
    else:
        # max_sharpe: trace the lambda path; each candidate is solved WITH the tilt,
        # but the winner is picked by realised in-sample Sharpe (tilt-free criterion —
        # a documented choice; a tilt-aware selection criterion is ledgered).
        best_w, best_s = None, -1e18
        for lam in (0.5, 1, 2, 5, 10, 25, 50, 100, 250):
            cand = _pgd(cov, mean, lam=lam, tilt=tilt_vec, cap=max_weight)
            _, _, s = _stats(cand, mean, cov)
            if s is not None and s > best_s:
                best_s, best_w, chosen_lam = s, cand, lam
        w = best_w or [1.0 / len(figis)] * len(figis)

    exp_ret, exp_vol, sharpe = _stats(w, mean, cov)
    ew = [1.0 / len(figis)] * len(figis)
    _, ew_vol, _ = _stats(ew, mean, cov)

    # Q7.4b: score the candidate (and the EW baseline) on the held-out window via the
    # backtest package — the optimiser-uses-backtests loop. The SPLIT is out-of-sample
    # for the covariance and the weights; the universe SELECTION is not (current
    # members by latest mcap — a stated selection-look-ahead caveat; PIT selection is
    # the ledgered upgrade). The scorer counts DB-priced days, which can exceed the
    # aligned dates — both counts are served under distinct names.
    holdout: dict | None = None
    if holdout_dates:
        w_map = {figis[i]: w[i] for i in range(len(figis)) if w[i] > 1e-5}
        ew_map = {f: 1.0 / len(figis) for f in figis}
        holdout = {
            "start_date": holdout_dates[0].isoformat(),
            "end_date": holdout_dates[-1].isoformat(),
            "n_aligned_days": len(holdout_dates),
            "selection_caveat": "universe selected by latest mcap/current membership "
                                "(not point-in-time at train_end)",
            "strategy": score_weights(eq_conn, w_map, cov_end, holdout_dates[-1]),
            "equal_weight": score_weights(eq_conn, ew_map, cov_end, holdout_dates[-1]),
        }

    # The spec reproduces the SOLVE DEFINITION; the resolved name set is data-dependent
    # (latest-mcap selection + alignment) and lives on optimiser.weight rows.
    spec = {
        "universe": universe_id, "method": method, "n": n, "lookback": lookback,
        "max_weight": max_weight, "cov_method": cov_method,
        "signal_tilt": ({"factor": tilt_factor, "strength": tilt_strength}
                        if tilt_factor else None),
        "holdout_days": holdout_days,
        "save_portfolio": portfolios_gw is not None,
        "train_start": dates[0].isoformat(), "train_end": cov_end.isoformat(),
    }
    tickers = _tickers(conn, figis)
    summary = {"n_dates": t, "max_weight": max(w), "n_nonzero": sum(1 for x in w if x > 1e-4),
               "weights_sum": sum(w), "holdout": holdout,
               "chosen_lam": chosen_lam, "tilt_coverage": tilt_coverage,
               "cov_method": cov_method, "shrink_delta": shrink_delta}
    sol_id = opt_conn.execute(
        """
        INSERT INTO optimiser.solution
            (universe_id, method, n_assets, lookback_days, exp_return, exp_vol, sharpe, ew_vol,
             summary, spec)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb) RETURNING solution_id
        """,
        (universe_id, method, len(figis), lookback, exp_ret, exp_vol, sharpe, ew_vol,
         json.dumps(summary), json.dumps(spec)),
    ).fetchone()[0]
    order = sorted(range(len(figis)), key=lambda i: (-w[i], figis[i]))
    kept = [(figis[i], w[i]) for i in order if w[i] > 1e-5]
    with opt_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO optimiser.weight (solution_id, composite_figi, ticker, weight) "
            "VALUES (%s,%s,%s,%s)",
            [(sol_id, f, tickers.get(f), wt) for f, wt in kept],
        )

    # Q7.4a: persist the allocation as a Portfolio via the OWNING package's writer.
    # Non-atomic with the solution INSERT (different databases) by design — a failing
    # save is ATTRIBUTED on the result, never a 500 that hides the committed solution.
    portfolio_id = None
    portfolio_error = None
    portfolio_upload = None
    if portfolios_gw is not None:
        kept_sum = sum(wt for _f, wt in kept)
        # renormalise the UPLOADED vector: the 1e-5 dust filter leaves the sum
        # fractionally under 1 and a portfolio's weights should state the full holding
        upload = ([(f, wt / kept_sum) for f, wt in kept] if kept_sum > 0 else [])
        try:
            portfolio_id = portfolios_gw.create(
                f"Optimiser #{sol_id}: {method} · {universe_id}", "(optimiser)", "USD"
            )
            portfolio_upload = portfolios_gw.upload_weights(portfolio_id, cov_end, upload)
        except Exception as exc:  # noqa: BLE001 — attributed, the solution stands
            portfolio_error = f"{type(exc).__name__}: {str(exc)[:160]}"

    return {"solution_id": int(sol_id), "universe_id": universe_id, "method": method,
            "n_assets": len(figis), "exp_return": exp_ret, "exp_vol": exp_vol,
            "sharpe": sharpe, "ew_vol": ew_vol, "summary": summary, "spec": spec,
            "holdout": holdout, "portfolio_id": portfolio_id,
            "portfolio_upload": portfolio_upload, "portfolio_error": portfolio_error}


def _tickers(conn, figis) -> dict:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (composite_figi) composite_figi, symbol_value
          FROM security_symbology
         WHERE composite_figi = ANY(%s) AND symbol_type='ticker'
         ORDER BY composite_figi, (valid_to IS NULL) DESC, valid_from DESC
        """,
        (figis,),
    ).fetchall()
    return {f: t for f, t in rows}


if __name__ == "__main__":
    from optimiser.db import connect

    sym_conn = connect("sym")
    opt_conn = connect()
    u_conn = connect("universe")
    eq_conn = connect("equity")
    try:
        for m in METHODS:
            print(json.dumps(solve(sym_conn, opt_conn, "sp500", m, 40, 252,
                                   u_conn=u_conn, eq_conn=eq_conn),
                             indent=2, default=str))
    finally:
        for c in (sym_conn, opt_conn, u_conn, eq_conn):
            c.close()
