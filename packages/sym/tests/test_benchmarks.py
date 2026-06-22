"""Tests for the benchmark registry + index-level sourcing (B2). DB-free.

Each published index series is its own instrument (no per-row variant); the name
distinguishes price vs total-return.
"""

from __future__ import annotations

from sym.benchmarks.levels import (
    BENCHMARKS,
    Benchmark,
    benchmark_xrefs,
    category_for,
    country_for,
    load_index_levels,
    region_for,
)


def test_country_for_name_map_currency_fallback_and_msci():
    assert country_for("S&P 500", "USD") == "United States"  # currency fallback
    assert country_for("IBOVESPA", "BRL") == "Brazil"
    assert country_for("DAX (Total Return)", "EUR") == "Germany"  # name map beats EUR->Eurozone
    assert country_for("CAC 40", "EUR") == "France"
    assert country_for("FTSE 100", "GBP") == "United Kingdom"
    assert country_for("Nikkei 225", "JPY") == "Japan"
    assert country_for("MSCI World Net (USD)", "USD") == "Global"  # aggregate
    assert country_for("MSCI USA", "USD") == "United States"
    assert country_for("MSCI Europe", "EUR") == "Europe"
    assert country_for("Mystery Index", None) == "—"  # unknown


def test_registry_yahoo_symbols_unique():
    syms = [b.yahoo_symbol for b in BENCHMARKS if b.yahoo_symbol]
    assert len(syms) == len(set(syms))


def test_price_and_total_return_are_separate_named_indexes():
    names = {b.name for b in BENCHMARKS}
    assert "S&P 500" in names                    # price series
    assert "S&P 500 (Total Return)" in names      # total-return series — a distinct index
    # distinct Yahoo symbols -> distinct instruments
    by_name = {b.name: b for b in BENCHMARKS}
    assert by_name["S&P 500"].yahoo_symbol == "^GSPC"
    assert by_name["S&P 500 (Total Return)"].yahoo_symbol == "^SP500TR"


def test_msci_world_is_deferred_no_yahoo():
    msci = next(b for b in BENCHMARKS if b.name.startswith("MSCI World"))
    assert msci.yahoo_symbol is None and msci.msci_code


def test_msci_registry_xref_is_variant_encoded_to_reconcile_with_pull():
    # The registry MSCI World entry must resolve to the SAME instrument `sym msci-pull --variant NR`
    # creates (msci xref 990100:NETR) — so a re-seed never mints a bare-code 990100 stub again.
    msci = next(b for b in BENCHMARKS if b.name.startswith("MSCI World"))
    assert msci.variant == "NR"
    assert benchmark_xrefs(msci) == {"msci": "990100:NETR"}


def test_region_for_known_and_msci_and_currency_fallback():
    # registry-mapped exchange indices
    assert region_for("S&P 500") == "Americas"
    assert region_for("FTSE 100") == "EMEA"
    assert region_for("Nikkei 225") == "Asia-Pacific"
    assert region_for("IBOVESPA") == "Americas"
    # MSCI aggregates -> Global (incl. the seeded variants not in the registry)
    assert region_for("MSCI World (Net Total Return)") == "Global"
    assert region_for("MSCI ACWI Net (USD)") == "Global"
    # currency fallback for an unknown name
    assert region_for("Some Unknown Index", "JPY") == "Asia-Pacific"
    assert region_for("Some Unknown Index", "EUR") == "EMEA"
    assert region_for("Some Unknown Index", None) == "Global"


def test_every_registry_benchmark_has_a_region():
    assert all(b.region for b in BENCHMARKS)


def test_regional_indices_in_registry_with_region_and_yahoo_xref():
    by_name = {b.name: b for b in BENCHMARKS}
    expected = {
        "Hang Seng Index": ("^HSI", "Asia-Pacific", "HKD"),
        "CSI 300": ("000300.SS", "Asia-Pacific", "CNY"),
        "STOXX Europe 600": ("^STOXX", "EMEA", "EUR"),
    }
    for name, (ysym, region, ccy) in expected.items():
        b = by_name.get(name)
        assert b is not None, f"{name} should be in the benchmark registry"
        assert b.yahoo_symbol == ysym and benchmark_xrefs(b)["yahoo"] == ysym
        assert b.region == region and b.currency_code == ccy
        assert b.category == "equity"  # equity → shows on the WEI board
        assert region_for(name, ccy) == region


def test_vix_in_registry_as_volatility_with_yahoo_xref():
    vix = next((b for b in BENCHMARKS if "VIX" in b.name), None)
    assert vix is not None, "VIX should be in the benchmark registry"
    assert vix.yahoo_symbol == "^VIX"
    assert vix.category == "volatility"
    assert benchmark_xrefs(vix)["yahoo"] == "^VIX"


def test_category_for_defaults_equity_and_flags_vix():
    # the VIX is tagged volatility; everything else (incl. unknown names) is equity
    assert category_for("CBOE Volatility Index (VIX)") == "volatility"
    assert category_for("S&P 500") == "equity"
    assert category_for("FTSE 100") == "equity"
    assert category_for("Some Unknown Index") == "equity"
    assert category_for(None) == "equity"
    # every equity benchmark is category 'equity' (only the VIX is excluded from the board)
    non_equity = {b.name for b in BENCHMARKS if b.category != "equity"}
    assert non_equity == {"CBOE Volatility Index (VIX)"}


def test_benchmark_xrefs_yahoo_and_legacy_bare_msci():
    assert benchmark_xrefs(Benchmark("Y", "USD", yahoo_symbol="^Y")) == {"yahoo": "^Y"}
    # a legacy MSCI entry with no variant keeps the bare code (backward-compatible)
    assert benchmark_xrefs(Benchmark("Z", "USD", msci_code="999")) == {"msci": "999"}


class _FakeSource:
    SOURCE = "yahoo"

    def __init__(self, series):
        self._series = series

    def levels(self, symbol, start):
        return self._series


class _FakeConn:
    """Stub: ensure_instrument finds nothing (creates id 1); upserts always insert."""

    def __init__(self):
        self.levels_inserted = 0
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        if "INSERT INTO index_levels" in sql:
            self.levels_inserted += 1
        return self

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def fetchone(self):
        if "SELECT sym_id FROM instrument_xref" in self._sql:
            return None  # no existing xref -> create
        if "RETURNING sym_id" in self._sql:
            return (1,)
        return None

    @property
    def autocommit(self):
        return True

    @autocommit.setter
    def autocommit(self, v):
        pass


def test_load_skips_msci_only_and_loads_yahoo():
    from datetime import date
    from decimal import Decimal

    conn = _FakeConn()
    bms = [
        Benchmark("X", "USD", yahoo_symbol="^X"),
        Benchmark("MSCI-ish", "USD", msci_code="999"),
    ]
    src = _FakeSource([(date(2024, 1, 2), Decimal("100")), (date(2024, 1, 3), Decimal("101"))])
    summary = load_index_levels(conn, src, bms, start=date(2024, 1, 1))
    assert summary.instruments == 2
    assert summary.deferred == 1          # MSCI-only deferred
    assert summary.levels_written == 2    # the yahoo one loaded 2 levels


class _CaptureConn:
    """Fake conn that records each index_levels write as (session_date, level, conflict-clause)."""

    def __init__(self):
        self.writes = []
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        if "INSERT INTO index_levels" in sql:
            conflict = "DO UPDATE" if "DO UPDATE" in sql else "DO NOTHING"
            self.writes.append((params[1], params[2], conflict))  # (session_date, level, conflict)
        return self

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def fetchone(self):
        if "SELECT sym_id FROM instrument_xref" in self._sql:
            return None
        if "RETURNING sym_id" in self._sql:
            return (1,)
        return None

    @property
    def autocommit(self):
        return True

    @autocommit.setter
    def autocommit(self, v):
        pass


def test_load_revises_latest_session_to_official_close():
    """The latest session's candle close is revised to the vendor's OFFICIAL close (overwriteable);
    history rows keep their candle close and stay append-only (DO NOTHING)."""
    from datetime import date, timedelta
    from decimal import Decimal

    today = date.today()
    d_old, d_latest = today - timedelta(days=2), today - timedelta(days=1)

    class _Src:
        SOURCE = "yahoo"

        def levels(self, symbol, start):
            return [(d_old, Decimal("100")), (d_latest, Decimal("110"))]  # candle latest = 110

        def official_quote(self, symbol):
            return d_latest.isoformat(), 108.5  # official differs from the candle

    conn = _CaptureConn()
    bms = [Benchmark("X", "USD", yahoo_symbol="^X")]
    load_index_levels(conn, _Src(), bms, start=date(2024, 1, 1))
    by_date = {d: (lv, c) for d, lv, c in conn.writes}
    assert by_date[d_latest] == (Decimal("108.5"), "DO UPDATE")  # official + overwriteable
    assert by_date[d_old] == (Decimal("100"), "DO NOTHING")  # history: candle, append-only


def test_load_keeps_candle_when_official_date_does_not_match_latest():
    """If the official quote is for a different session than the latest stored, keep the candle."""
    from datetime import date, timedelta
    from decimal import Decimal

    today = date.today()
    d_latest = today - timedelta(days=1)

    class _Src:
        SOURCE = "yahoo"

        def levels(self, symbol, start):
            return [(d_latest, Decimal("110"))]

        def official_quote(self, symbol):
            return today.isoformat(), 108.5  # official is for TODAY (newer) — must not apply

    conn = _CaptureConn()
    bms = [Benchmark("X", "USD", yahoo_symbol="^X")]
    load_index_levels(conn, _Src(), bms, start=date(2024, 1, 1))
    assert {d: lv for d, lv, _ in conn.writes}[d_latest] == Decimal("110")  # candle kept


def test_official_quote_parses_meta(monkeypatch):
    """official_quote reads regularMarketPrice + the exchange-local date from regularMarketTime."""
    import io
    import json

    from sym.benchmarks.levels import YahooIndexLevelSource

    payload = {
        "chart": {"result": [{"meta": {
            "regularMarketPrice": 168333.61,
            "regularMarketTime": 1781900220,  # 2026-06-19 20:17 UTC
            "gmtoffset": -10800,  # São Paulo → local session date 2026-06-19
        }}]}
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=30: io.BytesIO(json.dumps(payload).encode())
    )
    iso, price = YahooIndexLevelSource().official_quote("^BVSP")
    assert iso == "2026-06-19" and price == 168333.61
