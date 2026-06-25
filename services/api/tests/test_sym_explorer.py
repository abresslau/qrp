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
    """Dual-role fake (sym + equity) for securities(): count + 12-col meta rows (sym), the page
    prices_raw enrichment + the gap covered-set scans (equity). The same instance is injected as
    both conn and equity_conn — it routes by SQL."""

    def __init__(self, total, rows, *, px=None, covered=None):
        self._total = total
        self._rows = rows                  # 12-col meta rows (NO price columns now)
        self._px = px or {}                # {figi: (close, volume, session_date)}
        self._covered = covered or []      # figis covered in a layer (gap roster-fetch)
        self.seen: list[str] = []
        self.params: list = []

    def execute(self, sql, params=None):
        self.seen.append(sql)
        if params:
            self.params.append(params)
        if "count(*)" in sql:
            return _Cur(one=(self._total,))
        if "max(session_date) FROM prices_raw" in sql:
            return _Cur(one=(date(2026, 6, 18),))
        if "min(window_id) FROM return_window" in sql:
            return _Cur(one=(1,))
        if "DISTINCT composite_figi FROM prices_raw" in sql or \
                "DISTINCT composite_figi FROM fact_returns" in sql:
            return _Cur(rows=[(f,) for f in self._covered])  # gap covered-set (equity)
        if "FROM prices_raw" in sql:  # page enrichment: (figi, close, volume, session_date)
            return _Cur(rows=[(f, *v) for f, v in self._px.items()])
        return _Cur(rows=self._rows)  # the 12-col meta rows query (sym)


def _meta_row(figi, ticker, *, mcap, country, ciso, sector,
              exch_code="US", bbg_exchange_code="UW"):
    # the gateway's 12-column rows SELECT, in order (price columns moved to the equity query)
    return (
        figi, ticker, f"{ticker} Inc", "XNAS", "USD", "active",
        mcap, country, ciso, sector, exch_code, bbg_exchange_code,
    )


def test_securities_maps_enrichment_columns():
    rows = [_meta_row("F1", "AAPL", mcap=3.0e12, country="United States", ciso="US",
                      sector="Information Technology")]
    conn = _ListConn(1, rows, px={"F1": (296.42, 51000000, date(2026, 6, 17))})
    out = DbSymGateway(conn, equity_conn=conn).securities(None, 50, 0)

    assert out["total"] == 1
    r = out["rows"][0]
    assert r["figi"] == "F1" and r["ticker"] == "AAPL"
    assert r["price"] == 296.42 and r["volume"] == 51000000  # from the equity prices_raw read
    assert r["session_date"] == "2026-06-17"
    assert r["market_cap_usd"] == 3.0e12
    assert r["country"] == "United States" and r["country_iso"] == "US"
    assert r["sector"] == "Information Technology"
    assert r["exch_code"] == "US" and r["bbg_exchange_code"] == "UW"
    assert r["mic"] == "XNAS" and r["currency"] == "USD" and r["status"] == "active"


def test_securities_enrichment_is_null_safe():
    # unpriced (no equity px row) + unclassified + unmapped-MIC: every enrichment field → None
    rows = [_meta_row("F2", "OBSCURE", mcap=None, country=None, ciso=None, sector=None,
                      exch_code=None, bbg_exchange_code=None)]
    conn = _ListConn(1, rows)  # no px → unpriced
    out = DbSymGateway(conn, equity_conn=conn).securities(None, 50, 0)
    r = out["rows"][0]
    assert r["price"] is None and r["volume"] is None and r["session_date"] is None
    assert r["market_cap_usd"] is None
    assert r["country"] is None and r["country_iso"] is None and r["sector"] is None
    assert r["exch_code"] is None and r["bbg_exchange_code"] is None


def test_securities_count_query_does_not_carry_enrichment_joins():
    # perf guard: the count(*) must run over the lean _SEC_FROM, NOT the enrichment joins
    conn = _ListConn(7, [])
    DbSymGateway(conn, equity_conn=conn).securities("AAP", 50, 0)
    count_sql = next(s for s in conn.seen if "count(*)" in s)
    assert "prices_raw" not in count_sql
    assert "LEFT JOIN exchange" not in count_sql
    assert "gics_scd" not in count_sql


def test_securities_universe_filter_adds_member_exists_to_count_and_rows():
    conn = _ListConn(1, [])
    # the universe roster lives in its own DB now — inject it (same fake serves all three).
    DbSymGateway(conn, universe_conn=conn, equity_conn=conn).securities(
        None, 50, 0, universe="sp500"
    )
    count_sql = next(s for s in conn.seen if "count(*)" in s)
    rows_sql = next(s for s in conn.seen if "LEFT JOIN exchange" in s)
    for sql in (count_sql, rows_sql):
        # the sym filter is now a roster-bounded ANY(...), not a cross-DB member EXISTS.
        assert "composite_figi = ANY(%s)" in sql
    roster_sql = next(s for s in conn.seen if "universe_member_resolution" in s)
    assert "resolution_status = 'resolved'" in roster_sql
    assert any("sp500" in (p if isinstance(p, (list, tuple)) else [p]) for p in conn.params)


def test_securities_no_universe_has_no_member_filter():
    conn = _ListConn(1, [])
    DbSymGateway(conn, equity_conn=conn).securities(None, 50, 0)
    assert all("universe_member_resolution" not in s for s in conn.seen)


def test_securities_gap_filter_uses_roster_fetch_for_equity_and_not_exists_for_fundamentals():
    # prices/returns gaps are cross-DB now: covered figis fetched from the equity DB, then the
    # sym query restricts to the roster's uncovered remainder via ANY(...). fundamentals stays a
    # sym NOT EXISTS.
    for layer, needle in [("prices", "DISTINCT composite_figi FROM prices_raw"),
                          ("returns", "DISTINCT composite_figi FROM fact_returns")]:
        conn = _ListConn(1, [], covered=["SP0000000001"])
        DbSymGateway(conn, universe_conn=conn, equity_conn=conn).securities(
            None, 50, 0, universe="sp500", gap=layer
        )
        assert any(needle in s for s in conn.seen), layer            # equity covered-set scan
        count_sql = next(s for s in conn.seen if "count(*)" in s)
        assert "NOT EXISTS" not in count_sql                          # not a cross-DB NOT EXISTS
        assert "composite_figi = ANY(%s)" in count_sql               # roster-bounded uncovered set

    conn = _ListConn(1, [])
    DbSymGateway(conn, universe_conn=conn, equity_conn=conn).securities(
        None, 50, 0, universe="sp500", gap="fundamentals"
    )
    count_sql = next(s for s in conn.seen if "count(*)" in s)
    assert "NOT EXISTS" in count_sql and "FROM fundamentals f" in count_sql


def test_securities_gap_ignored_without_universe():
    # gap is a per-universe drill-down — meaningless (and ignored) without a universe
    conn = _ListConn(1, [])
    DbSymGateway(conn, equity_conn=conn).securities(None, 50, 0, gap="prices")
    assert all("NOT EXISTS" not in s for s in conn.seen)
    assert all("DISTINCT composite_figi FROM prices_raw" not in s for s in conn.seen)


def test_securities_rows_query_places_enrichment_joins_before_where():
    # SQL-validity guard: a search builds a WHERE; every JOIN must precede it (Postgres
    # rejects a JOIN after WHERE). The price enrichment moved to a separate equity read, so the
    # remaining sym laterals (exchange/fundamentals/gics) must still precede the WHERE.
    conn = _ListConn(1, [])
    DbSymGateway(conn, equity_conn=conn).securities("AAP", 50, 0)
    rows_sql = next(s for s in conn.seen if "LEFT JOIN exchange" in s)
    where_marker = "WHERE (upper(coalesce(tk.symbol_value"
    assert where_marker in rows_sql  # the search clause is present
    assert rows_sql.index("LEFT JOIN exchange") < rows_sql.index(where_marker)
    assert "FROM prices_raw" not in rows_sql  # the price enrichment is no longer in the sym query


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
        if "FROM gics_source_opinion" in sql:  # the multi-source opinion matrix
            return _Cur(rows=self.f.get("opinions", []))
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
        # the opinion matrix: 3 sources opine; effective is computed by matching the
        # resolved gics_scd source (financedatabase), NOT stored in the opinion rows
        opinions=[
            ("financedatabase", "Information Technology", "Tech Hardware", None),
            ("sec_sic", "Information Technology", None, None),
            ("wikidata", "Information Technology", None, None),
        ],
        country=("United States", "US", "US", "UN"),
        px=(296.42, 51000000, date(2026, 6, 17)),
        fund=(None, 3.0e12, 1.6e10, "USD", date(2026, 6, 16)),
        rets=[],
    )
    d = DbSymGateway(conn, equity_conn=conn).security_detail("F1")

    assert d is not None
    assert d["country"] == "United States" and d["country_iso"] == "US"
    assert d["source"] == "financedatabase"
    assert d["price"]["close"] == 296.42 and d["price"]["volume"] == 51000000
    assert d["price"]["session_date"] == "2026-06-17"
    # the full multi-source breakdown; effective flag matches the resolved source
    assert [c["source"] for c in d["classifications"]] == ["financedatabase", "sec_sic", "wikidata"]
    eff = {c["source"]: c["effective"] for c in d["classifications"]}
    assert eff == {"financedatabase": True, "sec_sic": False, "wikidata": False}


def test_security_detail_falls_back_to_resolved_row_when_opinion_matrix_empty():
    # before `classify-opinions` is run, the matrix is empty — the detail must still show
    # the resolved gics_scd classification (one row, flagged effective).
    conn = _DetailConn(
        master=("F1", "XNAS", "USD", "active", None),
        ticker=("AAPL",),
        name=("Apple Inc",),
        gics=("Information Technology", "Tech Hardware", None, "financedatabase"),
        opinions=[],  # matrix not populated
        country=("United States", "US", "US", "UN"),
        px=(296.42, 51000000, date(2026, 6, 17)),
        fund=None,
        rets=[],
    )
    d = DbSymGateway(conn, equity_conn=conn).security_detail("F1")
    assert [c["source"] for c in d["classifications"]] == ["financedatabase"]
    assert d["classifications"][0]["effective"] is True
    assert d["classifications"][0]["sector"] == "Information Technology"


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
    d = DbSymGateway(conn, equity_conn=conn).security_detail("F9")

    assert d is not None
    assert d["country"] is None and d["country_iso"] is None
    assert d["source"] is None and d["classifications"] == []
    assert d["price"]["close"] is None and d["price"]["volume"] is None
    assert d["fundamentals"] is None


def test_security_detail_returns_none_for_unknown_figi():
    conn = _DetailConn(master=None)
    assert DbSymGateway(conn, equity_conn=conn).security_detail("NOPE") is None
