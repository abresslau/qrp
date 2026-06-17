"""FMP company-profile→GICS source tests (multi-source) — fake client, no network/key."""

from __future__ import annotations

import contextlib
from datetime import date

import pytest

from sym.classification.fmp_profile import (
    FmpProfileError,
    FmpProfileGicsSource,
    HttpFmpProfileClient,
    fmp_sector_to_gics,
    fmp_symbol_for_identity,
)
from sym.classification.gics import SecurityIdentity, apply_classifications

# --- FMP sector → GICS crosswalk -------------------------------------------------------


@pytest.mark.parametrize(
    ("fmp", "expected"),
    [
        ("Technology", "Information Technology"),
        ("Financial Services", "Financials"),
        ("Healthcare", "Health Care"),
        ("Consumer Cyclical", "Consumer Discretionary"),
        ("Consumer Defensive", "Consumer Staples"),
        ("Industrials", "Industrials"),
        ("Industrial Goods", "Industrials"),  # legacy FMP label
        ("Energy", "Energy"),
        ("Basic Materials", "Materials"),
        ("Communication Services", "Communication Services"),
        ("Utilities", "Utilities"),
        ("Real Estate", "Real Estate"),
        ("  technology  ", "Information Technology"),  # case + whitespace insensitive
    ],
)
def test_fmp_sector_to_gics_maps_expected(fmp, expected):
    assert fmp_sector_to_gics(fmp) == expected


@pytest.mark.parametrize("sector", [None, "", "Conglomerates", "Services"])
def test_fmp_sector_to_gics_unmapped_returns_none(sector):
    assert fmp_sector_to_gics(sector) is None


# --- symbol construction ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticker", "mic", "expected"),
    [
        ("AAPL", "XNAS", "AAPL"),
        ("SHEL", "XLON", "SHEL.L"),
        ("BRK.B", "XNYS", "BRK-B"),
        ("VOD", None, "VOD"),
    ],
)
def test_fmp_symbol_for_identity(ticker, mic, expected):
    assert fmp_symbol_for_identity(SecurityIdentity("F", ticker=ticker, mic=mic)) == expected


def test_fmp_symbol_none_for_unmappable_mic_or_no_ticker():
    assert fmp_symbol_for_identity(SecurityIdentity("F", ticker="X", mic="XXXX")) is None
    assert fmp_symbol_for_identity(SecurityIdentity("F", ticker=None, mic="XNYS")) is None


# --- FmpProfileGicsSource.fetch --------------------------------------------------------


class FakeFmpClient:
    """In-memory FmpProfileClient: symbol → (sector, industry, is_fund)."""

    def __init__(self, profiles, raises=None):
        self._profiles = profiles
        self._raises = raises or {}
        self.calls: list[str] = []

    def profile_for_symbol(self, symbol):
        self.calls.append(symbol)
        if symbol in self._raises:
            raise self._raises[symbol]
        return self._profiles.get(symbol, (None, None, False))


def test_fetch_classifies_sector_only_with_fmp_provenance():
    client = FakeFmpClient({"CMA": ("Financial Services", "Banks", False)})
    src = FmpProfileGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_CMA", ticker="CMA", mic="XNYS")])

    assert set(out) == {"FIGI_CMA"}
    c = out["FIGI_CMA"]
    assert c.sector_name == "Financials"
    assert c.source == "fmp"
    assert c.industry_group_name is None
    assert c.industry_name is None


def test_fetch_skips_funds_by_is_fund_flag():
    # FMP's isFund/isEtf → deliberately left unclassified (a fund has no GICS sector)
    client = FakeFmpClient({"JAVA": ("Financial Services", "Asset Management", True)})
    src = FmpProfileGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_JAVA", ticker="JAVA", mic="XNAS")])

    assert out == {}
    assert src.last_skipped_fund == ["JAVA"]
    assert not src.last_unmatched


def test_fetch_records_unmapped_sector_and_no_profile():
    client = FakeFmpClient({"WEIRD": ("Conglomerates", "x", False)})  # NOPROF → (None,None,False)
    src = FmpProfileGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_W", ticker="WEIRD", mic="XNYS"),
            SecurityIdentity("FIGI_NP", ticker="NOPROF", mic="XNYS"),
        ]
    )
    assert out == {}
    assert src.last_unmapped_sector == {"WEIRD": "Conglomerates"}
    assert src.last_unmatched == ["NOPROF"]


def test_fetch_isolates_a_single_symbol_error_and_records_no_key():
    client = FakeFmpClient(
        {"GOOD": ("Energy", "Oil & Gas", False)},
        raises={"BAD": FmpProfileError("FMP requires an API key (set FMP_API_KEY)")},
    )
    src = FmpProfileGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_GOOD", ticker="GOOD", mic="XNYS"),
            SecurityIdentity("FIGI_BAD", ticker="BAD", mic="XNYS"),
        ]
    )
    assert set(out) == {"FIGI_GOOD"}  # one error never aborts the pass
    assert "BAD" in src.last_errors
    assert "API key" in src.last_errors["BAD"]


def test_fetch_unmappable_mic_recorded():
    client = FakeFmpClient({})
    src = FmpProfileGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_X", ticker="X", mic="XXXX")])
    assert out == {}
    assert src.last_unmapped_mic == ["X"]


# --- the live client without a key raises (dormant-until-keyed contract) ----------------


def test_http_client_without_key_raises():
    client = HttpFmpProfileClient(api_key="")  # explicit empty → no key
    with pytest.raises(FmpProfileError, match="API key"):
        client.profile_for_symbol("AAPL")


# --- AC8: provenance persists end-to-end ------------------------------------------------


class _RecordingConn:
    def __init__(self):
        self.inserts: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        if sql.upper().lstrip().startswith("INSERT"):
            self.inserts.append((sql, params))
        return _NullCursor()

    def transaction(self):
        return contextlib.nullcontext()


class _NullCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_apply_classifications_persists_fmp_provenance():
    client = FakeFmpClient({"ZEUS": ("Basic Materials", "Steel", False)})
    plans = list(
        FmpProfileGicsSource(client=client)
        .fetch([SecurityIdentity("FIGI_ZEUS", ticker="ZEUS", mic="XNYS")])
        .values()
    )
    conn = _RecordingConn()
    summary = apply_classifications(conn, plans, as_of_date=date(2026, 6, 17))
    assert summary.rows_inserted == 1
    _sql, params = conn.inserts[0]
    assert "fmp" in params
    assert "Materials" in params
