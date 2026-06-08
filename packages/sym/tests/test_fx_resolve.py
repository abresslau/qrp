"""FX as-of resolver classification (Epic FX, FX3a). DB-free (pure classify)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sym.fx.resolve import OUTAGE_CAP_DAYS, classify

D = date(2024, 6, 14)  # a Friday


def test_same_day_observation_is_ok_not_filled():
    r = classify("BRL", D, D, Decimal("5.40"))
    assert r.status == "ok" and r.rate == Decimal("5.40") and not r.is_filled and r.days_stale == 0


def test_weekend_carry_is_ok_and_filled():
    # Monday as-of, last observed the prior Friday (3 days) -> normal carry, ok + filled.
    monday = date(2024, 6, 17)
    r = classify("BRL", monday, D, Decimal("5.40"))
    assert r.status == "ok" and r.rate == Decimal("5.40") and r.is_filled and r.days_stale == 3


def test_beyond_outage_cap_is_stale_and_withheld():
    far = date(2024, 6, 14 + OUTAGE_CAP_DAYS + 1)  # 8 days after the last observation
    r = classify("BRL", far, D, Decimal("5.40"))
    assert r.status == "stale" and r.rate is None and r.days_stale == OUTAGE_CAP_DAYS + 1


def test_exactly_at_cap_is_still_ok():
    at_cap = date(2024, 6, 14 + OUTAGE_CAP_DAYS)  # exactly 7 days
    r = classify("BRL", at_cap, D, Decimal("5.40"))
    assert r.status == "ok" and r.rate == Decimal("5.40")


def test_no_observation_is_no_data_distinct_from_stale():
    r = classify("XYZ", D, None, None)
    assert r.status == "no_data" and r.rate is None and r.observed_date is None
