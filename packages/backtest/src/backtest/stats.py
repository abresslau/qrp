"""Overfitting & significance statistics for factor backtests (pure-Python, no numpy/scipy).

The credibility layer over a backtest sweep (Story 1B, deep-research 2026-06-23). When many
strategy configurations are tried, the best-observed Sharpe is inflated by selection alone, so a
high in-sample Sharpe is not evidence of skill. These functions quantify that:

- ``probabilistic_sharpe`` (PSR) — P(true Sharpe > a benchmark), correcting for non-normal returns
  (Bailey & López de Prado).
- ``expected_max_sharpe`` — the "False Strategy Theorem" benchmark E[max SR] across N independent
  trials (≈ σ_SR·√(2 ln N)); the level a winner must clear just to beat luck.
- ``deflated_sharpe`` (DSR) — PSR evaluated AT E[max SR] instead of zero: the headline number.
- ``pbo`` — Probability of Backtest Overfitting via Combinatorially-Symmetric Cross-Validation
  (CSCV): the rate at which the in-sample-best config lands below the out-of-sample median.
- ``min_backtest_length_years`` — MinBTL ≈ 2 ln N / E[max SR]²; how much history N trials demand.

Sharpe here is the per-observation ratio mean/pstdev (rf=0), matching ``engine._stats``; annualise
by ×√252 where a yearly figure is wanted. All inputs are plain Python lists.
"""

from __future__ import annotations

import math
from itertools import combinations

EULER_MASCHERONI = 0.5772156649015329


# --- normal distribution helpers (no scipy) ------------------------------------------------


def norm_cdf(x: float) -> float:
    """Standard-normal CDF Φ via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Standard-normal inverse CDF (quantile) — Acklam's rational approximation, |err| < 1.15e-9."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# --- sample moments -------------------------------------------------------------------------


def _moments(returns: list[float]) -> tuple[int, float, float, float, float]:
    """(n, mean, pstdev, skew, kurtosis) — kurtosis is NON-excess (normal = 3). Pop. stdev to
    match engine._stats. Degenerate (n<2 or zero variance) yields sd=0 and zero higher moments."""
    n = len(returns)
    if n < 2:
        return n, (returns[0] if returns else 0.0), 0.0, 0.0, 3.0
    m = sum(returns) / n
    var = sum((x - m) ** 2 for x in returns) / n
    sd = math.sqrt(var)
    if sd <= 0:
        return n, m, 0.0, 0.0, 3.0
    skew = sum(((x - m) / sd) ** 3 for x in returns) / n
    kurt = sum(((x - m) / sd) ** 4 for x in returns) / n
    return n, m, sd, skew, kurt


def sharpe(returns: list[float]) -> float:
    """Per-observation Sharpe (mean / population stdev, rf=0); 0.0 if no dispersion."""
    _n, m, sd, _sk, _ku = _moments(returns)
    return (m / sd) if sd > 0 else 0.0


# --- the significance statistics ------------------------------------------------------------


def probabilistic_sharpe(
    sr: float, n_obs: int, skew: float, kurt: float, sr_benchmark: float = 0.0
) -> float | None:
    """PSR = P(true Sharpe > ``sr_benchmark``) given the observed per-obs Sharpe and its return
    distribution's skew/kurtosis (Bailey & López de Prado 2012). ``sr``/``sr_benchmark`` are
    per-observation. None when undefined (n<2 or a non-positive variance term)."""
    if n_obs < 2:
        return None
    denom_sq = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom_sq <= 0.0:
        return None
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq)
    return norm_cdf(z)


def expected_max_sharpe(n_trials: int, sigma_sr: float) -> float:
    """E[max SR] across ``n_trials`` independent trials under the null of zero skill (the False
    Strategy Theorem). ``sigma_sr`` = cross-trial stdev of the per-obs Sharpes; grows ≈ √(2·lnN)."""
    if n_trials < 2 or sigma_sr <= 0.0:
        return 0.0
    g = EULER_MASCHERONI
    return sigma_sr * (
        (1.0 - g) * norm_ppf(1.0 - 1.0 / n_trials)
        + g * norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe(
    returns: list[float], n_trials: int, sigma_sr: float
) -> dict:
    """Deflated Sharpe Ratio: PSR of ``returns`` evaluated AT the E[max SR] benchmark for
    ``n_trials`` (selection-bias corrected). Returns the DSR probability plus the pieces that
    produced it, so the caller can show its work. DSR > 0.95 ≈ skill that survives the multiple
    testing implied by trying ``n_trials`` configurations."""
    n, _m, sd, skew, kurt = _moments(returns)
    sr = sharpe(returns)
    sr_star = expected_max_sharpe(n_trials, sigma_sr)
    dsr = probabilistic_sharpe(sr, n, skew, kurt, sr_star)
    return {
        "dsr": dsr,
        "sharpe": sr,
        "sharpe_ann": sr * math.sqrt(252),
        "sr_benchmark": sr_star,
        "n_obs": n,
        "n_trials": n_trials,
        "skew": skew,
        "kurtosis": kurt,
    }


def min_backtest_length_years(n_trials: int, expected_max_sharpe_ann: float) -> float | None:
    """MinBTL ≈ 2 ln(N) / E[max SR_annual]² — the history (years) needed before an annual IS Sharpe
    is evidence of skill rather than the best of N lucky draws. None when undefined."""
    if n_trials < 2 or expected_max_sharpe_ann <= 0.0:
        return None
    return 2.0 * math.log(n_trials) / (expected_max_sharpe_ann ** 2)


def pbo(series: list[list[float]], n_splits: int = 16) -> dict | None:
    """Probability of Backtest Overfitting via CSCV (Bailey, Borwein, López de Prado & Zhu 2017).

    ``series`` = one daily-return list per configuration (all trimmed to a common length T). Split
    the T observations into an even number S of contiguous equal blocks; for every way to choose
    S/2 blocks as the in-sample set, take the IS-best config and find its OUT-of-sample relative
    rank ω; the logit λ=ln(ω/(1−ω)). PBO = fraction of splits with λ ≤ 0 (IS-best below the OOS
    median). Reject a sweep with PBO > 0.05. Block sums are precomputed so each of the C(S,S/2)
    splits is O(configs·S), not O(configs·T)."""
    n_cfg = len(series)
    if n_cfg < 2:
        return None
    T = min(len(s) for s in series)
    series = [s[:T] for s in series]
    S = n_splits if n_splits % 2 == 0 else n_splits - 1
    while S > 2 and T // S < 2:  # need >= 2 obs per block for a defined Sharpe
        S -= 2
    if S < 2 or T < S:
        return None
    block = T // S
    bounds = [(i * block, (i + 1) * block if i < S - 1 else T) for i in range(S)]
    # per-config, per-block accumulators so a block-union Sharpe is O(blocks)
    s1 = [[0.0] * S for _ in range(n_cfg)]   # Σx
    s2 = [[0.0] * S for _ in range(n_cfg)]   # Σx²
    cnt = [0] * S
    for b, (lo, hi) in enumerate(bounds):
        cnt[b] = hi - lo
        for i, s in enumerate(series):
            seg = s[lo:hi]
            s1[i][b] = sum(seg)
            s2[i][b] = sum(x * x for x in seg)

    def block_sharpe(i: int, blocks: tuple[int, ...]) -> float:
        n = sum(cnt[b] for b in blocks)
        if n < 2:
            return 0.0
        a = sum(s1[i][b] for b in blocks)
        q = sum(s2[i][b] for b in blocks)
        m = a / n
        var = q / n - m * m
        return (m / math.sqrt(var)) if var > 1e-300 else 0.0

    all_blocks = range(S)
    logits: list[float] = []
    n_below = 0
    for train in combinations(all_blocks, S // 2):
        test = tuple(b for b in all_blocks if b not in train)
        is_best = max(range(n_cfg), key=lambda i: block_sharpe(i, train))
        oos = [block_sharpe(i, test) for i in range(n_cfg)]
        # average (tie-aware) rank of the IS-best config among OOS performances (1 = worst): a
        # plain sorted().index() forces tied/indistinguishable configs to the stable-sort order
        # (the IS-best lands worst, spuriously inflating PBO). Mid-rank puts ties at the median.
        # Identical for all-distinct OOS values (n_equal == 1 → n_worse + 1), so distinct sweeps
        # are unchanged.
        best_oos = oos[is_best]
        n_worse = sum(1 for v in oos if v < best_oos)
        n_equal = sum(1 for v in oos if v == best_oos)
        rank = n_worse + (n_equal + 1) / 2.0
        omega = rank / (n_cfg + 1)
        lam = math.log(omega / (1.0 - omega)) if 0.0 < omega < 1.0 else 0.0
        logits.append(lam)
        if lam <= 0.0:
            n_below += 1
    n_combos = len(logits)
    return {
        "pbo": n_below / n_combos if n_combos else None,
        "n_splits": S,
        "n_combos": n_combos,
        "median_logit": sorted(logits)[n_combos // 2] if n_combos else None,
    }
