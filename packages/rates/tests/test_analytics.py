"""Pure derive-module math — hand-computed fixtures. No DB/IO."""

from __future__ import annotations

import math

import pytest

from rates import analytics as a


def test_interp_linear_and_out_of_range():
    curve = {1.0: 2.0, 2.0: 4.0}
    assert a.interp(curve, 1.0) == 2.0  # exact node
    assert a.interp(curve, 1.5) == pytest.approx(3.0)  # midpoint
    assert a.interp(curve, 0.5) is None  # below grid → no extrapolation
    assert a.interp(curve, 2.5) is None  # above grid
    assert a.interp({}, 1.0) is None


def test_discount_factor_continuous_compounding():
    assert a.discount_factor(0.0, 5.0) == 1.0
    assert a.discount_factor(5.0, 2.0) == pytest.approx(math.exp(-0.10))  # exp(-0.05*2)


def test_curve_spread_2s10s_in_bp():
    assert a.curve_spread({2.0: 4.0, 10.0: 4.5}, 2.0, 10.0) == pytest.approx(50.0)
    assert a.curve_spread({2.0: 4.0}, 2.0, 10.0) is None  # 10y not published


def test_butterfly_2s5s10s_in_bp():
    # 2*4.3 - 4.0 - 4.5 = 0.1% → 10bp
    assert a.butterfly({2.0: 4.0, 5.0: 4.3, 10.0: 4.5}, 2.0, 5.0, 10.0) == pytest.approx(10.0)


def test_breakeven_is_a_percent_level():
    assert a.breakeven({10.0: 4.5}, {10.0: 1.0}, 10.0) == pytest.approx(3.5)  # %, not bp
    assert a.breakeven({10.0: 4.5}, {}, 10.0) is None  # no real curve at 10y


def test_asset_swap_proxy_in_bp():
    assert a.asset_swap_proxy({10.0: 4.5}, {10.0: 4.2}, 10.0) == pytest.approx(30.0)


def test_roll_down_in_bp():
    # rolls from 10y (4.4) to 7y (4.0) over a 3y horizon → yield falls 40bp
    assert a.roll_down({7.0: 4.0, 10.0: 4.4}, 10.0, 3.0) == pytest.approx(40.0)
    assert a.roll_down({7.0: 4.0, 10.0: 4.4}, 10.0, 0.0) is None  # degenerate horizon
    assert a.roll_down({10.0: 4.4}, 10.0, 3.0) is None  # 7y not published


def test_present_value_and_dv01():
    # single 100 cashflow at 10y on a flat 5% curve
    flat = {t: 5.0 for t in (1.0, 5.0, 10.0)}
    pv = a.present_value([(10.0, 100.0)], flat)
    assert pv == pytest.approx(100.0 * math.exp(-0.5))  # 60.653
    # DV01 ≈ amount·DF·t·1bp = 60.653 * 10 * 1e-4 ≈ 0.0607, positive
    d = a.dv01([(10.0, 100.0)], flat)
    assert d == pytest.approx(0.0607, abs=1e-3) and d > 0


def test_pv_none_when_cashflow_outside_grid():
    assert a.present_value([(30.0, 100.0)], {1.0: 5.0, 10.0: 5.0}) is None
    assert a.dv01([(30.0, 100.0)], {1.0: 5.0, 10.0: 5.0}) is None


def test_carry_roll_returns_both_legs():
    out = a.carry_roll({7.0: 4.0, 10.0: 4.4}, {0.25: 4.6}, 10.0, 3.0)
    assert out["roll_bp"] == pytest.approx(40.0)
    assert out["carry_bp"] is None  # fwd at 3.0 not published in this tiny fixture
