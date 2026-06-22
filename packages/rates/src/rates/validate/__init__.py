"""Validation layer for the rates package — the trust guards on the curve store."""

from .checks import (
    FAIL,
    PASS,
    WARN,
    CheckResult,
    check_forward_spot_reconcile,
    check_inflation_reconcile,
    check_plausible_band,
    check_staleness,
    run_all,
)

__all__ = [
    "CheckResult",
    "PASS",
    "WARN",
    "FAIL",
    "check_staleness",
    "check_plausible_band",
    "check_inflation_reconcile",
    "check_forward_spot_reconcile",
    "run_all",
]
