"""Commodity data-quality checks (PASS/WARN/FAIL), mirroring the rates validate surface."""

from __future__ import annotations

from .checks import run_checks

__all__ = ["run_checks"]
