"""SEC SIC→GICS source tests (multi-source classification) — fake client, no network."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from datetime import date

import pytest

from sym.classification.gics import SecurityIdentity, apply_classifications
from sym.classification.sec_sic import (
    SecSicError,
    SecSicGicsSource,
    sic_to_gics_sector,
)

# --- SIC → GICS crosswalk --------------------------------------------------------------


@pytest.mark.parametrize(
    ("sic", "expected"),
    [
        # high-traffic exact overrides beat their coarser parent band
        ("3571", "Information Technology"),  # electronic computers (vs 3500s Industrials)
        ("3674", "Information Technology"),  # semiconductors (vs 3600s)
        ("7372", "Information Technology"),  # prepackaged software (vs 7300s Industrials)
        ("2834", "Health Care"),  # pharmaceutical preparations (vs 2800s Materials)
        ("2836", "Health Care"),  # biological products
        ("3841", "Health Care"),  # surgical & medical instruments (vs 3800s Industrials)
        ("8731", "Health Care"),  # commercial physical & biological research (biotech)
        ("6798", "Real Estate"),  # REITs (vs 6700s Financials)
        ("5912", "Consumer Staples"),  # drug stores (vs 5200-5999 Consumer Discretionary)
        ("7311", "Communication Services"),  # advertising agencies
        # range bands
        ("3724", "Industrials"),  # aircraft engines & parts — HON, the non-Brazil gap
        ("1311", "Energy"),  # crude petroleum & natural gas
        ("4911", "Utilities"),  # electric services
        ("6021", "Financials"),  # national commercial banks
        ("5411", "Consumer Staples"),  # grocery stores
        ("5651", "Consumer Discretionary"),  # family clothing stores
        ("2080", "Consumer Staples"),  # beverages
        ("2911", "Energy"),  # petroleum refining
        ("3312", "Materials"),  # steel works & blast furnaces
        ("4813", "Communication Services"),  # telephone communications
        ("1531", "Consumer Discretionary"),  # operative builders (homebuilders)
        ("8011", "Health Care"),  # offices of physicians
    ],
)
def test_sic_to_gics_sector_maps_expected(sic: str, expected: str):
    assert sic_to_gics_sector(sic) == expected


@pytest.mark.parametrize("sic", [None, "", "abc", "9995", "0000"])
def test_sic_to_gics_sector_unmapped_returns_none(sic):
    # absent / non-numeric / uncovered SIC never guesses a sector
    assert sic_to_gics_sector(sic) is None


# --- SecSicGicsSource.fetch ------------------------------------------------------------


class FakeSecClient:
    """In-memory SecClient: ticker→CIK + CIK→(sic, desc), no network."""

    def __init__(
        self,
        ciks: dict[str, str],
        sics: dict[str, tuple[str | None, str | None]],
        raises: dict[str, SecSicError] | None = None,
    ) -> None:
        self._ciks = ciks
        self._sics = sics
        self._raises = raises or {}
        self.cik_calls: list[Sequence[str]] = []

    def company_ciks(self, tickers: Sequence[str]) -> dict[str, str]:
        self.cik_calls.append(list(tickers))
        return {t.upper(): self._ciks[t.upper()] for t in tickers if t.upper() in self._ciks}

    def sic_for_cik(self, cik: str) -> tuple[str | None, str | None]:
        if cik in self._raises:
            raise self._raises[cik]
        return self._sics.get(cik, (None, None))


def test_fetch_classifies_us_security_sector_only_with_provenance():
    client = FakeSecClient(
        ciks={"HON": "0000773840"},
        sics={"0000773840": ("3724", "Aircraft Engines & Engine Parts")},
    )
    src = SecSicGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_HON", ticker="HON", mic="XNAS")])

    assert set(out) == {"FIGI_HON"}
    c = out["FIGI_HON"]
    assert c.sector_name == "Industrials"
    assert c.source == "sec_sic"
    # sector-only: SIC has no GICS sub-structure
    assert c.industry_group_name is None
    assert c.industry_name is None
    assert c.sub_industry_name is None
    assert c.is_classified
    assert not src.last_unmapped_sic
    assert not src.last_unmatched
    assert not src.last_skipped_non_us


def test_fetch_skips_non_us_listing():
    # a foreign listing sharing a US ticker must NOT inherit a US filer's SIC
    client = FakeSecClient(ciks={"HON": "0000773840"}, sics={"0000773840": ("3724", "x")})
    src = SecSicGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_BR", ticker="HON", mic="BVMF")])

    assert out == {}
    assert src.last_skipped_non_us == ["HON"]
    # skipped before any lookup — the SEC directory is never even queried for it
    assert client.cik_calls == []


def test_fetch_records_unmapped_sic_without_guessing():
    client = FakeSecClient(
        ciks={"WEIRD": "0000000001"},
        sics={"0000000001": ("9995", "Non-Classifiable Establishments")},
    )
    src = SecSicGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_W", ticker="WEIRD", mic="XNYS")])

    assert out == {}
    assert src.last_unmapped_sic == {"WEIRD": ("9995", "Non-Classifiable Establishments")}
    assert not src.last_unmatched


def test_fetch_records_unmatched_when_no_cik_or_no_sic():
    client = FakeSecClient(
        ciks={"HASSIC": "0000000002"},  # NOCIK absent from the directory
        sics={"0000000002": (None, None)},  # HASSIC present but submissions carry no SIC
    )
    src = SecSicGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_NOCIK", ticker="NOCIK", mic="XNAS"),
            SecurityIdentity("FIGI_HASSIC", ticker="HASSIC", mic="XNAS"),
        ]
    )

    assert out == {}
    assert sorted(src.last_unmatched) == ["HASSIC", "NOCIK"]


def test_fetch_mic_less_identity_is_trusted_ticker_only():
    # legacy/test identities without a mic are classified ticker-only (like B3)
    client = FakeSecClient(ciks={"AAPL": "0000320193"}, sics={"0000320193": ("3571", "x")})
    src = SecSicGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_AAPL", ticker="AAPL")])

    assert out["FIGI_AAPL"].sector_name == "Information Technology"


def test_fetch_ignores_identities_without_ticker():
    client = FakeSecClient(ciks={}, sics={})
    src = SecSicGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_X", ticker=None, mic="XNAS")])

    assert out == {}
    # nothing in scope → the SEC directory is never queried
    assert client.cik_calls == []


def test_fetch_isolates_a_single_cik_lookup_error():
    # one CIK's submissions errors (404/403/blip); the rest of the pass must still
    # classify — one bad name never aborts the whole fill (the High-sev review fix).
    client = FakeSecClient(
        ciks={"GOOD": "0000000001", "BAD": "0000000002"},
        sics={"0000000001": ("3571", "Electronic Computers")},
        raises={"0000000002": SecSicError("HTTP Error 404: Not Found")},
    )
    src = SecSicGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_GOOD", ticker="GOOD", mic="XNAS"),
            SecurityIdentity("FIGI_BAD", ticker="BAD", mic="XNAS"),
        ]
    )

    assert set(out) == {"FIGI_GOOD"}  # GOOD still classified despite BAD erroring
    assert out["FIGI_GOOD"].sector_name == "Information Technology"
    assert "BAD" in src.last_errors
    assert "404" in src.last_errors["BAD"]


# --- AC8: provenance persists end-to-end through the SCD writer -------------------------


class _RecordingConn:
    """Minimal fake conn: no current row, records the INSERT params (AC8 provenance)."""

    def __init__(self) -> None:
        self.inserts: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        if sql.upper().lstrip().startswith("INSERT"):
            self.inserts.append((sql, params))
        return _NullCursor()

    def transaction(self):
        return contextlib.nullcontext()


class _NullCursor:
    def fetchone(self):
        return None  # no currently-effective gics_scd row → straight insert

    def fetchall(self):
        return []


def test_apply_classifications_persists_sec_sic_provenance():
    client = FakeSecClient(ciks={"HON": "0000773840"}, sics={"0000773840": ("3724", "x")})
    plans = list(
        SecSicGicsSource(client=client)
        .fetch([SecurityIdentity("FIGI_HON", ticker="HON", mic="XNAS")])
        .values()
    )
    conn = _RecordingConn()
    summary = apply_classifications(conn, plans, as_of_date=date(2026, 6, 17))

    assert summary.rows_inserted == 1
    assert len(conn.inserts) == 1
    _sql, params = conn.inserts[0]
    # the writer must persist source='sec_sic' (provenance), not the default
    assert "sec_sic" in params
    assert "Industrials" in params
