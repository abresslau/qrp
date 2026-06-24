"""Tests for the overfitting/significance stats (Story 1B) — pure functions, no DB."""

from __future__ import annotations

import math

import pytest

from backtest.stats import (
    deflated_sharpe,
    expected_max_sharpe,
    min_backtest_length_years,
    norm_cdf,
    norm_ppf,
    pbo,
    probabilistic_sharpe,
    sharpe,
)

# ---- normal helpers ------------------------------------------------------------------------


def test_norm_cdf_known_points():
    assert norm_cdf(0.0) == pytest.approx(0.5)
    assert norm_cdf(1.96) == pytest.approx(0.975, abs=1e-3)
    assert norm_cdf(-1.96) == pytest.approx(0.025, abs=1e-3)


def test_norm_ppf_is_cdf_inverse():
    for p in (0.01, 0.1, 0.5, 0.84, 0.975, 0.999):
        assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-6)
    assert norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-4)


# ---- Sharpe + PSR --------------------------------------------------------------------------


def test_sharpe_zero_when_no_dispersion():
    assert sharpe([0.001, 0.001, 0.001]) == 0.0


def test_psr_rises_with_more_observations():
    # same Sharpe, normal moments: more history -> more confident the true SR > 0
    short = probabilistic_sharpe(0.1, n_obs=30, skew=0.0, kurt=3.0)
    long = probabilistic_sharpe(0.1, n_obs=2000, skew=0.0, kurt=3.0)
    assert 0.5 < short < long < 1.0


def test_psr_punished_by_negative_skew_and_fat_tails():
    base = probabilistic_sharpe(0.1, 500, skew=0.0, kurt=3.0)
    skewed = probabilistic_sharpe(0.1, 500, skew=-1.0, kurt=3.0)  # left tail -> less significant
    fat = probabilistic_sharpe(0.1, 500, skew=0.0, kurt=8.0)      # fat tails -> less significant
    assert skewed < base and fat < base


def test_psr_undefined_for_degenerate_variance_term():
    # 1 - skew·sr + (kurt-1)/4·sr² <= 0 -> None, never a fabricated probability
    assert probabilistic_sharpe(2.0, 500, skew=5.0, kurt=1.0) is None


# ---- expected max Sharpe (False Strategy Theorem) ------------------------------------------


def test_expected_max_sharpe_grows_with_trials_like_sqrt_2lnN():
    sig = 0.02
    e10 = expected_max_sharpe(10, sig)
    e1000 = expected_max_sharpe(1000, sig)
    assert 0 < e10 < e1000
    # order-of-magnitude check against the √(2 ln N) asymptotic (loose — EVT constant)
    assert e1000 == pytest.approx(sig * math.sqrt(2 * math.log(1000)), rel=0.25)


def test_expected_max_sharpe_zero_without_dispersion_or_trials():
    assert expected_max_sharpe(1, 0.02) == 0.0
    assert expected_max_sharpe(50, 0.0) == 0.0


# ---- Deflated Sharpe -----------------------------------------------------------------------


def _series(mu, sd, n, seed=1):
    state = seed & 0x7FFFFFFF

    def rnd():  # Box-Muller off an LCG — deterministic normal-ish draws
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        u1 = (state + 1) / (0x7FFFFFFF + 2)
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        u2 = (state + 1) / (0x7FFFFFFF + 2)
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

    return [mu + sd * rnd() for _ in range(n)]


def test_deflated_sharpe_high_when_one_trial_strong_signal():
    # a genuinely strong series, claimed as the ONLY trial -> DSR near 1
    r = _series(0.0015, 0.01, 800, seed=3)  # daily Sharpe ~0.15
    out = deflated_sharpe(r, n_trials=1, sigma_sr=0.0)
    assert out["sr_benchmark"] == 0.0  # 1 trial -> benchmark is zero
    assert out["dsr"] is not None and out["dsr"] > 0.95


def test_deflated_sharpe_collapses_when_many_trials_were_tried():
    # the SAME series, but disclosed as the best of 500 noisy trials -> benchmark rises, DSR falls
    r = _series(0.0015, 0.01, 800, seed=3)
    solo = deflated_sharpe(r, n_trials=1, sigma_sr=0.0)["dsr"]
    swept = deflated_sharpe(r, n_trials=500, sigma_sr=0.05)
    assert swept["sr_benchmark"] > 0.0
    assert swept["dsr"] < solo  # selection bias deflates the headline


# ---- Minimum Backtest Length ---------------------------------------------------------------


def test_min_backtest_length_grows_with_trials():
    short = min_backtest_length_years(10, 1.0)
    longer = min_backtest_length_years(1000, 1.0)
    assert longer > short
    # LdP worked example: ~45 independent configs over 5 years at E[max]=1 is the danger line
    assert min_backtest_length_years(45, 1.0) == pytest.approx(2 * math.log(45), rel=1e-9)


def test_min_backtest_length_undefined_cases():
    assert min_backtest_length_years(1, 1.0) is None
    assert min_backtest_length_years(50, 0.0) is None


# ---- PBO via CSCV --------------------------------------------------------------------------


def test_pbo_low_when_one_config_has_persistent_real_edge():
    # config 0 has a true positive drift every period; the rest are pure noise. The IS-best should
    # keep winning OOS -> PBO near 0.
    edge = [0.002 + 0.001 * ((i % 7) - 3) for i in range(240)]  # always-positive-mean, varied
    noise = [_series(0.0, 0.01, 240, seed=s) for s in range(2, 12)]
    out = pbo([edge, *noise], n_splits=10)
    assert out is not None
    assert 0.0 <= out["pbo"] <= 1.0
    assert out["pbo"] < 0.5  # a real edge is not an overfit


def test_pbo_high_when_all_configs_are_interchangeable_noise():
    # 12 indistinguishable noise configs: whoever wins IS is a coin-flip OOS -> PBO near 0.5+
    series = [_series(0.0, 0.01, 240, seed=s) for s in range(20, 32)]
    out = pbo(series, n_splits=10)
    assert out is not None
    assert out["pbo"] > 0.3  # no persistent skill -> IS-best routinely sinks OOS


def test_pbo_combo_count_matches_choose_S_half():
    series = [_series(0.0, 0.01, 120, seed=s) for s in range(5)]
    out = pbo(series, n_splits=8)
    assert out["n_splits"] == 8
    assert out["n_combos"] == math.comb(8, 4)  # C(8,4) = 70


def test_pbo_none_for_too_few_configs():
    assert pbo([[0.01] * 100], n_splits=8) is None
