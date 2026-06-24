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

    def __init__(self, primary=None, anchors=None, points=None, currency=None, tenors=None):
        self.primary = primary or {}
        self.anchors = anchors or {}
        self.points = points or {}
        self.currency = currency or {}
        self.tenors = tenors or {}  # {country: set of distinct tenors} for generic spread specs

    def execute(self, sql, params=None):
        co = params[0] if params else None
        if "GROUP BY curve_set, basis, rate_type" in sql:  # _primary_series (CTE on latest day)
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
    # a govt/yield country with 2,5,10 → expect 2s10s and 2s5s10s fly (no 30y → no 5s30s)
    conn = _Conn(
        primary={"CA": ("govt", "nominal", "yield")},
        tenors={"CA": {2.0, 5.0, 10.0}},
    )
    keys = {s["key"] for s in DbRatesGateway(conn)._spread_specs("CA")}
    assert keys == {"2s10s", "2s5s10s"}
