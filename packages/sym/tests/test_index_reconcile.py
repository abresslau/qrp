"""Index-level source reconciliation (catches candle-vs-official gaps like ^BVSP/IBOVESPA).

The grading is pure (no DB, no network): given stored latest levels + source official quotes,
``reconcile_index_levels`` returns a tri-state CheckResult. These tests pin the IBOVESPA case that
prompted the check (a ~14 bps gap warns) and the clean case (16 indices that match → pass).
"""

from __future__ import annotations

from sym.validate.index_levels import OfficialQuote, StoredLevel, reconcile_index_levels
from sym.validate.results import FAIL, PASS, WARN


def _stored(name, sym, d, lv):
    return StoredLevel(sym_id=1, name=name, symbol=sym, last_date=d, level=lv)


def test_matching_closes_pass():
    stored = [
        _stored("S&P 500", "^GSPC", "2026-06-19", 7500.580078125),
        _stored("Nikkei 225", "^N225", "2026-06-19", 71250.0625),
    ]
    # FP round-trip noise (<0.01 bps) must not trip the 5 bps warn floor
    quotes = {
        "^GSPC": OfficialQuote("2026-06-19", 7500.58),
        "^N225": OfficialQuote("2026-06-19", 71250.06),
    }
    r = reconcile_index_levels(stored, quotes)
    assert r.status == PASS and r.checked == 2 and r.failures == 0 and r.warnings == 0


def test_ibovespa_small_gap_warns():
    # the real case: stored candle close vs official settled close = 168576 vs 168333.61 (~14 bps)
    stored = [_stored("IBOVESPA", "^BVSP", "2026-06-19", 168576.0)]
    quotes = {"^BVSP": OfficialQuote("2026-06-19", 168333.61)}
    r = reconcile_index_levels(stored, quotes)  # default warn=5, fail=50 bps
    assert r.status == WARN and r.checked == 1 and r.warnings == 1 and r.failures == 0
    assert any("IBOVESPA" in s and "bps" in s for s in r.samples)


def test_large_divergence_fails():
    stored = [_stored("Busted Index", "^X", "2026-06-19", 200000.0)]
    quotes = {"^X": OfficialQuote("2026-06-19", 168333.61)}  # ~19% off
    r = reconcile_index_levels(stored, quotes)
    assert r.status == FAIL and r.failures == 1


def test_newer_official_means_stored_is_behind_warns_not_fails():
    # source official is a newer session than what we hold → freshness signal, not a fidelity gap
    stored = [_stored("S&P 500", "^GSPC", "2026-06-05", 7400.0)]
    quotes = {"^GSPC": OfficialQuote("2026-06-19", 7500.58)}
    r = reconcile_index_levels(stored, quotes)
    assert r.status == WARN and r.checked == 0  # not compared (different dates)
    assert any("behind the source" in s for s in r.samples)


def test_missing_quote_warns():
    stored = [_stored("Some Index", "^Y", "2026-06-19", 100.0)]
    r = reconcile_index_levels(stored, {"^Y": None})
    assert r.status == WARN and any("no official quote" in s for s in r.samples)


def test_custom_tolerance_can_promote_ibovespa_to_fail():
    stored = [_stored("IBOVESPA", "^BVSP", "2026-06-19", 168576.0)]
    quotes = {"^BVSP": OfficialQuote("2026-06-19", 168333.61)}
    r = reconcile_index_levels(stored, quotes, warn_bps=1.0, fail_bps=10.0)  # ~14 bps > 10
    assert r.status == FAIL
