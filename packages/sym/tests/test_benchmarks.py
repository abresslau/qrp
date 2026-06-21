"""Tests for the benchmark registry + index-level sourcing (B2). DB-free.

Each published index series is its own instrument (no per-row variant); the name
distinguishes price vs total-return.
"""

from __future__ import annotations

from sym.benchmarks.levels import BENCHMARKS, Benchmark, benchmark_xrefs, load_index_levels, region_for


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
