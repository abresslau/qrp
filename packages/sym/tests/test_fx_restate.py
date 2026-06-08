"""FX restatement math (Epic FX consumer). DB-free (pure restate_return)."""

from __future__ import annotations

from decimal import Decimal

from sym.fx.restate import restate_return


def test_cumulative_restatement_compounds_local_with_fx():
    # +10% local, FX up 5% over the window -> (1.10)(1.05) - 1 = 0.155
    assert restate_return(Decimal("0.10"), Decimal("1.05")) == Decimal("0.155")


def test_flat_fx_leaves_local_unchanged():
    assert restate_return(Decimal("0.2345"), Decimal("1")) == Decimal("0.2345")


def test_negative_local_and_fx_devaluation():
    # -10% local, local currency devalued so FX_target/local rises 25% -> (0.9)(1.25)-1 = 0.125
    assert restate_return(Decimal("-0.10"), Decimal("1.25")) == Decimal("0.125")


def test_annualized_restatement_reannualizes():
    # 10%/yr local over 2y (cum 21%), FX +21% cumulative over the window.
    # cum_restated = 1.21*1.21-1 = 0.4641 -> reannualized = sqrt(1.4641)-1 = 0.21
    r = restate_return(Decimal("0.10"), Decimal("1.21"), annualized=True, years=2)
    assert round(r, 6) == Decimal("0.210000")


def test_annualized_flat_fx_is_identity():
    r = restate_return(Decimal("0.08"), Decimal("1"), annualized=True, years=5)
    assert round(r, 8) == Decimal("0.08000000")


def test_none_and_bad_inputs():
    assert restate_return(None, Decimal("1.1")) is None
    assert restate_return(Decimal("0.1"), None) is None
    assert restate_return(Decimal("0.1"), Decimal("0")) is None  # non-positive ratio
    assert restate_return(Decimal("0.1"), Decimal("1.1"), annualized=True, years=0) is None
