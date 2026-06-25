"""Cross-module factor compute tests (Story Q9.2) — fake conns, no network/DB."""

from __future__ import annotations

import json
from datetime import date

import pytest

from signals.compute import (
    FACTORS,
    _ensure_catalog,
    _raw_fiscal_sens,
    _raw_wiki_attention,
    _store,
    _winsorize,
    compute_universe,
)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _RoutedConn:
    """Routes execute() by SQL content; records every (sql, params)."""

    def __init__(self, routes=()):
        self._routes = list(routes)
        self.calls: list[tuple[str, tuple]] = []
        self.autocommit = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        for needle, cur in self._routes:
            if needle in sql:
                return cur
        return _Cur(one=(None,), rows=[])


# ---- catalog traceability (Q9.3) ---------------------------------------------------------


def test_every_factor_declares_inputs_and_method():
    for key, f in FACTORS.items():
        assert f["inputs"], f"{key} has no inputs"
        assert all(":" in ref for ref in f["inputs"]), f"{key} inputs not module-qualified"
        assert f["method"], f"{key} has no method statement"


def test_cross_module_factors_name_their_modules():
    assert any(r.startswith("altdata:") for r in FACTORS["wiki_attention"]["inputs"])
    assert any(r.startswith("macro:") for r in FACTORS["fiscal_sens"]["inputs"])
    # the definition-choice and vintage caveats are stated, not implied
    assert "DEFINITION choice" in FACTORS["fiscal_sens"]["method"]
    assert "current-vintage" in FACTORS["fiscal_sens"]["method"]


def test_ensure_catalog_writes_inputs_and_method():
    conn = _RoutedConn()
    _ensure_catalog(conn)
    assert len(conn.calls) == len(FACTORS)
    sql, params = conn.calls[0]
    assert "inputs" in sql and "method" in sql
    assert "inputs=EXCLUDED.inputs" in sql and "method=EXCLUDED.method" in sql
    # inputs reach the SQL as a JSON array string
    assert json.loads(params[4]) == FACTORS[params[0]]["inputs"]
    assert params[5] == FACTORS[params[0]]["method"]


# ---- pure math ---------------------------------------------------------------------------


def test_winsorize_clips_extremes_preserving_order():
    raw = {f"F{i}": float(i) for i in range(100)}
    raw["HUGE"] = 1e9
    w = _winsorize(raw)
    assert max(w.values()) <= 99.0  # the outlier is capped at the p99 value
    assert w["F50"] == 50.0  # interior values untouched
    assert len(w) == len(raw)


def test_store_orients_rank_and_pctile_by_direction():
    conn = _RoutedConn()
    n = _store(conn, "u", date(2026, 6, 5), "vol_test", "low", {"A": 0.10, "B": 0.30, "C": 0.20})
    assert n == 3
    by_figi = {p[3]: p for _, p in conn.calls}
    # direction low: smallest raw is most favourable
    assert by_figi["A"][6] == 1  # rank
    assert by_figi["B"][6] == 3
    assert by_figi["A"][7] == pytest.approx(1.0)  # pctile, 1 = most favourable
    assert by_figi["A"][5] > 0  # favourable z is positive after orientation


# ---- wiki_attention ----------------------------------------------------------------------


def test_wiki_attention_ratio_and_minimum_obs_gates():
    rows = [
        ("FIGI_OK000000", 200.0, 7, 100.0, 30),   # ratio 2.0
        ("FIGI_THIN7000", 300.0, 3, 100.0, 30),   # n7 < 5: absent
        ("FIGI_THIN3000", 200.0, 7, 100.0, 10),   # n30 < 15: absent
        ("FIGI_ZERO0000", 0.0, 7, 0.0, 30),       # zero 30d mean: absent (no div-by-zero)
    ]
    alt = _RoutedConn([("altdata.observation", _Cur(rows=rows))])
    as_of = date(2026, 6, 5)
    members = ["FIGI_OK000000"]
    out = _raw_wiki_attention(alt, members, as_of)
    assert out == {"FIGI_OK000000": 2.0}
    # the read is bounded at as_of_date (no look-ahead) and scoped to the wiki series
    sql, params = alt.calls[0]
    assert "obs_date <= %s" in sql
    assert "source = 'wikipedia'" in sql
    # parameter ORDERING is the classic bug in this query shape — pin it exactly:
    # (7d filter ×2, members, 30d lower bound, upper bound)
    assert params == (as_of, as_of, members, as_of, as_of)


# ---- fiscal_sens -------------------------------------------------------------------------


def _debt_rows(start: date, pcts: list[float], base: float = 100.0):
    """Build (obs_date, value) rows whose successive %-changes are ``pcts``."""
    rows = [(start, base)]
    v = base
    for i, p in enumerate(pcts):
        v *= 1.0 + p
        rows.append((date.fromordinal(start.toordinal() + i + 1), v))
    return rows


def test_fiscal_sens_recovers_a_known_beta_as_magnitude():
    as_of = date(2026, 6, 5)
    start = date.fromordinal(as_of.toordinal() - 70)
    pcts = [0.001 if i % 2 == 0 else -0.001 for i in range(65)]  # alternating debt changes
    debt = _debt_rows(start, pcts)
    # one name at exactly 2x the debt change, one at exactly -2x: the raw value is the
    # sensitivity MAGNITUDE, so both score |beta| = 2.0 (a signed raw would rank the
    # -2x name "best" under direction low — the bug the review caught)
    pos = [("FIGI_BETA2000", d, 2.0 * ((v / debt[i][1]) - 1.0))
           for i, (d, v) in enumerate(debt[1:])]
    neg = [("FIGI_BETAN200", d, -2.0 * ((v / debt[i][1]) - 1.0))
           for i, (d, v) in enumerate(debt[1:])]
    macro = _RoutedConn([("macro.observation", _Cur(rows=debt))])
    sym = _RoutedConn([("fact_returns", _Cur(rows=pos + neg))])
    out = _raw_fiscal_sens(sym, macro, ["FIGI_BETA2000", "FIGI_BETAN200"], as_of)
    assert out["FIGI_BETA2000"] == pytest.approx(2.0)
    assert out["FIGI_BETAN200"] == pytest.approx(2.0)  # magnitude, not sign
    # the macro read names the series and is bounded at as_of
    sql, params = macro.calls[0]
    assert "UST:DEBT" in sql
    assert "obs_date <= %s" in sql


def test_fiscal_sens_requires_60_matched_days_and_drops_unmatched():
    as_of = date(2026, 6, 5)
    start = date.fromordinal(as_of.toordinal() - 70)
    debt = _debt_rows(start, [0.001] * 65)
    # only 10 return rows match debt dates -> below the 60-day floor -> absent
    ret_rows = [("FIGI_THIN0000", d, 0.01) for d, _ in debt[1:11]]
    macro = _RoutedConn([("macro.observation", _Cur(rows=debt))])
    sym = _RoutedConn([("fact_returns", _Cur(rows=ret_rows))])
    assert _raw_fiscal_sens(sym, macro, ["FIGI_THIN0000"], as_of) == {}


def test_fiscal_sens_zero_variance_debt_yields_no_scores():
    as_of = date(2026, 6, 5)
    start = date.fromordinal(as_of.toordinal() - 70)
    debt = _debt_rows(start, [0.0] * 65)  # constant debt: zero variance
    ret_rows = [("FIGI_X0000000", d, 0.01) for d, _ in debt[1:]]
    macro = _RoutedConn([("macro.observation", _Cur(rows=debt))])
    sym = _RoutedConn([("fact_returns", _Cur(rows=ret_rows))])
    # beta undefined -> absent, never NaN/inf (a non-finite score would 500 the JSON layer)
    assert _raw_fiscal_sens(sym, macro, ["FIGI_X0000000"], as_of) == {}


def test_fiscal_sens_empty_macro_series_yields_no_scores():
    macro = _RoutedConn([("macro.observation", _Cur(rows=[]))])
    sym = _RoutedConn()
    assert _raw_fiscal_sens(sym, macro, ["FIGI_X0000000"], date(2026, 6, 5)) == {}
    assert not sym.calls  # without the macro series there is nothing to regress against


# ---- the public factor seam (Q9.4) -------------------------------------------------------


def test_required_modules_parsed_from_declared_inputs():
    from signals.compute import required_modules

    assert required_modules("mom_12_1") == frozenset()
    assert required_modules("wiki_attention") == frozenset({"altdata"})
    assert required_modules("fiscal_sens") == frozenset({"macro"})
    with pytest.raises(ValueError, match="unknown factor"):
        required_modules("nope")


def test_raw_factor_names_the_missing_module():
    from signals.compute import raw_factor

    with pytest.raises(ValueError, match="macro"):
        raw_factor("fiscal_sens", ["FIGI_A0000000"], date(2026, 6, 5),
                   sym_conn=_RoutedConn(), eq_conn=_RoutedConn())
    with pytest.raises(ValueError, match="altdata"):
        raw_factor("wiki_attention", ["FIGI_A0000000"], date(2026, 6, 5),
                   sym_conn=_RoutedConn(), eq_conn=_RoutedConn())


def test_raw_factor_dispatches_to_the_single_definition():
    from signals.compute import raw_factor

    sym = _RoutedConn([("fundamentals", _Cur(rows=[("FIGI_A0000000", 5e9)]))])
    out = raw_factor("size", ["FIGI_A0000000"], date(2026, 6, 5), sym_conn=sym, eq_conn=sym)
    assert out == {"FIGI_A0000000": 5e9}


# ---- skip attribution --------------------------------------------------------------------


def test_missing_module_connections_skip_factors_with_reasons():
    sym = _RoutedConn([
        ("max(as_of_date) FROM fact_returns", _Cur(one=(date(2026, 6, 5),))),
        ("universe_membership", _Cur(rows=[("FIGI_A0000000",)])),
        ("fact_returns a", _Cur(rows=[])),
        ("stddev_samp", _Cur(rows=[])),
        ("fundamentals", _Cur(rows=[])),
    ])
    sig = _RoutedConn()
    out = compute_universe(sym, sig, "sp500", eq_conn=sym)
    assert out["skipped"] == {
        "wiki_attention": "no altdata connection",
        "fiscal_sens": "no macro connection",
    }
    assert "wiki_attention" not in out["scored"]  # skipped, not zero-scored
    assert "fiscal_sens" not in out["scored"]
