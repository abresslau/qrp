"""Explorer enrichment (securities list + detail) — DB-free, SQL-dispatching fake conn.

Covers the new list-row fields (price/volume/market_cap_usd/country/sector) incl. null
degradation, and the detail's volume/country/effective-source + the multi-source
`classifications` breakdown. Mirrors the fake-conn pattern in test_sym_quotes / test_sym_live_heatmap.
"""

from __future__ import annotations

from datetime import date

from qrp_api.modules.sym.gateway import DbSymGateway


class _Cur:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _ListConn:
    """Dispatches securities()'s two reads: the count scalar, then the enriched rows."""

    def __init__(self, total, rows):
        self._total = total
        self._rows = rows
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "count(*)" in sql:
            return _Cur(one=(self._total,))
        return _Cur(rows=self._rows)


def _list_row(figi, ticker, *, close, volume, sdate, mcap, country, ciso, sector):
    # shape matches the gateway's 13-column rows SELECT, in order
    return (
        figi, ticker, f"{ticker} Inc", "XNAS", "USD", "active",
        close, volume, sdate, mcap, country, ciso, sector,
    )


def test_securities_maps_enrichment_columns():
    rows = [
        _list_row(
            "F1", "AAPL", close=296.42, volume=51000000, sdate=date(2026, 6, 17),
            mcap=3.0e12, country="United States", ciso="US", sector="Information Technology",
        )
    ]
    out = DbSymGateway(_ListConn(1, rows)).securities(None, 50, 0)

    assert out["total"] == 1
    r = out["rows"][0]
    assert r["figi"] == "F1" and r["ticker"] == "AAPL"
    assert r["price"] == 296.42 and r["volume"] == 51000000
    assert r["session_date"] == "2026-06-17"
    assert r["market_cap_usd"] == 3.0e12
    assert r["country"] == "United States" and r["country_iso"] == "US"
    assert r["sector"] == "Information Technology"
    # existing fields untouched
    assert r["mic"] == "XNAS" and r["currency"] == "USD" and r["status"] == "active"


def test_securities_enrichment_is_null_safe():
    # unpriced + unclassified + unmapped-MIC security: every enrichment field degrades to None
    rows = [
        _list_row(
            "F2", "OBSCURE", close=None, volume=None, sdate=None,
            mcap=None, country=None, ciso=None, sector=None,
        )
    ]
    out = DbSymGateway(_ListConn(1, rows)).securities(None, 50, 0)
    r = out["rows"][0]
    assert r["price"] is None and r["volume"] is None and r["session_date"] is None
    assert r["market_cap_usd"] is None
    assert r["country"] is None and r["country_iso"] is None and r["sector"] is None


def test_securities_count_query_does_not_carry_enrichment_joins():
    # perf guard: the count(*) must run over the lean _SEC_FROM, NOT the enrichment joins
    conn = _ListConn(7, [])
    DbSymGateway(conn).securities("AAP", 50, 0)
    count_sql = next(s for s in conn.seen if "count(*)" in s)
    assert "prices_raw" not in count_sql
    assert "LEFT JOIN exchange" not in count_sql
    assert "gics_scd" not in count_sql


def test_securities_rows_query_places_enrichment_joins_before_where():
    # SQL-validity guard: a search builds a WHERE; every JOIN must precede it (Postgres
    # rejects a JOIN after WHERE). Regression for the enrichment-joins-after-WHERE bug.
    conn = _ListConn(1, [])
    DbSymGateway(conn).securities("AAP", 50, 0)
    rows_sql = next(s for s in conn.seen if "px.close" in s)
    # target the OUTER search clause specifically (the _SEC_FROM laterals also contain "WHERE")
    where_marker = "WHERE (upper(coalesce(tk.symbol_value"
    assert where_marker in rows_sql  # the search clause is present
    assert rows_sql.index("LEFT JOIN exchange") < rows_sql.index(where_marker)
    assert rows_sql.index("FROM prices_raw") < rows_sql.index(where_marker)


class _DetailConn:
    """Dispatches the several reads security_detail() issues, keyed on distinctive SQL."""

    def __init__(self, **fixtures):
        self.f = fixtures
        self.seen: list[str] = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if "FROM securities WHERE composite_figi" in sql:
            return _Cur(one=self.f["master"])
        if "FROM security_symbology" in sql:
            return _Cur(one=self.f.get("ticker"))
        if "FROM security_names" in sql:
            return _Cur(one=self.f.get("name"))
        if "DISTINCT ON (source)" in sql:  # must precede the generic gics_scd match
            return _Cur(rows=self.f.get("by_source", []))
        if "FROM gics_scd" in sql:
            return _Cur(one=self.f.get("gics"))
        if "FROM exchange WHERE mic" in sql:
            return _Cur(one=self.f.get("country"))
        if "FROM prices_raw" in sql:
            return _Cur(one=self.f.get("px"))
        if "FROM fundamentals" in sql:
            return _Cur(one=self.f.get("fund"))
        if "FROM fact_returns" in sql:
            return _Cur(rows=self.f.get("rets", []))
        raise AssertionError(f"unexpected SQL: {sql}")


def test_security_detail_enriches_volume_country_source_and_by_source():
    conn = _DetailConn(
        master=("F1", "XNAS", "USD", "active", None),
        ticker=("AAPL",),
        name=("Apple Inc",),
        gics=("Information Technology", "Tech Hardware", None, "financedatabase"),
        by_source=[
            ("financedatabase", "Information Technology", "Tech Hardware", None, True),
            ("sec_sic", "Information Technology", None, None, False),
        ],
        country=("United States", "US"),
        px=(296.42, 51000000, date(2026, 6, 17)),
        fund=(None, 3.0e12, 1.6e10, "USD", date(2026, 6, 16)),
        rets=[],
    )
    d = DbSymGateway(conn).security_detail("F1")

    assert d is not None
    assert d["country"] == "United States" and d["country_iso"] == "US"
    assert d["source"] == "financedatabase"
    assert d["price"]["close"] == 296.42 and d["price"]["volume"] == 51000000
    assert d["price"]["session_date"] == "2026-06-17"
    # the multi-source breakdown, effective flag carried through
    assert [c["source"] for c in d["classifications"]] == ["financedatabase", "sec_sic"]
    eff = {c["source"]: c["effective"] for c in d["classifications"]}
    assert eff == {"financedatabase": True, "sec_sic": False}


def test_security_detail_null_safe_when_no_enrichment_rows():
    conn = _DetailConn(
        master=("F9", None, "USD", "active", None),  # mic-less → no exchange/country
        ticker=("ZZZ",),
        name=None,
        gics=None,
        by_source=[],
        country=None,
        px=None,
        fund=None,
        rets=[],
    )
    d = DbSymGateway(conn).security_detail("F9")

    assert d is not None
    assert d["country"] is None and d["country_iso"] is None
    assert d["source"] is None and d["classifications"] == []
    assert d["price"]["close"] is None and d["price"]["volume"] is None
    assert d["fundamentals"] is None


def test_security_detail_returns_none_for_unknown_figi():
    conn = _DetailConn(master=None)
    assert DbSymGateway(conn).security_detail("NOPE") is None
