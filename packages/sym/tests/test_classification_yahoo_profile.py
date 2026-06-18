"""Yahoo assetProfile→GICS source tests (multi-source, AC #3) — fake client, no network."""

from __future__ import annotations

import contextlib
from datetime import date

import pytest

from sym.classification.gics import SecurityIdentity, apply_classifications
from sym.classification.yahoo_profile import (
    HttpYahooProfileClient,
    YahooProfileError,
    YahooProfileGicsSource,
    _parse_profile_payload,
    yahoo_sector_to_gics,
    yahoo_symbol_for_identity,
)

# --- Yahoo sector → GICS crosswalk -----------------------------------------------------


@pytest.mark.parametrize(
    ("yahoo", "expected"),
    [
        ("Technology", "Information Technology"),
        ("Financial Services", "Financials"),
        ("Healthcare", "Health Care"),
        ("Consumer Cyclical", "Consumer Discretionary"),
        ("Consumer Defensive", "Consumer Staples"),
        ("Industrials", "Industrials"),
        ("Energy", "Energy"),
        ("Basic Materials", "Materials"),
        ("Communication Services", "Communication Services"),
        ("Utilities", "Utilities"),
        ("Real Estate", "Real Estate"),
        ("  energy  ", "Energy"),  # case + whitespace insensitive
    ],
)
def test_yahoo_sector_to_gics_maps_all_eleven(yahoo: str, expected: str):
    assert yahoo_sector_to_gics(yahoo) == expected


@pytest.mark.parametrize("sector", [None, "", "Conglomerates", "Unknown"])
def test_yahoo_sector_to_gics_unmapped_returns_none(sector):
    assert yahoo_sector_to_gics(sector) is None


# --- symbol construction ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticker", "mic", "expected"),
    [
        ("AAPL", "XNAS", "AAPL"),  # US → bare
        ("SHEL", "XLON", "SHEL.L"),  # LSE
        ("ENEL", "XMIL", "ENEL.MI"),  # Milan
        ("BRK.B", "XNYS", "BRK-B"),  # share-class dot → dash, US bare
        ("VOD", None, "VOD"),  # mic-less → trusted bare
    ],
)
def test_yahoo_symbol_for_identity(ticker, mic, expected):
    assert yahoo_symbol_for_identity(SecurityIdentity("F", ticker=ticker, mic=mic)) == expected


def test_yahoo_symbol_none_for_unmappable_mic_or_no_ticker():
    assert yahoo_symbol_for_identity(SecurityIdentity("F", ticker="X", mic="XXXX")) is None
    assert yahoo_symbol_for_identity(SecurityIdentity("F", ticker=None, mic="XLON")) is None


# --- YahooProfileGicsSource.fetch ------------------------------------------------------


class FakeYahooClient:
    """In-memory YahooProfileClient: symbol→(sector, industry), no network."""

    def __init__(self, profiles, raises=None):
        self._profiles = profiles
        self._raises = raises or {}
        self.calls: list[str] = []

    def sector_for_symbol(self, symbol):
        self.calls.append(symbol)
        if symbol in self._raises:
            raise self._raises[symbol]
        return self._profiles.get(symbol, (None, None))


def test_fetch_classifies_non_us_sector_only_with_provenance():
    client = FakeYahooClient({"SHEL.L": ("Energy", "Oil & Gas Integrated")})
    src = YahooProfileGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_SHEL", ticker="SHEL", mic="XLON")])

    assert set(out) == {"FIGI_SHEL"}
    c = out["FIGI_SHEL"]
    assert c.sector_name == "Energy"
    assert c.source == "yahoo_profile"
    # sector-only: Yahoo industries are not GICS industries
    assert c.industry_group_name is None
    assert c.industry_name is None
    assert client.calls == ["SHEL.L"]


def test_fetch_records_unmapped_sector_without_guessing():
    client = FakeYahooClient({"ABC.L": ("Conglomerates", "Conglomerates")})
    src = YahooProfileGicsSource(client=client)
    out = src.fetch([SecurityIdentity("FIGI_ABC", ticker="ABC", mic="XLON")])

    assert out == {}
    assert src.last_unmapped_sector == {"ABC.L": "Conglomerates"}


def test_fetch_records_no_profile_and_unmappable_mic():
    client = FakeYahooClient({})  # NOPROFILE returns (None, None)
    src = YahooProfileGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_NP", ticker="NOPROFILE", mic="XLON"),
            SecurityIdentity("FIGI_BADMIC", ticker="WAT", mic="XXXX"),
        ]
    )

    assert out == {}
    assert src.last_unmatched == ["NOPROFILE.L"]
    assert src.last_unmapped_mic == ["WAT"]


def test_fetch_isolates_a_single_symbol_fetch_error():
    # one symbol errors; the rest of the pass must still classify (per-symbol isolation)
    client = FakeYahooClient(
        {"GOOD.L": ("Utilities", "x")},
        raises={"BAD.L": YahooProfileError("profile fetch failed: HTTP Error 404")},
    )
    src = YahooProfileGicsSource(client=client)
    out = src.fetch(
        [
            SecurityIdentity("FIGI_GOOD", ticker="GOOD", mic="XLON"),
            SecurityIdentity("FIGI_BAD", ticker="BAD", mic="XLON"),
        ]
    )

    assert set(out) == {"FIGI_GOOD"}
    assert out["FIGI_GOOD"].sector_name == "Utilities"
    assert "BAD.L" in src.last_errors


# --- circuit-breaker (consecutive-failure short-circuit on a Yahoo outage) --------------


def _err(msg="HTTP Error 401"):
    return YahooProfileError(msg, is_auth=True)


def test_circuit_breaker_trips_after_consecutive_errors_and_records_remainder():
    from sym.classification.yahoo_profile import MAX_CONSECUTIVE_ERRORS

    # Every symbol errors → a total outage. The pass must stop after K errors and
    # record the not-yet-attempted names instead of walking the whole residual.
    names = [SecurityIdentity(f"F{i}", ticker=f"T{i}", mic="XLON") for i in range(12)]
    client = FakeYahooClient({}, raises={f"T{i}.L": _err() for i in range(12)})
    src = YahooProfileGicsSource(client=client)
    out = src.fetch(names)

    assert out == {}
    # exactly K symbols attempted (each errored), then the breaker tripped
    assert len(client.calls) == MAX_CONSECUTIVE_ERRORS
    assert len(src.last_errors) == MAX_CONSECUTIVE_ERRORS
    # the remaining 12 - K names are recorded as not-attempted, none silently dropped
    assert len(src.last_short_circuited) == 12 - MAX_CONSECUTIVE_ERRORS
    assert src.last_short_circuited[0] == f"T{MAX_CONSECUTIVE_ERRORS}.L"


def test_scattered_errors_interleaved_with_hits_never_trip_the_breaker():
    # errors separated by successes must NOT trip the breaker — a success resets the
    # consecutive counter, so only a genuine run of failures short-circuits.
    profiles, raises, names = {}, {}, []
    for i in range(12):
        names.append(SecurityIdentity(f"F{i}", ticker=f"T{i}", mic="XLON"))
        if i % 2 == 0:
            raises[f"T{i}.L"] = _err()  # every other name errors
        else:
            profiles[f"T{i}.L"] = ("Energy", "x")  # ...but the alternates succeed
    client = FakeYahooClient(profiles, raises=raises)
    src = YahooProfileGicsSource(client=client)
    out = src.fetch(names)

    assert len(client.calls) == 12  # every name attempted — breaker never tripped
    assert src.last_short_circuited == []
    assert len(out) == 6  # the six successes classified


def test_clean_no_profile_resets_the_breaker():
    # a clean no-profile (Yahoo returned (None, None)) is NOT an error and must reset
    # the counter — interleaving no-profiles with errors should never trip the breaker.
    profiles, raises, names = {}, {}, []
    for i in range(12):
        names.append(SecurityIdentity(f"F{i}", ticker=f"T{i}", mic="XLON"))
        if i % 2 == 0:
            raises[f"T{i}.L"] = _err()
        # odd i: absent from profiles → FakeYahooClient returns (None, None) = no-profile
    client = FakeYahooClient(profiles, raises=raises)
    src = YahooProfileGicsSource(client=client)
    src.fetch(names)

    assert len(client.calls) == 12  # never short-circuited
    assert src.last_short_circuited == []
    assert len(src.last_unmatched) == 6  # the no-profiles
    # sanity: with 6 errors total but none consecutive past the threshold, none dropped
    assert len(src.last_errors) == 6


# --- AC8: provenance persists end-to-end through the SCD writer -------------------------


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


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"quoteSummary": None},  # the AttributeError trap (review finding F3)
        {"quoteSummary": {"result": None}},  # Yahoo not-found envelope
        {"quoteSummary": {"result": []}},
        {"finance": {"error": {"code": "Unauthorized"}}},  # other error envelope
        {"quoteSummary": {"result": [None]}},
        {"quoteSummary": {"result": [{"assetProfile": None}]}},
        {"quoteSummary": {"result": [{"assetProfile": {}}]}},  # profile but no sector
        "not a dict",
    ],
)
def test_parse_profile_payload_never_raises_on_malformed(payload):
    # every malformed/error shape → (None, None), NEVER an exception that would
    # escape per-symbol isolation and abort the whole pass (review finding F3)
    assert _parse_profile_payload(payload) == (None, None)


def test_parse_profile_payload_extracts_sector_industry():
    profile = {"sector": "Energy", "industry": "Oil"}
    payload = {"quoteSummary": {"result": [{"assetProfile": profile}]}}
    assert _parse_profile_payload(payload) == ("Energy", "Oil")


class _FakeOpener:
    """Stands in for the urllib opener; returns canned payloads, no network."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.opens = 0

    def open(self, req, timeout=None):  # noqa: A003 — matches urllib opener API
        self.opens += 1
        return self._payloads.pop(0)


def test_http_client_reestablishes_session_on_401(monkeypatch):
    # the auth-retry path (review findings F1/F2): a 401 must trigger exactly one
    # session re-establish + retry, carried via is_auth (not __cause__).
    client = HttpYahooProfileClient(min_interval=0)
    ensure_calls = {"n": 0}

    def fake_ensure():
        ensure_calls["n"] += 1
        client._crumb = "crumb"
        client._opener = object()

    fetches = [
        YahooProfileError("401", is_auth=True),  # first fetch: crumb expired
        {"quoteSummary": {"result": [{"assetProfile": {"sector": "Utilities"}}]}},  # retry OK
    ]

    def fake_fetch(symbol):
        item = fetches.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(client, "_ensure_session", fake_ensure)
    monkeypatch.setattr(client, "_fetch_profile", fake_fetch)

    sector, _ind = client.sector_for_symbol("X.L")
    assert sector == "Utilities"
    assert ensure_calls["n"] == 2  # initial + one re-establish after the 401


def test_http_client_non_auth_error_propagates(monkeypatch):
    client = HttpYahooProfileClient(min_interval=0)
    monkeypatch.setattr(client, "_ensure_session", lambda: None)

    def fake_fetch(symbol):
        raise YahooProfileError("404", is_auth=False)

    monkeypatch.setattr(client, "_fetch_profile", fake_fetch)
    with pytest.raises(YahooProfileError):
        client.sector_for_symbol("X.L")


def test_apply_classifications_persists_yahoo_provenance():
    client = FakeYahooClient({"SHEL.L": ("Energy", "x")})
    plans = list(
        YahooProfileGicsSource(client=client)
        .fetch([SecurityIdentity("FIGI_SHEL", ticker="SHEL", mic="XLON")])
        .values()
    )
    conn = _RecordingConn()
    summary = apply_classifications(conn, plans, as_of_date=date(2026, 6, 17))

    assert summary.rows_inserted == 1
    _sql, params = conn.inserts[0]
    assert "yahoo_profile" in params
    assert "Energy" in params
