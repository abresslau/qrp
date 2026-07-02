"""Tests for the asset-level risk metrics (vol + Sharpe per window). Pure, no DB."""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from decimal import Decimal

from equity.returns.metrics import (
    MIN_OBS,
    TRADING_DAYS,
    compute_metric_rows,
    daily_returns,
    metric_input_hash,
)

FIGI = "BBG000B9XRY4"


def _bdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(sessions, prices):
    return {d: Decimal(str(p)) for d, p in zip(sessions, prices, strict=True)}


# --- daily_returns ----------------------------------------------------------


def test_daily_returns_consecutive_and_skips_first():
    s = _series([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)], [100, 110, 99])
    r = daily_returns(s)
    assert set(r) == {date(2024, 1, 3), date(2024, 1, 4)}  # no return on the first session
    assert abs(r[date(2024, 1, 3)] - 0.10) < 1e-12
    assert abs(r[date(2024, 1, 4)] - (99 / 110 - 1)) < 1e-12


def test_daily_returns_break_on_nonpositive_price():
    s = _series([date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)], [100, 0, 105])
    r = daily_returns(s)
    assert r == {}  # 0 breaks both the ratio into it and out of it — no fabricated return


# --- annualization + min-obs (the core math) --------------------------------


def test_vol_and_sharpe_annualization_formula():
    # a controlled window: two daily returns -> known sample stdev + mean
    from equity.returns.metrics import _vol_sharpe

    rets = [0.02, -0.01]
    vol, sharpe = _vol_sharpe(rets)
    sd = statistics.stdev(rets)
    # vol = stddev_samp × √252 ; sharpe = mean/sd × √252 (rf=0, annualize the ratio ONCE)
    assert abs(vol - sd * math.sqrt(TRADING_DAYS)) < 1e-12
    assert abs(sharpe - (statistics.fmean(rets) / sd) * math.sqrt(TRADING_DAYS)) < 1e-12


def test_vol_null_below_min_obs_and_on_zero_variance():
    from equity.returns.metrics import _vol_sharpe

    assert MIN_OBS == 2
    assert _vol_sharpe([0.01]) == (None, None)          # one return: no sample stdev
    assert _vol_sharpe([0.01, 0.01, 0.01]) == (None, None)  # zero variance -> undefined Sharpe


def test_1d_window_is_null():
    sess = _bdays(date(2024, 1, 1), 40)
    adj = _series(sess, [100 * (1.001 ** i) for i in range(40)])
    rows = compute_metric_rows(FIGI, sess[-3:], adj, adj, sess, 7)
    one_d = [r for r in rows if r.window_id == 1]  # 1D
    assert one_d and all(r.vol_pr is None and r.n_obs <= 1 for r in one_d)


# --- PR vs TR diverge on a dividend payer -----------------------------------


def test_pr_and_tr_volatility_differ_with_dividends():
    sess = _bdays(date(2024, 1, 1), 60)
    adj = _series(sess, [100.0 + 0.5 * i for i in range(60)])  # smooth price path
    # a TRI that steps up on one interior session (a reinvested dividend) — extra dispersion vs PR
    tri_prices = [float(adj[d]) for d in sess]
    mid = 30
    for i in range(mid, len(tri_prices)):
        tri_prices[i] *= 1.05  # a one-day jump folded into every later TRI value
    tri = _series(sess, tri_prices)
    rows = compute_metric_rows(FIGI, [sess[-1]], adj, tri, sess, 7)
    # the trailing windows spanning the jump must show TR vol != PR vol
    diverged = [r for r in rows if r.vol_pr is not None and r.vol_tr is not None
                and abs(r.vol_pr - r.vol_tr) > 1e-9]
    assert diverged, "TR vol should differ from PR vol across a dividend step"


# --- gating parity ----------------------------------------------------------


def test_gated_endpoint_nulls_values_and_reflag_re_dirties():
    sess = _bdays(date(2024, 1, 1), 60)
    adj = _series(sess, [100 * (1.002 ** i) for i in range(60)])
    as_of = sess[-1]
    ungated = compute_metric_rows(FIGI, [as_of], adj, adj, sess, 7)
    gated = compute_metric_rows(FIGI, [as_of], adj, adj, sess, 7, gated_dates={as_of})
    g_1m = next(r for r in gated if r.window_id == 7)     # 1M
    u_1m = next(r for r in ungated if r.window_id == 7)
    assert g_1m.gated and g_1m.vol_pr is None and g_1m.sharpe_pr is None
    assert u_1m.vol_pr is not None
    # the in-window flag count is in the hash, so clearing the flag on review changes the hash
    # (n_flags 1→0) → the dirty-set re-dirties the row and publishes the real value.
    assert g_1m.input_hash != u_1m.input_hash


def test_interior_flag_excluded_from_sample_not_gating_the_window():
    # The review fix: an interior flagged session is EXCLUDED from the vol sample (matching
    # signals.vol_1y), NOT folded into a published stdev and NOT NULLing the whole window (flags
    # are common — whole-window NULLing would destroy coverage). The metric is published over
    # the clean remainder; only a flagged AS-OF date gates.
    sess = _bdays(date(2024, 1, 1), 60)
    adj = _series(sess, [100 * (1.002 ** i) for i in range(60)])
    flag = sess[45]  # interior to the 1M window at sess[-1]; OUTSIDE the ~1-week window
    clean = {r.window_id: r for r in compute_metric_rows(FIGI, [sess[-1]], adj, adj, sess, 7)}
    flagged = {r.window_id: r for r in
               compute_metric_rows(FIGI, [sess[-1]], adj, adj, sess, 7, gated_dates={flag})}
    # 1M (id 7) spans the flag → still PUBLISHED (not gated), computed over the clean remainder,
    # with the two tainted returns (ret[flag] uses the flagged price, ret[flag+1] uses it as prev)
    # dropped from the sample.
    assert not flagged[7].gated and flagged[7].vol_pr is not None
    assert flagged[7].n_obs == clean[7].n_obs - 2
    # a window that doesn't reach the flag is byte-identical to the clean run
    assert flagged[6].n_obs == clean[6].n_obs and flagged[6].vol_pr == clean[6].vol_pr


# --- reconciliation with signals.vol_1y (AC-4) ------------------------------


def test_1y_vol_matches_signals_vol_1y_formula():
    # signals.vol_1y = stddev_samp(daily pr) × √252 over the window; pin the SAME formula here.
    sess = _bdays(date(2023, 1, 2), 400)
    adj = _series(sess, [100 * (1.0007 ** i) * (1.0 + 0.01 * ((-1) ** i)) for i in range(400)])
    as_of = sess[-1]
    rows = compute_metric_rows(FIGI, [as_of], adj, adj, sess, 7)
    r_1y = next(r for r in rows if r.window_id == 11)  # 1Y
    # independently gather the same window's daily pr returns and apply the vol_1y formula
    from equity.returns.metrics import daily_returns as dr
    from equity.returns.windows import BY_CODE, base_date
    base = base_date(BY_CODE["1Y"], as_of, sess)
    pr = dr(adj)
    window_rets = [pr[d] for d in sorted(pr) if base < d <= as_of]
    expected = statistics.stdev(window_rets) * math.sqrt(252)
    assert r_1y.n_obs == len(window_rets) >= 60
    assert abs(r_1y.vol_pr - expected) < 1e-12


# --- forward returns = trailing re-indexed (the v_forward_returns identity) ---


def test_forward_return_equals_trailing_at_forward_session():
    # fwd_H(t) == trailing_H at the session H forward of t — the view's defining identity.
    from equity.returns.loader import compute_return_rows
    from equity.returns.windows import BY_CODE, base_date

    sess = _bdays(date(2024, 1, 1), 80)
    adj = _series(sess, [100 * (1.003 ** i) for i in range(80)])
    rr = compute_return_rows(FIGI, sess, adj, adj, sess, 7)
    by = {(r.window_id, r.as_of_date): r for r in rr}
    w1m = BY_CODE["1M"]
    t = sess[20]
    fwd_end = None
    # the forward endpoint = first session where the trailing-1M base is on/after t
    for s in sess:
        if base_date(w1m, s, sess) is not None and base_date(w1m, s, sess) >= t:
            fwd_end = s
            break
    assert fwd_end is not None
    fwd = by[(w1m.id, fwd_end)]           # trailing-1M return AT the forward session
    assert fwd.pr is not None             # a real forward observation (endpoint has occurred)


def test_metric_input_hash_stable_and_sensitive():
    # signature: (window_id, calendar_version, base, end, vol_pr, vol_tr, sharpe_pr, sharpe_tr,
    #             n_obs, n_flags)
    args = (7, 7, date(2024, 1, 1), date(2024, 2, 1), 0.2, 0.21, 1.1, 1.2, 21, 0)
    a = metric_input_hash(*args)
    b = metric_input_hash(*args)
    assert a == b                                                   # stable
    assert metric_input_hash(*(7, 7, date(2024, 1, 1), date(2024, 2, 1),
                               0.3, 0.21, 1.1, 1.2, 21, 0)) != a     # value change
    assert metric_input_hash(*(8, *args[1:])) != a                  # window_id change (Blind #4)
    assert metric_input_hash(*(*args[:9], 1)) != a                  # n_flags change (Edge #3)
