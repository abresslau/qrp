"""Cross-country comparison + generic (non-UK) curve spreads. DB-free (fake conn by SQL marker)."""

from __future__ import annotations

from datetime import date

from rates.gateway import DbRatesGateway


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    """primary: {country: (cs,b,rt)}; anchors: {country: date}; points: {country: [(tenor,val)]};
    currency: {country: ccy}; series_rows: leg-group rows for the spread query."""

    def __init__(self, primary=None, anchors=None, points=None, currency=None, tenors=None,
                 latest_series=None):
        self.primary = primary or {}
        self.anchors = anchors or {}
        self.points = points or {}
        self.currency = currency or {}
        self.tenors = tenors or {}  # {country: set of distinct tenors} for generic spread specs
        # {country: [(curve_set, basis, rate_type, n), ...]} present on the latest day
        self.latest_series = latest_series or {}

    def execute(self, sql, params=None):
        co = params[0] if params else None
        if "count(*) AS n" in sql:  # _latest_day_series (bases on the country's latest day)
            return _Cur(all_=self.latest_series.get(co, []))
        if "GROUP BY curve_set, basis, rate_type" in sql:  # _primary_series (CTE, nominal)
            return _Cur(one=self.primary.get(co))
        if "max(currency)" in sql:
            return _Cur(one=(self.currency.get(co),))
        if "DISTINCT tenor FROM rates.curve_point" in sql:  # generic spread spec tenor probe
            return _Cur(all_=[(t,) for t in sorted(self.tenors.get(co, set()))])
        if "max(as_of_date)" in sql:  # curve() anchor
            return _Cur(one=(self.anchors.get(co),))
        if "ORDER BY tenor" in sql:  # curve points
            return _Cur(all_=self.points.get(co, []))
        return _Cur()


def test_compare_curves_uses_each_countrys_primary_series():
    conn = _Conn(
        primary={"DE": ("govt", "nominal", "spot"), "US": ("govt", "nominal", "par")},
        anchors={"DE": date(2026, 6, 19), "US": date(2026, 6, 19)},
        points={"DE": [(2.0, 2.4, "bundesbank"), (10.0, 2.9, "bundesbank")],
                "US": [(2.0, 4.3, "ustreasury"), (10.0, 4.5, "ustreasury")]},
        currency={"DE": "EUR", "US": "USD"},
    )
    out = DbRatesGateway(conn).compare_curves(["DE", "US"])
    by_c = {r["country"]: r for r in out}
    assert by_c["DE"]["rate_type"] == "spot" and by_c["DE"]["currency"] == "EUR"
    assert by_c["US"]["rate_type"] == "par" and by_c["US"]["currency"] == "USD"
    assert by_c["US"]["source"] == "ustreasury"  # provenance carried through compare
    assert by_c["DE"]["points"] == [{"tenor": 2.0, "value": 2.4}, {"tenor": 10.0, "value": 2.9}]


def test_compare_curves_skips_country_with_no_series():
    conn = _Conn(primary={"DE": ("govt", "nominal", "spot")}, anchors={"DE": date(2026, 6, 19)},
                 points={"DE": [(2.0, 2.4, "bundesbank")]}, currency={"DE": "EUR"})
    out = DbRatesGateway(conn).compare_curves(["DE", "XX"])  # XX has no primary series
    assert [r["country"] for r in out] == ["DE"]


def test_generic_spreads_built_from_primary_curve_tenors():
    # a govt/yield country with 2,5,10 (no real curve) → expect 2s10s and 2s5s10s fly, NO breakeven
    conn = _Conn(
        primary={"CA": ("govt", "nominal", "yield")},
        tenors={"CA": {2.0, 5.0, 10.0}},
        latest_series={"CA": [("govt", "nominal", "yield", 3)]},  # no real basis
    )
    keys = {s["key"] for s in DbRatesGateway(conn)._spread_specs("CA")}
    assert keys == {"2s10s", "2s5s10s"}  # no real series → no breakeven spec


def test_br_gets_interpolated_breakeven_when_real_curve_present():
    # BR has a real govt curve in the same curve_set as nominal and no fitted inflation curve →
    # a generic INTERPOLATED breakeven spec (IPCA, approx) is added. Raw per-issue tenors → no
    # exact-tenor 2s10s (tenors don't hit 2.0/10.0), so breakeven is the headline derived spread.
    conn = _Conn(
        primary={"BR": ("govt", "nominal", "yield")},
        tenors={"BR": {0.51, 5.51, 9.8}},  # per-issue floats — no exact 2/5/10
        latest_series={"BR": [("govt", "nominal", "yield", 8), ("govt", "real", "yield", 11)]},
    )
    specs = DbRatesGateway(conn)._spread_specs("BR")
    be = next(s for s in specs if s["key"] == "be10y")
    assert be["interp"] is True and be["unit"] == "%" and be["tenor"] == 10.0
    assert "IPCA" in be["label"] and "approx" in be["label"]
    assert be["nominal"] == ("BR", "govt", "nominal", "yield")
    assert be["real"] == ("BR", "govt", "real", "yield")


def test_breakeven_suppressed_when_country_publishes_inflation_curve():
    # US GSW already stores basis='inflation' (BKEVEN) → don't derive a second, generic breakeven.
    conn = _Conn(
        primary={"US": ("gsw", "nominal", "spot")},
        tenors={"US": {2.0, 5.0, 10.0, 30.0}},
        latest_series={"US": [("gsw", "nominal", "spot", 30), ("gsw", "real", "spot", 19),
                              ("gsw", "inflation", "spot", 19)]},
    )
    keys = {s["key"] for s in DbRatesGateway(conn)._spread_specs("US")}
    assert "be10y" not in keys  # inflation already published → no derived duplicate


def test_breakeven_skipped_when_real_is_a_different_curve_set():
    # real curve exists but in a DIFFERENT curve_set than the nominal primary → don't cross curves.
    conn = _Conn(
        primary={"XX": ("govt", "nominal", "par")},
        tenors={"XX": {2.0, 10.0}},
        latest_series={"XX": [("govt", "nominal", "par", 5), ("gsw", "real", "spot", 9)]},
    )
    keys = {s["key"] for s in DbRatesGateway(conn)._spread_specs("XX")}
    assert "be10y" not in keys


class _CurveConn:
    """Serves _full_curve_by_date: {(co,cs,b,rt): [(date,tenor,value), ...]}."""

    def __init__(self, rows_by_series):
        self.rows = rows_by_series

    def execute(self, sql, params=None):
        if "as_of_date, tenor, value FROM rates.curve_point" in sql:
            return _Cur(all_=self.rows.get(tuple(params), []))
        return _Cur()


def test_interp_breakeven_uses_interpolation_over_non_matching_tenors():
    # nominal 8y=12.0,12y=13.0 → interp(10y)=12.5 ; real 6y=6.0,14y=7.0 → interp(10y)=6.5
    # breakeven(10y) = 12.5 - 6.5 = 6.0%.  (No exact 10y node on either curve — pure interpolation.)
    d = date(2026, 6, 30)
    conn = _CurveConn({
        ("BR", "govt", "nominal", "yield"): [(d, 8.0, 12.0), (d, 12.0, 13.0)],
        ("BR", "govt", "real", "yield"): [(d, 6.0, 6.0), (d, 14.0, 7.0)],
    })
    spec = {"key": "be10y", "interp": True, "tenor": 10.0,
            "nominal": ("BR", "govt", "nominal", "yield"),
            "real": ("BR", "govt", "real", "yield")}
    series = DbRatesGateway(conn)._interp_breakeven_series(spec)
    assert len(series) == 1
    assert series[0][0] == d
    assert abs(series[0][1] - 6.0) < 1e-9


def test_interp_breakeven_skips_dates_where_tenor_outside_grid():
    # nominal only reaches 5y here → 10y not bracketed → interp None → date dropped (honest).
    d = date(2026, 6, 30)
    conn = _CurveConn({
        ("BR", "govt", "nominal", "yield"): [(d, 1.0, 14.0), (d, 5.0, 13.0)],   # max 5y
        ("BR", "govt", "real", "yield"): [(d, 6.0, 6.0), (d, 30.0, 7.0)],
    })
    spec = {"key": "be10y", "interp": True, "tenor": 10.0,
            "nominal": ("BR", "govt", "nominal", "yield"),
            "real": ("BR", "govt", "real", "yield")}
    assert DbRatesGateway(conn)._interp_breakeven_series(spec) == []
