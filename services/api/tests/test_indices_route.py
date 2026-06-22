"""Benchmark-index endpoints (MSCI EOD pull story). Route-table + gateway parse, DB-free.

The index level data (e.g. MSCI World NR) is pulled into ``index_levels`` by ``sym msci-pull``;
these endpoints expose it read-only. The gateway is exercised with a fake conn (no DB) that
dispatches by SQL, mirroring the project's DB-free API test style.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from qrp_api.main import create_app
from qrp_api.modules.sym.gateway import DbSymGateway


def _route_paths() -> set[str]:
    return {r.path for r in create_app().routes if hasattr(r, "path")}


def test_index_routes_exist():
    paths = _route_paths()
    assert "/api/sym/indices" in paths
    assert "/api/sym/indices/board" in paths
    assert "/api/sym/indices/reconcile" in paths
    assert any(p.startswith("/api/sym/indices/{sym_id}/levels") for p in paths)


def test_index_reconcile_route_returns_check_shape():
    """`/indices/reconcile` returns the live fidelity check's tri-state shape. DB/network-free via a
    dependency override (the gateway method is exercised separately by the sym validate tests)."""
    from qrp_api.modules.sym.router import _gateway

    class _Gw:
        def index_reconcile(self):
            return {
                "status": "warn", "checked": 17, "warnings": 1, "failures": 0,
                "samples": ["WARN IBOVESPA (^BVSP) 2026-06-19: stored 168576 vs official 168334 (14.4 bps)"],
                "detail": "stored latest index close vs source official (warn>=5bps, fail>=50bps)",
            }

    app = create_app()
    app.dependency_overrides[_gateway] = lambda: _Gw()
    client = TestClient(app)
    resp = client.get("/api/sym/indices/reconcile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "warn" and body["checked"] == 17 and body["warnings"] == 1
    assert "IBOVESPA" in body["samples"][0]
    app.dependency_overrides.clear()


def test_index_board_route_accepts_as_of_date_and_rejects_garbage():
    """The board endpoint takes an optional ``as_of_date`` (passed through to the gateway); a bad
    value is a 422 from query-param coercion, never a 500. DB-free via a dependency override."""
    from qrp_api.modules.sym.router import _gateway

    seen: dict = {}

    class _Gw:
        def index_board(self, as_of_date=None):
            seen["as_of_date"] = as_of_date
            return []

    app = create_app()
    app.dependency_overrides[_gateway] = lambda: _Gw()
    client = TestClient(app)
    # valid date → 200, forwarded to the gateway as a real date
    ok = client.get("/api/sym/indices/board", params={"as_of_date": "2026-03-31"})
    assert ok.status_code == 200 and ok.json() == []
    assert seen["as_of_date"] == date(2026, 3, 31)
    # omitted → 200, gateway sees None (latest)
    assert client.get("/api/sym/indices/board").status_code == 200
    assert seen["as_of_date"] is None
    # garbage → 422 (validation), not a 500
    assert client.get("/api/sym/indices/board", params={"as_of_date": "not-a-date"}).status_code == 422
    app.dependency_overrides.clear()


class _BoardConn:
    """Fake conn for index_board(): the ranked last/prev query + the recent-levels query."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN ranked r" in s:  # last + prior session per index
            return _Result([
                (1, "S&P 500", "USD", None, 5000.0, date(2026, 6, 19), 4950.0),
                (2210, "MSCI World Net (USD)", "USD", "990100:NETR", 11731.17, date(2026, 6, 19), 11700.0),
                (2212, "MSCI World Gross (USD)", "USD", "990100:GRTR", 12000.0, date(2026, 6, 19), 11990.0),
            ])
        if "session_date >= (SELECT max(session_date)" in s:  # recent levels (trailing + spark)
            return _Result([
                # S&P 500: enough history to resolve 5Y..5D/MTD/YTD bases + 52w range
                (1, date(2021, 6, 19), 3000.0),   # ~5y base
                (1, date(2023, 6, 19), 3600.0),   # ~3y base
                (1, date(2024, 6, 19), 4000.0),   # ~2y base
                (1, date(2025, 6, 19), 4400.0),   # ~1y base (start of the 52w window)
                (1, date(2025, 12, 19), 4600.0),  # ~6m base
                (1, date(2025, 12, 31), 4500.0),  # prior year-end (YTD)
                (1, date(2026, 3, 19), 4800.0),   # ~3m base
                (1, date(2026, 5, 19), 4700.0),   # ~1m base
                (1, date(2026, 6, 1), 4900.0),    # month-start (MTD)
                (1, date(2026, 6, 12), 4950.0),   # ~5d base
                (1, date(2026, 6, 19), 5000.0),   # latest; 52w-window high
                (2210, date(2025, 12, 31), 11000.0), (2210, date(2026, 6, 19), 11731.17),
            ])
        return _Result([])


def test_index_board_chg_ytd_region_and_msci_net_only():
    out = DbSymGateway(_BoardConn()).index_board()
    by = {r["sym_id"]: r for r in out}
    assert set(by) == {1, 2210}  # the GRTR (gross) MSCI variant is filtered out (Net only)
    sp = by[1]
    assert sp["region"] == "Americas" and sp["currency"] == "USD"
    assert sp["country"] == "United States"  # data-driven country (currency fallback)
    assert by[2210]["country"] == "Global"  # MSCI aggregate
    assert sp["last"] == 5000.0 and sp["last_date"] == "2026-06-19"
    assert abs(sp["chg"] - 50.0) < 1e-9  # 5000 - 4950
    assert abs(sp["chg_pct"] - (5000 / 4950 - 1)) < 1e-9
    # trailing windows, each = last / (last obs on-or-before the window start) - 1
    assert abs(sp["d5"] - (5000 / 4950 - 1)) < 1e-9  # vs ~2026-06-12
    assert abs(sp["mtd"] - (5000 / 4900 - 1)) < 1e-9  # vs 2026-06-01
    assert abs(sp["m1"] - (5000 / 4700 - 1)) < 1e-9  # vs ~2026-05-19
    assert abs(sp["m3"] - (5000 / 4800 - 1)) < 1e-9  # vs ~2026-03-20 -> 2026-03-19
    assert abs(sp["m6"] - (5000 / 4600 - 1)) < 1e-9  # vs ~2025-12-19
    assert abs(sp["ytd"] - (5000 / 4500 - 1)) < 1e-9  # vs 2025-12-31
    assert abs(sp["1y"] - (5000 / 4400 - 1)) < 1e-9  # vs 2025-06-19
    assert abs(sp["2y"] - (5000 / 4000 - 1)) < 1e-9  # vs 2024-06-19
    assert abs(sp["3y"] - (5000 / 3600 - 1)) < 1e-9  # vs 2023-06-19
    assert abs(sp["5y"] - (5000 / 3000 - 1)) < 1e-9  # vs 2021-06-19
    # 52-week range = low/high over the trailing 365d (2025-06-19 onward; older points excluded)
    assert sp["lo_52w"] == 4400.0 and sp["hi_52w"] == 5000.0
    assert sp["spark"] == [3000.0, 3600.0, 4000.0, 4400.0, 4600.0, 4500.0, 4800.0, 4700.0, 4900.0, 4950.0, 5000.0]
    assert by[2210]["region"] == "Global"  # MSCI aggregate


class _BoardConnAsOf:
    """Fake conn for index_board(as_of_date=…): rows are pre-clipped to ≤ the as-of date, so the
    gateway must anchor on the clipped series' last point and re-base every window to it. The ranked
    query returns only S&P 500 (the MSCI rows have no session ≤ the date) → MSCI is OMITTED."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN ranked r" in s:  # anchored = latest session ≤ as_of (and the prior)
            assert "session_date <= %(as_of_date)s" in s  # the as-of filter is applied before ranking
            return _Result([(1, "S&P 500", "USD", None, 4800.0, date(2026, 3, 19), 4750.0)])
        if "session_date <= %(as_of_date)s AND session_date >=" in s:  # recent levels clipped to ≤ as_of
            return _Result([
                (1, date(2025, 3, 19), 4200.0),   # 52w-window start (~1y before the anchor) + 1Y base
                (1, date(2025, 12, 31), 4500.0),  # prior year-end (YTD base)
                (1, date(2026, 2, 27), 4760.0),   # ≤ 2026-03-01 (MTD base)
                (1, date(2026, 3, 12), 4790.0),   # ~5d base
                (1, date(2026, 3, 19), 4800.0),   # the anchor (series[-1])
            ])
        return _Result([])


def test_index_board_as_of_date_rewinds_anchor_and_windows():
    out = DbSymGateway(_BoardConnAsOf()).index_board(as_of_date=date(2026, 3, 31))
    by = {r["sym_id"]: r for r in out}
    assert set(by) == {1}  # MSCI (no session ≤ the as-of date) is omitted — no fabricated row
    sp = by[1]
    # anchor = latest session ≤ 2026-03-31 = 2026-03-19; prior = 4750
    assert sp["last"] == 4800.0 and sp["last_date"] == "2026-03-19" and sp["prev"] == 4750.0
    assert abs(sp["chg"] - 50.0) < 1e-9 and abs(sp["chg_pct"] - (4800 / 4750 - 1)) < 1e-9
    # windows re-based to the as-of anchor (2026-03-19), not to "today"
    assert abs(sp["d5"] - (4800 / 4790 - 1)) < 1e-9   # vs 2026-03-12
    assert abs(sp["mtd"] - (4800 / 4760 - 1)) < 1e-9  # vs 2026-03-01 -> 2026-02-27
    assert abs(sp["ytd"] - (4800 / 4500 - 1)) < 1e-9  # vs 2025-12-31
    assert abs(sp["1y"] - (4800 / 4200 - 1)) < 1e-9   # vs 2025-03-19
    assert sp["2y"] is None and sp["5y"] is None       # no history that far before the as-of date
    # 52-week range = trailing 365d ENDING at the anchor (2025-03-19 onward)
    assert sp["lo_52w"] == 4200.0 and sp["hi_52w"] == 4800.0
    assert sp["spark"] == [4200.0, 4500.0, 4760.0, 4790.0, 4800.0]


class _LiveBoardConn:
    """index_board() ranked+recent queries (S&P 500 + MSCI World NETR) plus the yahoo-xref lookup the
    LIVE board adds. S&P 500 has a `^GSPC` xref (→ quoted); MSCI World has none (→ unavailable)."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "source = 'yahoo' AND sym_id = ANY" in s:
            return _Result([(1, "^GSPC")])  # only S&P 500 has a yahoo xref
        if "JOIN ranked r" in s:
            return _Result([
                (1, "S&P 500", "USD", None, 5000.0, date(2026, 6, 19), 4950.0),
                (2210, "MSCI World Net (USD)", "USD", "990100:NETR", 11000.0, date(2026, 6, 19), 10900.0),
            ])
        if "session_date >= (SELECT max(session_date)" in s:
            return _Result([
                (1, date(2025, 12, 31), 4500.0), (1, date(2026, 6, 19), 5000.0),
                (2210, date(2025, 12, 31), 10000.0), (2210, date(2026, 6, 19), 11000.0),
            ])
        return _Result([])


def test_index_board_live_rebases_to_quote_and_marks_freshness(monkeypatch):
    import qrp_api.modules.sym.quotes as qmod

    # S&P 500 quoted live at 5050 (vs the 5000 EOD close → +1%); MSCI World unquoted → unavailable.
    monkeypatch.setattr(qmod, "now_epoch", lambda: 1050.0)
    monkeypatch.setattr(
        qmod, "fetch_quotes_batch",
        lambda syms, **kw: {"^GSPC": qmod.RawQuote(price=5050.0, prev_close=4990.0, currency="USD", quote_epoch=1000)},
    )
    out = DbSymGateway(_LiveBoardConn()).index_board_live()
    by = {r["sym_id"]: r for r in out["rows"]}
    assert set(by) == {1, 2210}
    sp = by[1]
    # live last + 1D vs the latest EOD close (5000), NOT the quote's own prev_close
    assert sp["last"] == 5050.0 and sp["prev"] == 5000.0
    assert abs(sp["chg_pct"] - (5050 / 5000 - 1)) < 1e-9
    # YTD re-based to the live mark: base unchanged (2025-12-31 = 4500), endpoint now 5050
    assert abs(sp["ytd"] - (5050 / 4500 - 1)) < 1e-9
    assert sp["freshness"] == "live"  # age 50s <= 120
    assert sp["spark"][-1] == 5050.0  # live point appended
    # MSCI World has no yahoo xref → unavailable, EOD values untouched
    msci = by[2210]
    assert msci["freshness"] == "unavailable" and msci["last"] == 11000.0
    assert msci["quote_time"] is None
    # board rollup: 1 priced (live) + 1 unavailable → partial coverage degrades the badge to "delayed"
    # (never reads fully-"live" while a row is stale EOD); as_of tracks the freshest priced quote.
    assert out["priced"] == 1 and out["total"] == 2 and out["freshness"] == "delayed"
    assert out["as_of"] is not None


def test_index_board_live_503_when_provider_unreachable():
    from fastapi.testclient import TestClient

    import qrp_api.modules.sym.quotes as qmod
    from qrp_api.modules.sym import router as sym_router

    app = create_app()

    def _boom(*a, **k):
        raise qmod.QuoteSourceUnreachable("provider down")

    # override the gateway dependency to one whose batch-fetch is wholly unreachable
    class _Gw(DbSymGateway):
        def __init__(self):
            super().__init__(_LiveBoardConn())

    import qrp_api.modules.sym.quotes as q2
    orig = q2.fetch_quotes_batch
    q2.fetch_quotes_batch = _boom
    app.dependency_overrides[sym_router._gateway] = _Gw
    try:
        r = TestClient(app).get("/api/sym/indices/board/live")
        assert r.status_code == 503
    finally:
        q2.fetch_quotes_batch = orig
        app.dependency_overrides.clear()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Dispatches execute() by SQL fragment to canned rows (no DB)."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN index_levels l" in s:  # gateway.indices() list query
            return _Result(
                [
                    (2210, "MSCI World Net (USD)", "USD", "990100:NETR", 6646,
                     date(2000, 12, 29), date(2026, 6, 19), 11731.17),
                ]
            )
        if "SELECT session_date, level FROM index_levels" in s:  # series (asc by date)
            return _Result([
                (date(2000, 12, 29), 2487.61),
                (date(2021, 6, 19), 8000.0),
                (date(2023, 6, 19), 9000.0),
                (date(2025, 6, 19), 10000.0),
                (date(2026, 6, 19), 11731.17),
            ])
        if "FROM instrument i WHERE i.sym_id" in s:  # series meta
            return _Result([("MSCI World Net (USD)", "USD", "990100:NETR")])
        return _Result([])


def test_indices_lists_with_variant_split():
    gw = DbSymGateway(_FakeConn())
    out = gw.indices()
    assert out == [
        {
            "sym_id": 2210, "name": "MSCI World Net (USD)", "currency": "USD",
            "msci_code": "990100", "variant": "NETR", "category": "equity", "n_levels": 6646,
            "first_date": "2000-12-29", "last_date": "2026-06-19", "last_level": 11731.17,
        }
    ]


class _VixListConn:
    """indices() list query returning the VIX (a volatility index) alongside an equity index."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN index_levels l" in s:
            return _Result([
                (1, "S&P 500", "USD", None, 5000, date(2020, 1, 1), date(2026, 6, 19), 5000.0),
                (99, "CBOE Volatility Index (VIX)", "USD", None, 4000,
                 date(2010, 1, 1), date(2026, 6, 19), 17.5),
            ])
        return _Result([])


def test_indices_list_includes_vix_tagged_volatility():
    out = DbSymGateway(_VixListConn()).indices()
    by = {r["sym_id"]: r for r in out}
    assert by[1]["category"] == "equity"
    assert by[99]["category"] == "volatility"  # the Indices page list SHOWS the VIX


class _VixBoardConn:
    """index_board() ranked + recent queries returning an equity index and the VIX."""

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "JOIN ranked r" in s:
            return _Result([
                (1, "S&P 500", "USD", None, 5000.0, date(2026, 6, 19), 4950.0),
                (99, "CBOE Volatility Index (VIX)", "USD", None, 17.5, date(2026, 6, 19), 18.0),
            ])
        if "session_date >= (SELECT max(session_date)" in s:
            return _Result([
                (1, date(2025, 12, 31), 4500.0), (1, date(2026, 6, 19), 5000.0),
                (99, date(2025, 12, 31), 20.0), (99, date(2026, 6, 19), 17.5),
            ])
        return _Result([])


def test_index_board_excludes_volatility_indices():
    out = DbSymGateway(_VixBoardConn()).index_board()
    by = {r["sym_id"]: r for r in out}
    assert set(by) == {1}  # the VIX (volatility) is kept OFF the equity board; only S&P 500 shows


def test_index_levels_series_and_since_start_return():
    gw = DbSymGateway(_FakeConn())
    out = gw.index_levels(2210)
    assert out["sym_id"] == 2210
    assert out["msci_code"] == "990100" and out["variant"] == "NETR"
    assert out["n_levels"] == 5
    assert out["series"][0] == {"date": "2000-12-29", "level": 2487.61}
    # since-start return = last/first - 1
    assert abs(out["since_start_return"] - (11731.17 / 2487.61 - 1.0)) < 1e-9


def test_index_levels_trailing_returns():
    out = DbSymGateway(_FakeConn()).index_levels(2210)
    tr = out["trailing"]
    # all 8 windows present
    assert set(tr) == {"mtd", "qtd", "ytd", "1y", "2y", "3y", "5y", "10y"}
    # latest 2026-06-19 = 11731.17. Bases (last obs on-or-before the window start):
    # MTD/QTD/YTD/1Y -> 2025-06-19 (10000); 2Y/3Y -> 2023-06-19 (9000); 5Y -> 2021-06-19 (8000);
    # 10Y -> 2000-12-29 (2487.61). Each = latest/base - 1.
    assert abs(tr["mtd"] - (11731.17 / 10000.0 - 1.0)) < 1e-9
    assert abs(tr["qtd"] - (11731.17 / 10000.0 - 1.0)) < 1e-9
    assert abs(tr["ytd"] - (11731.17 / 10000.0 - 1.0)) < 1e-9
    assert abs(tr["1y"] - (11731.17 / 10000.0 - 1.0)) < 1e-9
    assert abs(tr["2y"] - (11731.17 / 9000.0 - 1.0)) < 1e-9
    assert abs(tr["3y"] - (11731.17 / 9000.0 - 1.0)) < 1e-9
    assert abs(tr["5y"] - (11731.17 / 8000.0 - 1.0)) < 1e-9
    assert abs(tr["10y"] - (11731.17 / 2487.61 - 1.0)) < 1e-9
