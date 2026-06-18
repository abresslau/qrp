"""SEC SIC→GICS source tests (multi-source classification) — fake client, no network."""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from datetime import date

import pytest

from sym.classification.gics import SecurityIdentity, apply_classifications
from sym.classification.sec_sic import (
    HttpSecClient,
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


# --- HttpSecClient.company_ciks duplicate-ticker / CIK dedup ---------------------------


def _directory(rows):
    """Build a company_tickers.json-shaped directory: {idx: {cik_str, ticker, title}}."""
    return {str(i): row for i, row in enumerate(rows)}


def _submissions(tickers, dates):
    return {"tickers": tickers, "filings": {"recent": {"filingDate": dates}}}


def test_company_ciks_single_cik_path_is_unchanged_and_makes_no_extra_calls(monkeypatch):
    client = HttpSecClient(min_interval=0)
    calls: list[str] = []

    def fake_get(url):
        calls.append(url)
        return _directory(
            [
                {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"},
                {"cik_str": 773840, "ticker": "HON", "title": "Honeywell"},
            ]
        )

    monkeypatch.setattr(client, "_get_json", fake_get)
    out = client.company_ciks(["AAPL", "HON"])

    assert out == {"AAPL": "0000320193", "HON": "0000773840"}
    assert client.last_ambiguous_ticker == {}
    # only the directory was fetched — no submissions calls for single-CIK tickers
    assert len(calls) == 1


def test_company_ciks_resolves_duplicate_ticker_to_active_filer(monkeypatch):
    # ZZZ appears under two CIKs (an old delisted filer + a new active one). The
    # resolver must pick the filer that still lists ZZZ as current, not directory order.
    client = HttpSecClient(min_interval=0)
    stale = "0000000111"
    active = "0000000222"

    def fake_get(url):
        if "company_tickers" in url:
            return _directory(
                [
                    {"cik_str": 111, "ticker": "ZZZ", "title": "Old Filer (delisted)"},
                    {"cik_str": 222, "ticker": "ZZZ", "title": "New Filer (active)"},
                ]
            )
        if stale in url:
            return _submissions(["WAS"], ["2014-02-01"])  # no longer lists ZZZ, old filing
        if active in url:
            return _submissions(["ZZZ"], ["2026-05-01"])  # currently lists ZZZ, recent
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(client, "_get_json", fake_get)
    out = client.company_ciks(["ZZZ"])

    assert out == {"ZZZ": active}  # NOT the first directory row (stale)
    # the collision is surfaced for the report, listing both candidate CIKs
    assert client.last_ambiguous_ticker == {"ZZZ": [stale, active]}


def test_company_ciks_duplicate_ticker_falls_back_to_first_when_submissions_unreadable(monkeypatch):
    client = HttpSecClient(min_interval=0)

    def fake_get(url):
        if "company_tickers" in url:
            return _directory(
                [
                    {"cik_str": 111, "ticker": "ZZZ", "title": "A"},
                    {"cik_str": 222, "ticker": "ZZZ", "title": "B"},
                ]
            )
        raise SecSicError("submissions unreachable")

    monkeypatch.setattr(client, "_get_json", fake_get)
    out = client.company_ciks(["ZZZ"])

    # no submissions reachable → deterministic fallback to the first candidate, still surfaced
    assert out == {"ZZZ": "0000000111"}
    assert client.last_ambiguous_ticker == {"ZZZ": ["0000000111", "0000000222"]}


def test_company_ciks_duplicate_ticker_tie_breaks_on_recency_when_both_list_ticker(monkeypatch):
    # both filers CURRENTLY list ZZZ — the active-listing signal ties, so the resolver
    # must fall through to most-recent filingDate (proves filingDate isn't ignored).
    client = HttpSecClient(min_interval=0)

    def fake_get(url):
        if "company_tickers" in url:
            return _directory(
                [
                    {"cik_str": 111, "ticker": "ZZZ", "title": "Older"},
                    {"cik_str": 222, "ticker": "ZZZ", "title": "Newer"},
                ]
            )
        if "0000000111" in url:
            return _submissions(["ZZZ"], ["2019-03-01"])  # lists ZZZ but older
        if "0000000222" in url:
            return _submissions(["ZZZ"], ["2026-05-01"])  # lists ZZZ and more recent
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(client, "_get_json", fake_get)
    out = client.company_ciks(["ZZZ"])

    assert out == {"ZZZ": "0000000222"}  # recency broke the active-listing tie


def test_resolve_active_cik_survives_malformed_submissions_without_raising(monkeypatch):
    # A partial/malformed submissions payload must NOT crash the resolver (and thus
    # abort the whole fill pass): an all-falsy filingDate list (empty after filtering)
    # and a non-list `tickers` are the concrete traps. Falls back to the first CIK.
    client = HttpSecClient(min_interval=0)

    def fake_get(url):
        if "company_tickers" in url:
            return _directory(
                [
                    {"cik_str": 111, "ticker": "ZZZ", "title": "A"},
                    {"cik_str": 222, "ticker": "ZZZ", "title": "B"},
                ]
            )
        # both malformed: tickers is a bare string (truthy non-list), filingDate all-falsy
        return {"tickers": "ZZZ", "filings": {"recent": {"filingDate": ["", None]}}}

    monkeypatch.setattr(client, "_get_json", fake_get)
    out = client.company_ciks(["ZZZ"])  # must not raise

    assert out == {"ZZZ": "0000000111"}  # graceful fallback to the first candidate
    assert client.last_ambiguous_ticker == {"ZZZ": ["0000000111", "0000000222"]}


def test_source_surfaces_ambiguity_from_the_client():
    # the source copies the client's collision record into its own side-channel so the
    # renderer can report it (the live client has it; a plain fake wouldn't).
    class _AmbiguousClient:
        last_ambiguous_ticker = {"ZZZ": ["0000000111", "0000000222"]}

        def company_ciks(self, tickers):
            return {"ZZZ": "0000000222"}

        def sic_for_cik(self, cik):
            return ("3571", "Electronic Computers")

    src = SecSicGicsSource(client=_AmbiguousClient())
    out = src.fetch([SecurityIdentity("FIGI_Z", ticker="ZZZ", mic="XNAS")])

    assert out["FIGI_Z"].sector_name == "Information Technology"
    assert src.last_ambiguous_ticker == {"ZZZ": ["0000000111", "0000000222"]}


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
