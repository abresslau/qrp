"""Parser tests for altdata.sources — embedded fixture payloads, no network."""

from __future__ import annotations

import json
from datetime import date

import pytest

import altdata.sources as sources
from altdata.sources import fetch_company_ciks, fetch_pageviews, fetch_sec_filing_counts

# --- wikimedia pageviews ---------------------------------------------------------------

_PV_PAYLOAD = {
    "items": [
        {"timestamp": "2026060100", "views": 12000},
        {"timestamp": "2026060200", "views": 13500},
        {"timestamp": "2026060300"},  # missing views: skipped
        {"views": 9000},  # missing timestamp: skipped
    ]
}


def test_fetch_pageviews_parses_dates_and_values(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(_PV_PAYLOAD).encode())
    obs = fetch_pageviews("Apple_Inc.", date(2026, 6, 1), date(2026, 6, 3))
    assert obs == [(date(2026, 6, 1), 12000.0), (date(2026, 6, 2), 13500.0)]


def test_fetch_pageviews_skips_non_finite_views(monkeypatch):
    # stdlib json accepts NaN/Infinity tokens — a bad vendor cell must be skipped, not
    # persisted (the API's JSON encoder cannot serialize it and would 500 the endpoint)
    raw = (b'{"items":[{"timestamp":"2026060100","views":Infinity},'
           b'{"timestamp":"2026060200","views":7}]}')
    monkeypatch.setattr(sources, "_get", lambda url: raw)
    obs = fetch_pageviews("X", date(2026, 6, 1), date(2026, 6, 2))
    assert obs == [(date(2026, 6, 2), 7.0)]


def test_fetch_pageviews_url_formats_window(monkeypatch):
    seen: list[str] = []

    def fake_get(url: str) -> bytes:
        seen.append(url)
        return b'{"items":[]}'

    monkeypatch.setattr(sources, "_get", fake_get)
    fetch_pageviews("Nvidia", date(2026, 1, 2), date(2026, 3, 4))
    assert "Nvidia/daily/2026010200/2026030400" in seen[0]


def test_fetch_pageviews_percent_encodes_article(monkeypatch):
    # an unencoded '%' would be reinterpreted server-side and silently fetch a DIFFERENT
    # article's data; '?'/'/' would alter the request path
    seen: list[str] = []

    def fake_get(url: str) -> bytes:
        seen.append(url)
        return b'{"items":[]}'

    monkeypatch.setattr(sources, "_get", fake_get)
    fetch_pageviews("100%_(song)", date(2026, 1, 1), date(2026, 1, 2))
    assert "100%25_%28song%29" in seen[0]  # quote(safe="") encodes % AND parens
    assert "100%_" not in seen[0]


def test_fetch_pageviews_missing_items_key_raises(monkeypatch):
    # an absent block is a shape break (attributable error) — only a PRESENT-but-empty
    # list is honest no-data
    monkeypatch.setattr(sources, "_get", lambda url: b'{"detail":"not found"}')
    with pytest.raises(ValueError, match="items"):
        fetch_pageviews("X", date(2026, 1, 1), date(2026, 1, 2))


def test_fetch_pageviews_skips_typeerror_garble(monkeypatch):
    # list-valued views / non-string timestamp raise TypeError, not ValueError — the
    # per-row skip contract must hold for both
    payload = {"items": [
        {"timestamp": "2026060100", "views": [1, 2]},
        {"timestamp": 20260602, "views": 5},
        {"timestamp": "2026060300", "views": 9},
    ]}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    obs = fetch_pageviews("X", date(2026, 6, 1), date(2026, 6, 3))
    assert obs == [(date(2026, 6, 3), 9.0)]


# --- SEC company_tickers.json ----------------------------------------------------------

_CIK_PAYLOAD = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}


def test_fetch_company_ciks_zero_pads_and_filters(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(_CIK_PAYLOAD).encode())
    out = fetch_company_ciks({"AAPL", "NVDA", "ZZZQ"})
    # requested tickers only; 10-digit zero-pad; absent ticker simply absent (caller attributes)
    assert out == {"AAPL": "0000320193", "NVDA": "0001045810"}


def test_fetch_company_ciks_first_occurrence_wins(monkeypatch):
    dup = {"0": {"cik_str": 1, "ticker": "AAPL"}, "1": {"cik_str": 2, "ticker": "AAPL"}}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(dup).encode())
    assert fetch_company_ciks({"AAPL"}) == {"AAPL": "0000000001"}


def test_fetch_company_ciks_non_dict_payload_raises(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: b"[]")
    with pytest.raises(ValueError, match="company_tickers"):
        fetch_company_ciks({"AAPL"})


def test_fetch_company_ciks_garbled_row_skipped_not_fatal(monkeypatch):
    # one non-numeric cik_str must not kill every other company's EDGAR series — the
    # ticker reads as absent and the caller attributes it
    payload = {
        "0": {"cik_str": "N/A", "ticker": "AAPL"},
        "1": {"cik_str": 1045810, "ticker": "NVDA"},
    }
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    assert fetch_company_ciks({"AAPL", "NVDA"}) == {"NVDA": "0001045810"}


# --- SEC submissions filing counts -----------------------------------------------------

_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["4", "8-K", "4/A", "4", "4", "10-Q", "8-K"],
            "filingDate": [
                "2026-06-02",  # 4 in window
                "2026-06-02",  # 8-K in window
                "2026-06-02",  # 4/A: amendment, NOT counted (exact match)
                "2026-06-02",  # 4 same day: aggregates to count 2
                "2026-05-01",  # 4 before window: excluded
                "2026-06-03",  # 10-Q: not a tracked form
                "garbled",     # garbled date: skipped, never invented
            ],
        }
    }
}

_METRICS = {"filings_form4": frozenset({"4"}), "filings_8k": frozenset({"8-K"})}


def test_fetch_sec_filing_counts_windows_and_aggregates(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(_SUBMISSIONS).encode())
    out = fetch_sec_filing_counts("0000320193", _METRICS, date(2026, 6, 1), date(2026, 6, 30))
    assert out == {
        "filings_form4": [(date(2026, 6, 2), 2.0)],  # two Form 4s that day; 4/A excluded
        "filings_8k": [(date(2026, 6, 2), 1.0)],
    }


def test_fetch_sec_filing_counts_one_fetch_serves_all_metrics(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str) -> bytes:
        calls.append(url)
        return json.dumps(_SUBMISSIONS).encode()

    monkeypatch.setattr(sources, "_get", fake_get)
    fetch_sec_filing_counts("0000320193", _METRICS, date(2026, 6, 1), date(2026, 6, 30))
    assert len(calls) == 1
    assert "CIK0000320193.json" in calls[0]


def test_fetch_sec_filing_counts_empty_window_yields_empty_lists(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(_SUBMISSIONS).encode())
    out = fetch_sec_filing_counts("0000320193", _METRICS, date(2020, 1, 1), date(2020, 1, 2))
    # dates with no matching filings are true zeros: nothing emitted, nothing fabricated
    assert out == {"filings_form4": [], "filings_8k": []}


def test_fetch_sec_filing_counts_mismatched_arrays_raise(monkeypatch):
    bad = {"filings": {"recent": {"form": ["4", "8-K"], "filingDate": ["2026-06-02"]}}}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(bad).encode())
    with pytest.raises(ValueError):
        # a malformed payload is an attributable error, not data
        fetch_sec_filing_counts("0000320193", _METRICS, date(2026, 6, 1), date(2026, 6, 30))


def test_fetch_sec_filing_counts_missing_recent_block_raises(monkeypatch):
    # a wholly absent filings.recent is a shape break — ok:True/obs:0 would be a lie
    monkeypatch.setattr(sources, "_get", lambda url: b'{"cik":"0000320193"}')
    with pytest.raises(ValueError, match="filings.recent"):
        fetch_sec_filing_counts("0000320193", _METRICS, date(2026, 6, 1), date(2026, 6, 30))


def test_fetch_sec_filing_counts_window_edges_inclusive(monkeypatch):
    payload = {"filings": {"recent": {
        "form": ["4", "4", "4", "4"],
        "filingDate": ["2026-05-31", "2026-06-01", "2026-06-30", "2026-07-01"],
    }}}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    out = fetch_sec_filing_counts("1", {"filings_form4": frozenset({"4"})},
                                  date(2026, 6, 1), date(2026, 6, 30))
    # [start, end] is inclusive on BOTH edges; the day before/after are out
    assert out["filings_form4"] == [(date(2026, 6, 1), 1.0), (date(2026, 6, 30), 1.0)]


def test_fetch_sec_filing_counts_truncation_guard_drops_boundary_day(monkeypatch):
    # at the 1000-filing cap the earliest day's count may be cut mid-day — it must be
    # dropped, not stored as a quiet undercount
    forms = ["4"] * 1000
    dates = ["2026-06-05"] * 998 + ["2026-06-02", "2026-06-02"]
    payload = {"filings": {"recent": {"form": forms, "filingDate": dates}}}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    out = fetch_sec_filing_counts("1", {"filings_form4": frozenset({"4"})},
                                  date(2026, 6, 1), date(2026, 6, 30))
    assert out["filings_form4"] == [(date(2026, 6, 5), 998.0)]  # boundary day excluded


def test_fetch_sec_filing_counts_below_cap_keeps_earliest_day(monkeypatch):
    # under the cap the block IS full history for the window — nothing is dropped
    payload = {"filings": {"recent": {
        "form": ["4", "4"], "filingDate": ["2026-06-05", "2026-06-02"],
    }}}
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    out = fetch_sec_filing_counts("1", {"filings_form4": frozenset({"4"})},
                                  date(2026, 6, 1), date(2026, 6, 30))
    assert out["filings_form4"] == [(date(2026, 6, 2), 1.0), (date(2026, 6, 5), 1.0)]


def test_fetch_sec_filing_counts_sorted_ascending(monkeypatch):
    payload = {
        "filings": {
            "recent": {
                "form": ["4", "4", "4"],
                # newest first (live order)
                "filingDate": ["2026-06-09", "2026-06-03", "2026-06-05"],
            }
        }
    }
    monkeypatch.setattr(sources, "_get", lambda url: json.dumps(payload).encode())
    out = fetch_sec_filing_counts("1", {"filings_form4": frozenset({"4"})},
                                  date(2026, 6, 1), date(2026, 6, 30))
    assert [d for d, _ in out["filings_form4"]] == [
        date(2026, 6, 3), date(2026, 6, 5), date(2026, 6, 9)
    ]
