"""Pure-Python mean-variance optimiser (no numpy).

Builds the daily-return covariance for a capped set of names from sym (read-only), then
solves long-only weights on the probability simplex (sum=1, w>=0) by projected gradient:
- min_variance: minimise wᵀΣw
- max_sharpe: trace a small risk-aversion path (minimise λ·wᵀΣw − wᵀμ) and keep the
  allocation with the best realised Sharpe.
Annualised with 252. rf = 0. Reads sym READ-ONLY; persists to the `optimiser` schema.
"""

from __future__ import annotations

import json
import math

import psycopg

_W_1D = 1
ANN = 252


def _select_names(conn, universe_id: str, n: int) -> list[str]:
    """The n largest current members by latest market cap (keeps the covariance tractable)."""
    rows = conn.execute(
        """
        SELECT um.composite_figi
          FROM universe_membership um
          JOIN LATERAL (
              SELECT market_cap_usd FROM fundamentals f
               WHERE f.composite_figi = um.composite_figi AND f.market_cap_usd IS NOT NULL
               ORDER BY f.as_of_date DESC LIMIT 1
          ) fc ON TRUE
         WHERE um.universe_id = %s AND um.valid_to IS NULL
         ORDER BY fc.market_cap_usd DESC
         LIMIT %s
        """,
        (universe_id, n),
    ).fetchall()
    return [r[0] for r in rows]


def _return_matrix(conn, figis, lookback) -> tuple[list[str], list[list[float]]]:
    """Aligned daily returns: keep names present on a common set of recent dates.

    Returns (kept_figis, matrix) where matrix[i] is the daily series for kept_figis[i].
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
        present = sorted(figis, key=lambda f: sum(1 for d in by_date if f in by_date[d]), reverse=True)
        # trim names with poor coverage until we have >=30 common dates or <5 names
        kept = list(present)
        while len(kept) > 5:
            ds = [d for d in sorted(by_date) if set(kept).issubset(by_date[d].keys())]
            if len(ds) >= 30:
                dates = ds
                break
            kept.pop()  # drop the worst-covered name
        figis = kept
    series = {f: [by_date[d][f] for d in dates] for f in figis}
    return list(figis), [series[f] for f in figis]


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


def _matvec(m, v):
    return [sum(m[i][j] * v[j] for j in range(len(v))) for i in range(len(m))]


def _project_simplex(v: list[float]) -> list[float]:
    """Euclidean projection onto {w : sum(w)=1, w>=0} (Wang & Carreira-Perpiñán)."""
    u = sorted(v, reverse=True)
    css = 0.0
    theta = 0.0
    for i, ui in enumerate(u):
        css += ui
        t = (css - 1.0) / (i + 1)
        if ui - t > 0:
            theta = t
    return [max(x - theta, 0.0) for x in v]


def _pgd(cov, mean, lam: float, iters: int = 800) -> list[float]:
    """Minimise lam*wᵀΣw − wᵀμ over the simplex (lam large -> min variance)."""
    n = len(cov)
    w = [1.0 / n] * n
    # Step from a Gershgorin bound on the largest eigenvalue of 2*lam*Σ.
    l_max = max(sum(abs(cov[i][j]) for j in range(n)) for i in range(n)) * 2 * lam + 1e-9
    step = 1.0 / l_max
    for _ in range(iters):
        sig_w = _matvec(cov, w)
        grad = [2 * lam * sig_w[i] - mean[i] for i in range(n)]
        w = _project_simplex([w[i] - step * grad[i] for i in range(n)])
    return w


def _stats(w, mean, cov):
    var = sum(w[i] * _matvec(cov, w)[i] for i in range(len(w)))
    exp_ret = sum(w[i] * mean[i] for i in range(len(w))) * ANN
    exp_vol = math.sqrt(max(var, 0.0) * ANN)
    sharpe = exp_ret / exp_vol if exp_vol > 0 else None
    return exp_ret, exp_vol, sharpe


def solve(sym_conn: psycopg.Connection, opt_conn: psycopg.Connection,
          universe_id="sp500", method="min_variance", n=40, lookback=252) -> dict:
    # sym_conn reads the sym package (universe/fundamentals/fact_returns/symbology); opt_conn writes
    # solutions/weights to the optimiser database (DB-per-package; cross-DB read via psycopg).
    conn = sym_conn  # all reads below go to the sym package
    opt_conn.autocommit = True
    names = _select_names(conn, universe_id, n)
    if len(names) < 5:
        return {"error": f"too few members with market cap for {universe_id!r}"}
    figis, matrix = _return_matrix(conn, names, lookback)
    if len(figis) < 5 or len(matrix[0]) < 30:
        return {"error": "insufficient aligned daily history for a covariance"}
    mean, cov = _mean_cov(matrix)
    t = len(matrix[0])

    if method == "min_variance":
        w = _pgd(cov, mean, lam=1e6)  # huge lam -> pure variance min
    else:  # max_sharpe: trace lambda path, keep best realised Sharpe
        best_w, best_s = None, -1e18
        for lam in (0.5, 1, 2, 5, 10, 25, 50, 100, 250):
            cand = _pgd(cov, mean, lam=lam)
            _, _, s = _stats(cand, mean, cov)
            if s is not None and s > best_s:
                best_s, best_w = s, cand
        w = best_w or [1.0 / len(figis)] * len(figis)

    exp_ret, exp_vol, sharpe = _stats(w, mean, cov)
    ew = [1.0 / len(figis)] * len(figis)
    _, ew_vol, _ = _stats(ew, mean, cov)

    tickers = _tickers(conn, figis)
    summary = {"n_dates": t, "max_weight": max(w), "n_nonzero": sum(1 for x in w if x > 1e-4),
               "weights_sum": sum(w)}
    sol_id = opt_conn.execute(
        """
        INSERT INTO optimiser.solution
            (universe_id, method, n_assets, lookback_days, exp_return, exp_vol, sharpe, ew_vol,
             summary)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING solution_id
        """,
        (universe_id, method, len(figis), lookback, exp_ret, exp_vol, sharpe, ew_vol,
         json.dumps(summary)),
    ).fetchone()[0]
    order = sorted(range(len(figis)), key=lambda i: w[i], reverse=True)
    with opt_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO optimiser.weight (solution_id, composite_figi, ticker, weight) "
            "VALUES (%s,%s,%s,%s)",
            [(sol_id, figis[i], tickers.get(figis[i]), w[i]) for i in order if w[i] > 1e-5],
        )
    return {"solution_id": int(sol_id), "universe_id": universe_id, "method": method,
            "n_assets": len(figis), "exp_return": exp_ret, "exp_vol": exp_vol, "sharpe": sharpe,
            "ew_vol": ew_vol, "summary": summary}


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
    try:
        for m in ("min_variance", "max_sharpe"):
            print(json.dumps(solve(sym_conn, opt_conn, "sp500", m, 40, 252), indent=2, default=str))
    finally:
        sym_conn.close()
        opt_conn.close()
