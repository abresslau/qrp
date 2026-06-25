"""Tests for the 52-week price-extremes spec (Story 3.2-ext). Pure, no DB."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from equity.returns.extremes import (
    WINDOW_DAYS,
    compute_extreme_rows,
    extreme_input_hash,
    trailing_extremes,
)

FIGI = "BBG000B9XRY4"


def _series(pairs):
    return {d: Decimal(str(v)) for d, v in pairs}


# --- sliding-window extremum ------------------------------------------------


def test_high_and_low_over_full_window():
    s = _series([
        (date(2024, 1, 2), 100),
        (date(2024, 1, 3), 120),
        (date(2024, 1, 4), 90),
    ])
    ext = trailing_extremes(s, list(s))[date(2024, 1, 4)]
    assert ext.high == Decimal("120") and ext.high_date == date(2024, 1, 3)
    assert ext.low == Decimal("90") and ext.low_date == date(2024, 1, 4)


def test_tie_breaks_to_most_recent_session():
    # the high (110) is printed twice; the LATER date wins ("how long since the high")
    s = _series([
        (date(2024, 1, 2), 110),
        (date(2024, 1, 3), 50),
        (date(2024, 1, 4), 110),
        (date(2024, 1, 5), 60),
    ])
    ext = trailing_extremes(s, [date(2024, 1, 5)])[date(2024, 1, 5)]
    assert ext.high == Decimal("110") and ext.high_date == date(2024, 1, 4)


def test_session_outside_trailing_window_is_evicted():
    # a sky-high print > 365d before as_of must NOT count toward the trailing high
    s = _series([
        (date(2023, 1, 2), 999),          # ~2yr before -> out of window
        (date(2024, 12, 2), 100),
        (date(2024, 12, 3), 120),
    ])
    as_of = date(2024, 12, 3)
    ext = trailing_extremes(s, [as_of])[as_of]
    assert ext.high == Decimal("120")  # 999 excluded
    # boundary: a session exactly window_days before as_of is INCLUDED (inclusive lo)
    edge = as_of - timedelta(days=WINDOW_DAYS)
    s2 = _series([(edge, 999), (as_of, 120)])
    assert trailing_extremes(s2, [as_of])[as_of].high == Decimal("999")
    # one day older than the edge is excluded
    s3 = _series([(edge - timedelta(days=1), 999), (as_of, 120)])
    assert trailing_extremes(s3, [as_of])[as_of].high == Decimal("120")


def test_partial_history_uses_available_sessions():
    s = _series([(date(2024, 1, 2), 100), (date(2024, 1, 3), 80)])
    ext = trailing_extremes(s, [date(2024, 1, 3)])[date(2024, 1, 3)]
    assert ext.high == Decimal("100") and ext.low == Decimal("80")


def test_single_session_high_equals_low():
    s = _series([(date(2024, 1, 2), 100)])
    ext = trailing_extremes(s, [date(2024, 1, 2)])[date(2024, 1, 2)]
    assert ext.high == ext.low == Decimal("100")
    assert ext.high_date == ext.low_date == date(2024, 1, 2)


def test_extremes_track_as_each_day_advances():
    # one O(n) pass must give the correct rolling extreme for every as_of
    s = _series([
        (date(2024, 1, 2), 100),
        (date(2024, 1, 3), 130),
        (date(2024, 1, 4), 110),
    ])
    ext = trailing_extremes(s, list(s))
    assert ext[date(2024, 1, 2)].high == Decimal("100")
    assert ext[date(2024, 1, 3)].high == Decimal("130")
    assert ext[date(2024, 1, 4)].high == Decimal("130")  # 130 still in window
    assert ext[date(2024, 1, 4)].low == Decimal("100")


# --- pct-off + row build ----------------------------------------------------


def test_pct_off_signs_and_values():
    s = _series([
        (date(2024, 1, 2), 100),  # the high
        (date(2024, 1, 3), 50),   # the low
        (date(2024, 1, 4), 75),   # current
    ])
    row = {r.as_of_date: r for r in compute_extreme_rows(s, list(s), 53)}[date(2024, 1, 4)]
    assert row.high_52w == Decimal("100") and row.low_52w == Decimal("50")
    assert row.pct_off_high == Decimal("75") / Decimal("100") - 1  # -0.25
    assert row.pct_off_low == Decimal("75") / Decimal("50") - 1    # +0.50
    assert row.pct_off_high < 0 < row.pct_off_low
    assert not row.gated


# --- gating (AR-9, equity) --------------------------------------------------


def test_flag_on_extreme_date_gates_the_row():
    s = _series([(date(2024, 1, 2), 100), (date(2024, 1, 3), 50), (date(2024, 1, 4), 75)])
    rows = {
        r.as_of_date: r
        for r in compute_extreme_rows(s, list(s), 53, gated_dates={date(2024, 1, 2)})
    }
    row = rows[date(2024, 1, 4)]  # high_date 2024-01-02 is flagged
    assert row.gated
    assert row.high_52w is None and row.low_52w is None
    assert row.high_52w_date is None and row.pct_off_high is None
    # but the hash still reflects the real endpoints + price (re-dirties on review/price change)
    assert row.input_hash == extreme_input_hash(
        53, date(2024, 1, 4), Decimal("100"), date(2024, 1, 2), Decimal("50"), date(2024, 1, 3),
        Decimal("75"),
    )


def test_flag_off_the_extreme_does_not_gate():
    # a flag on a session that did NOT set the high or low must NOT gate (precise gate)
    s = _series([
        (date(2024, 1, 2), 100),  # high
        (date(2024, 1, 3), 70),   # an inert middle session (flagged below)
        (date(2024, 1, 4), 50),   # low
        (date(2024, 1, 5), 60),   # current
    ])
    rows = {
        r.as_of_date: r
        for r in compute_extreme_rows(s, list(s), 53, gated_dates={date(2024, 1, 3)})
    }
    row = rows[date(2024, 1, 5)]
    assert not row.gated and row.high_52w == Decimal("100") and row.low_52w == Decimal("50")


# --- input_hash -------------------------------------------------------------


def test_input_hash_deterministic_and_sensitive():
    args = (53, date(2024, 1, 4), Decimal("100"), date(2024, 1, 2), Decimal("50"), date(2024, 1, 3))
    a = extreme_input_hash(*args, Decimal("75"))
    b = extreme_input_hash(*args, Decimal("75"))
    c = extreme_input_hash(53, date(2024, 1, 4), Decimal("101"), date(2024, 1, 2),
                           Decimal("50"), date(2024, 1, 3), Decimal("75"))  # high moved -> dirty
    assert a == b and a != c


def test_input_hash_dirties_on_price_change_without_extreme_move():
    # A same-day close correction that does NOT move the trailing high/low must still
    # re-dirty the row, because pct_off depends on the current price (review-finding patch).
    base = (53, date(2024, 1, 4), Decimal("100"), date(2024, 1, 2), Decimal("50"), date(2024, 1, 3))
    assert extreme_input_hash(*base, Decimal("75")) != extreme_input_hash(*base, Decimal("78"))


def test_input_hash_format_is_pinned():
    # Golden digest pins the payload format (field order + separators); a reorder would
    # silently re-hash every fact_price_extremes row and force a full rewrite.
    h = extreme_input_hash(
        53, date(2024, 1, 4), Decimal("100"), date(2024, 1, 2), Decimal("50"), date(2024, 1, 3),
        Decimal("75"),
    )
    assert h == _expected_pinned_hash()


def _expected_pinned_hash() -> str:
    import hashlib
    payload = "53|2024-01-04|100|2024-01-02|50|2024-01-03|75"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- migration <-> code parity ----------------------------------------------


def test_extreme_tables_have_matching_deploy_revert_verify():
    # equity consolidates its DDL into one `equity_schema` change (deploy/revert/verify trio);
    # fact_price_extremes is defined there. (fact_index_extremes stays in the sym DB — index
    # facts ride the sym_id bridge and were deliberately left in sym.)
    base = Path(__file__).resolve().parents[1] / "db"
    for kind in ("deploy", "revert", "verify"):
        path = base / kind / "equity_schema.sql"
        assert path.exists(), f"missing {kind}/equity_schema.sql"
    assert "fact_price_extremes" in (base / "deploy/equity_schema.sql").read_text()


def test_extreme_tables_registered_in_sqitch_plan():
    plan = (Path(__file__).resolve().parents[1] / "db/sqitch.plan").read_text()
    assert re.search(r"^equity_schema \[?", plan, re.MULTILINE)
    assert "fact_price_extremes" in (
        Path(__file__).resolve().parents[1] / "db/deploy/equity_schema.sql"
    ).read_text()
