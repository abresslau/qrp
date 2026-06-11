"""Ingest attribution + upsert-param tests for altdata.ingest — fake conns, no DB."""

from __future__ import annotations

from datetime import date

import altdata.ingest as ingest
from altdata.ingest import run_ingest

_START, _END = date(2026, 2, 1), date(2026, 6, 1)

_TWO = {
    "AAPL": ("Apple_Inc.", "Apple"),
    "NVDA": ("Nvidia", "Nvidia"),
}


class FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeSymConn:
    """Resolves tickers to figis from a fixed map (None = unresolved)."""

    def __init__(self, figis: dict[str, str | None]):
        self._figis = figis

    def execute(self, sql, params=None):
        assert "security_symbology" in sql
        return FakeCursor((self._figis[params[0]],) if self._figis.get(params[0]) else None)


class FakeAdConn:
    """Records every (sql, params) reaching the altdata database."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.autocommit = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor(None)


def _series_params(conn):
    return [p for sql, p in conn.calls if "INSERT INTO altdata.series" in sql]


def _obs_params(conn):
    return [p for sql, p in conn.calls if "INSERT INTO altdata.observation" in sql]


def test_run_ingest_upserts_both_sources_with_provenance(monkeypatch):
    monkeypatch.setattr(ingest, "_MAP", _TWO)
    monkeypatch.setattr(
        ingest, "fetch_pageviews",
        lambda article, start, end: [(date(2026, 6, 1), 100.0)],
    )
    monkeypatch.setattr(
        ingest, "fetch_company_ciks",
        lambda tickers: {"AAPL": "0000320193", "NVDA": "0001045810"},
    )
    monkeypatch.setattr(
        ingest, "fetch_sec_filing_counts",
        lambda cik, metrics, start, end: {
            "filings_form4": [(date(2026, 5, 29), 3.0)],
            "filings_8k": [],
        },
    )
    sym = FakeSymConn({"AAPL": "FIGI_AAPL0000", "NVDA": "FIGI_NVDA0000"})
    ad = FakeAdConn()
    res = run_ingest(sym, ad, _START, _END)

    assert ad.autocommit is True  # per-statement commits are real commits (durability)
    # provenance reaches the series rows: article for wikipedia, CIK for sec_edgar
    series = _series_params(ad)
    assert ("FIGI_AAPL0000", "wikipedia", "pageviews",
            "AAPL", "Apple", "Apple_Inc.", "views") in series
    assert ("FIGI_AAPL0000", "sec_edgar", "filings_form4",
            "AAPL", "Apple", "0000320193", "filings") in series
    # observation params carry the full (figi, source, metric, date, value) key
    assert ("FIGI_AAPL0000", "sec_edgar", "filings_form4",
            date(2026, 5, 29), 3.0) in _obs_params(ad)

    by_key = {(s["ticker"], s["source"], s["metric"]): s for s in res["series"]}
    assert by_key[("AAPL", "wikipedia", "pageviews")] == {
        "ticker": "AAPL", "source": "wikipedia", "metric": "pageviews", "ok": True, "obs": 1,
    }
    # obs counts what was upserted for THAT series: the empty 8-K list counts 0, stays ok
    assert by_key[("AAPL", "sec_edgar", "filings_8k")]["obs"] == 0
    assert res["total_obs"] == sum(s.get("obs", 0) for s in res["series"])
    # end-of-run sweep: an obs-less series row is not data and is never served
    assert any("DELETE FROM altdata.series" in sql for sql, _ in ad.calls)


def test_run_ingest_attributes_unresolved_ticker_to_all_its_series(monkeypatch):
    monkeypatch.setattr(ingest, "_MAP", _TWO)
    monkeypatch.setattr(
        ingest, "fetch_pageviews", lambda article, start, end: [(date(2026, 6, 1), 1.0)]
    )
    monkeypatch.setattr(ingest, "fetch_company_ciks", lambda tickers: {"AAPL": "0000320193"})
    monkeypatch.setattr(
        ingest, "fetch_sec_filing_counts",
        lambda cik, metrics, start, end: {"filings_form4": [], "filings_8k": []},
    )
    sym = FakeSymConn({"AAPL": "FIGI_AAPL0000", "NVDA": None})  # NVDA unresolved in sym
    ad = FakeAdConn()
    res = run_ingest(sym, ad, _START, _END)

    nvda = [s for s in res["series"] if s["ticker"] == "NVDA"]
    assert len(nvda) == 3  # wikipedia + 2 sec metrics, every one attributed
    assert all(s["ok"] is False and s["reason"] == "unresolved ticker" for s in nvda)
    # nothing fabricated for the unresolved name
    assert not any("FIGI_NVDA" in str(p) for p in _series_params(ad))


def test_run_ingest_missing_cik_attributed_but_wiki_unaffected(monkeypatch):
    monkeypatch.setattr(ingest, "_MAP", _TWO)
    monkeypatch.setattr(
        ingest, "fetch_pageviews", lambda article, start, end: [(date(2026, 6, 1), 1.0)]
    )
    monkeypatch.setattr(ingest, "fetch_company_ciks", lambda tickers: {"AAPL": "0000320193"})
    monkeypatch.setattr(
        ingest, "fetch_sec_filing_counts",
        lambda cik, metrics, start, end: {"filings_form4": [], "filings_8k": []},
    )
    sym = FakeSymConn({"AAPL": "FIGI_AAPL0000", "NVDA": "FIGI_NVDA0000"})
    ad = FakeAdConn()
    res = run_ingest(sym, ad, _START, _END)

    nvda_sec = [s for s in res["series"] if s["ticker"] == "NVDA" and s["source"] == "sec_edgar"]
    assert len(nvda_sec) == 2
    assert all(s["ok"] is False and "no CIK" in s["reason"] for s in nvda_sec)
    nvda_wiki = [s for s in res["series"] if s["ticker"] == "NVDA" and s["source"] == "wikipedia"]
    assert nvda_wiki == [
        {"ticker": "NVDA", "source": "wikipedia", "metric": "pageviews", "ok": True, "obs": 1}
    ]


def test_run_ingest_cik_map_failure_attributes_every_edgar_series(monkeypatch):
    monkeypatch.setattr(ingest, "_MAP", _TWO)
    monkeypatch.setattr(
        ingest, "fetch_pageviews", lambda article, start, end: [(date(2026, 6, 1), 1.0)]
    )

    def boom(tickers):
        raise ValueError("HTTP 403")

    monkeypatch.setattr(ingest, "fetch_company_ciks", boom)
    # NVDA is unresolved in sym — its reason must NOT be hijacked by the map failure
    sym = FakeSymConn({"AAPL": "FIGI_AAPL0000", "NVDA": None})
    ad = FakeAdConn()
    res = run_ingest(sym, ad, _START, _END)

    sec_rows = [s for s in res["series"] if s["source"] == "sec_edgar"]
    assert len(sec_rows) == 4  # 2 tickers x 2 metrics, no silent omission
    assert all(s["ok"] is False for s in sec_rows)
    by_ticker = {s["ticker"]: s["reason"] for s in sec_rows}
    assert "company_tickers.json" in by_ticker["AAPL"]
    assert by_ticker["NVDA"] == "unresolved ticker"  # its own reason, not the map's
    assert not any(p and p[1] == "sec_edgar" for p in _series_params(ad))


def test_run_ingest_per_ticker_fetch_failure_attributed(monkeypatch):
    monkeypatch.setattr(ingest, "_MAP", _TWO)

    def wiki(article, start, end):
        if article == "Nvidia":
            raise OSError("timed out")
        return [(date(2026, 6, 1), 1.0)]

    monkeypatch.setattr(ingest, "fetch_pageviews", wiki)
    monkeypatch.setattr(
        ingest, "fetch_company_ciks",
        lambda tickers: {"AAPL": "0000320193", "NVDA": "0001045810"},
    )

    def sec(cik, metrics, start, end):
        if cik == "0001045810":
            raise OSError("HTTP 503")
        return {"filings_form4": [(date(2026, 5, 29), 1.0)], "filings_8k": []}

    monkeypatch.setattr(ingest, "fetch_sec_filing_counts", sec)
    sym = FakeSymConn({"AAPL": "FIGI_AAPL0000", "NVDA": "FIGI_NVDA0000"})
    ad = FakeAdConn()
    res = run_ingest(sym, ad, _START, _END)

    by_key = {(s["ticker"], s["source"], s.get("metric")): s for s in res["series"]}
    assert by_key[("NVDA", "wikipedia", "pageviews")]["ok"] is False
    assert "timed out" in by_key[("NVDA", "wikipedia", "pageviews")]["reason"]
    # one submissions fetch serves both metrics — so one failure attributes BOTH
    assert by_key[("NVDA", "sec_edgar", "filings_form4")]["ok"] is False
    assert by_key[("NVDA", "sec_edgar", "filings_8k")]["ok"] is False
    assert by_key[("AAPL", "sec_edgar", "filings_form4")]["ok"] is True
