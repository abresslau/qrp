"""Tests for OpenFIGI resolution and FIGI-assignment classification (Story 1.6)."""

from collections.abc import Sequence

import pytest

from sym.identity.figi import (
    AMBIGUOUS_FIGI,
    ASSIGNED,
    NO_FIGI_FOUND,
    SHARE_CLASS_CONFLICT,
    FigiRecord,
    HttpOpenFigiClient,
    OpenFigiError,
    _openfigi_ticker,
    classify,
    detect_share_class_conflicts,
    plan_resolutions,
)
from sym.identity.review_queue import source_key
from sym.identity.universe import ISIN, TICKER, ResolutionInput, SeedSecurity


def _seed(name, ticker="X", mic="XNYS", isin="US0000000000", category="baseline"):
    return SeedSecurity(name=name, category=category, ticker=ticker, mic=mic, isin=isin, note="n")


def _ticker_query(seed):
    return seed.resolution_inputs()[0]


# --- classify --------------------------------------------------------------


def test_unique_match_is_assigned():
    seed = _seed("Apple", ticker="AAPL", mic="XNAS")
    records = [FigiRecord(composite_figi="BBG000B9XRY4", share_class_figi="BBG001S5N8V8")]
    res = classify(seed, _ticker_query(seed), records)
    assert res.outcome == ASSIGNED
    assert res.composite_figi == "BBG000B9XRY4"
    assert res.share_class_figi == "BBG001S5N8V8"


def test_multiple_venue_records_one_composite_still_assigned():
    # Several venue-level FIGIs that share a CompositeFIGI = a single security.
    seed = _seed("Apple", ticker="AAPL", mic="XNAS")
    records = [
        FigiRecord(composite_figi="BBG000B9XRY4", share_class_figi="S", figi="BBG000B9XVV8"),
        FigiRecord(composite_figi="BBG000B9XRY4", share_class_figi="S", figi="BBG000BPHFS9"),
    ]
    res = classify(seed, _ticker_query(seed), records)
    assert res.outcome == ASSIGNED
    assert res.composite_figi == "BBG000B9XRY4"


def test_assigned_resolution_carries_company_name():
    seed = _seed("Apple", ticker="AAPL", mic="XNAS")
    records = [FigiRecord(composite_figi="BBG000B9XRY4", share_class_figi="S", name="APPLE INC")]
    res = classify(seed, _ticker_query(seed), records)
    assert res.outcome == ASSIGNED and res.name == "APPLE INC"


def test_no_records_is_no_figi_found():
    seed = _seed("Enron", ticker="ENE", mic="XNYS")
    res = classify(seed, _ticker_query(seed), [])
    assert res.outcome == NO_FIGI_FOUND
    assert res.detail


def test_multiple_distinct_composites_is_ambiguous():
    seed = _seed("Ambig", ticker="AMB", mic="XNYS")
    records = [
        FigiRecord(composite_figi="BBG000000001", share_class_figi="A"),
        FigiRecord(composite_figi="BBG000000002", share_class_figi="B"),
    ]
    res = classify(seed, _ticker_query(seed), records)
    assert res.outcome == AMBIGUOUS_FIGI
    assert len(res.candidates) == 2
    assert res.composite_figi is None


# --- share-class conflict --------------------------------------------------


def test_distinct_share_classes_keep_distinct_figis():
    googl = _seed("Alphabet A", ticker="GOOGL", mic="XNAS")
    goog = _seed("Alphabet C", ticker="GOOG", mic="XNAS")
    res = [
        classify(googl, _ticker_query(googl), [FigiRecord("BBG009S39JX6", "S")]),
        classify(goog, _ticker_query(goog), [FigiRecord("BBG009S3NB30", "S")]),
    ]
    detect_share_class_conflicts(res)
    assert {r.outcome for r in res} == {ASSIGNED}
    assert {r.composite_figi for r in res} == {"BBG009S39JX6", "BBG009S3NB30"}


def test_shared_composite_across_classes_is_conflict():
    a = _seed("Class A", ticker="AAA", mic="XNYS")
    b = _seed("Class B", ticker="BBB", mic="XNYS")
    shared = "BBG000000099"
    res = [
        classify(a, _ticker_query(a), [FigiRecord(shared, "S")]),
        classify(b, _ticker_query(b), [FigiRecord(shared, "S")]),
    ]
    detect_share_class_conflicts(res)
    assert {r.outcome for r in res} == {SHARE_CLASS_CONFLICT}
    for r in res:
        assert r.composite_figi is None  # nothing auto-assigned
        assert shared in r.detail


# --- plan_resolutions with a fake client -----------------------------------


class _FakeClient:
    """Returns canned records keyed by each query's idValue (order-independent).

    Keying by value (not position) lets the same client serve the two-pass
    resolver: the ticker pass and the ISIN fallback pass each look up their own
    identifier. An unknown value resolves to ``[]`` (a no-match).
    """

    def __init__(self, by_value: dict[str, list[FigiRecord]]):
        self._by_value = by_value

    def map_identifiers(self, inputs: Sequence[ResolutionInput]) -> list[list[FigiRecord]]:
        return [list(self._by_value.get(i.symbol_value, [])) for i in inputs]


def test_plan_resolutions_classifies_each_and_one_no_match_does_not_halt():
    seeds = [
        _seed("Good", ticker="GD", mic="XNYS", isin="US0000000001"),
        _seed("Missing", ticker="MISS", mic="XNYS", isin="US0000000002"),
        _seed("Ambiguous", ticker="AMB", mic="XNYS", isin="US0000000003"),
    ]
    client = _FakeClient(
        {
            "GD": [FigiRecord("BBG000000010", "S")],
            # MISS and its ISIN are both absent -> no match (must not raise)
            "AMB": [FigiRecord("BBG000000020", "A"), FigiRecord("BBG000000021", "B")],
        }
    )
    res = plan_resolutions(seeds, client)
    assert [r.outcome for r in res] == [ASSIGNED, NO_FIGI_FOUND, AMBIGUOUS_FIGI]


def test_isin_fallback_resolves_a_ticker_that_misses():
    # Delisted name: ticker+exchCode misses, but the ISIN resolves to the home
    # listing (exchCode SW) -> assigned via the fallback pass.
    seed = _seed("Credit Suisse", ticker="CSGN", mic="XSWX", isin="CH0012138530")
    client = _FakeClient(
        {
            "CH0012138530": [
                FigiRecord("BBG000G9P6W6", "BBG001S68TR2", exch_code="SW", name="CREDIT SUISSE"),
                FigiRecord("BBG000JDYBP1", "BBG001S68TR2", exch_code="XS"),  # other venue
            ]
        }
    )
    (res,) = plan_resolutions([seed], client, {"XSWX": "SW"})
    assert res.outcome == ASSIGNED
    assert res.composite_figi == "BBG000G9P6W6"  # narrowed to the SW home listing
    assert res.query.symbol_type == ISIN  # resolved via ISIN, recorded as such


def test_isin_fallback_without_home_listing_is_ambiguous_with_candidates():
    # Delisted home listing absent from the ISIN result -> can't narrow -> the
    # candidates are surfaced for review (strictly better than no_figi_found).
    seed = _seed("Gone", ticker="GONE", mic="XSWX", isin="CH9999999999")
    client = _FakeClient(
        {
            "CH9999999999": [
                FigiRecord("BBG000000100", "S", exch_code="XS"),
                FigiRecord("BBG000000200", "S", exch_code="L3"),
            ]
        }
    )
    (res,) = plan_resolutions([seed], client, {"XSWX": "SW"})
    assert res.outcome == AMBIGUOUS_FIGI
    assert len(res.candidates) == 2


def test_isin_fallback_still_no_match_stays_no_figi_found_on_ticker():
    seed = _seed("Ancient", ticker="OLD", mic="XNYS", isin="US1111111111")
    res, = plan_resolutions([seed], _FakeClient({}), {"XNYS": "US"})
    assert res.outcome == NO_FIGI_FOUND
    assert res.query.symbol_type == TICKER  # the ticker miss is what's recorded


# --- HTTP client parsing (injected transport, no network) ------------------


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = 0

    def post(self, url, json, headers, timeout):  # noqa: A002 - mirrors requests API
        self.calls += 1
        return self._response


def test_http_client_parses_data_and_warning():
    payload = [
        {
            "data": [
                {
                    "figi": "BBG000B9XVV8",
                    "compositeFIGI": "BBG000B9XRY4",
                    "shareClassFIGI": "BBG001S5N8V8",
                    "ticker": "AAPL",
                    "exchCode": "US",
                    "securityType": "Common Stock",
                    "name": "APPLE INC",
                }
            ]
        },
        {"warning": "No identifier found."},
    ]
    session = _FakeSession(_FakeResponse(200, payload))
    client = HttpOpenFigiClient(session=session)
    out = client.map_identifiers(
        [ResolutionInput(TICKER, "AAPL", "XNAS"), ResolutionInput(ISIN, "US0000000000")]
    )
    assert out[0][0].composite_figi == "BBG000B9XRY4"
    assert out[0][0].share_class_figi == "BBG001S5N8V8"
    assert out[1] == []


def test_http_client_raises_on_outage():
    session = _FakeSession(_FakeResponse(503, None))
    client = HttpOpenFigiClient(session=session, max_retries=1)
    with pytest.raises(OpenFigiError):
        client.map_identifiers([ResolutionInput(TICKER, "AAPL", "XNAS")])


def test_http_client_retries_then_raises_on_persistent_429(monkeypatch):
    monkeypatch.setattr("sym.identity.figi.time.sleep", lambda _s: None)
    session = _FakeSession(_FakeResponse(429, None))
    client = HttpOpenFigiClient(session=session, max_retries=2)
    with pytest.raises(OpenFigiError):
        client.map_identifiers([ResolutionInput(TICKER, "AAPL", "XNAS")])
    assert session.calls == 2  # retried up to the cap


# --- OpenFIGI ticker normalization + job building --------------------------


def test_openfigi_ticker_normalizes_share_class_and_leading_zeros():
    assert _openfigi_ticker("BRK.A") == "BRK/A"
    assert _openfigi_ticker("0700", "HK") == "700"  # Hong Kong drops leading zeros
    assert _openfigi_ticker("005930", "KS") == "005930"  # Korea KEEPS leading zeros
    assert _openfigi_ticker("AAPL", "US") == "AAPL"  # unchanged


def test_job_uses_exchcode_not_miccode_for_ticker():
    job = HttpOpenFigiClient._job(
        ResolutionInput(TICKER, "BRK.A", "XNYS", exch_code="US")
    )
    assert job == {"idType": "TICKER", "idValue": "BRK/A", "exchCode": "US"}
    assert "micCode" not in job  # the operating MIC must not be sent


def test_job_isin_has_no_exchange_filter():
    job = HttpOpenFigiClient._job(ResolutionInput(ISIN, "US0378331005"))
    assert job == {"idType": "ID_ISIN", "idValue": "US0378331005"}


def test_plan_resolutions_stamps_exch_code_from_map():
    seed = _seed("Apple", ticker="AAPL", mic="XNAS")
    captured = {}

    class _CapturingClient:
        def map_identifiers(self, inputs):
            captured["inputs"] = list(inputs)
            return [[FigiRecord("BBG000B9XRY4", "S")]]

    plan_resolutions([seed], _CapturingClient(), {"XNAS": "US"})
    assert captured["inputs"][0].exch_code == "US"


# --- source_key ------------------------------------------------------------


def test_source_key_shapes():
    assert source_key(ResolutionInput(TICKER, "AAPL", "XNAS")) == "ticker:AAPL@XNAS"
    assert source_key(ResolutionInput(ISIN, "US0378331005")) == "isin:US0378331005"
