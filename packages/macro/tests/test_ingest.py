"""Upsert/restatement + summary-attribution tests for macro.ingest — fake conn, no DB."""

from __future__ import annotations

from datetime import date

import pytest

import macro.ingest as ingest
from macro.ingest import _upsert, run_ingest


class FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Records every (sql, params); scripts fetchone() results for observation upserts.

    Script entries model the three upsert outcomes: ``(False,)`` fresh insert, ``(True,)``
    existing row whose value changed (restatement), ``None`` identical row (DO UPDATE's
    WHERE filtered it out — nothing returned).
    """

    def __init__(self, obs_results=()):
        self.calls: list[tuple[str, object]] = []
        self._obs_results = list(obs_results)
        self.autocommit = False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "INSERT INTO macro.observation" in sql:
            return FakeCursor(self._obs_results.pop(0))
        return FakeCursor(None)


_META = {
    "series_id": "T:1", "source": "test", "name": "t", "geo": "g",
    "unit": "u", "frequency": "monthly", "category": "rates",
}


def _empty_focus(*args, **kwargs):
    """No-op stub for the BCB Focus fetcher: a valid meta with no observations, so the
    run_ingest dispatch tests can neutralize that source without a network call (the
    empty-obs series is dropped by _upsert, contributing nothing to the summary SQL)."""
    meta = {
        "series_id": "BCB:FOCUS_IPCA_12M", "source": "bcb_focus", "name": "f",
        "geo": "Brazil", "unit": "% per year", "frequency": "daily",
    }
    return meta, []


def test_upsert_counts_obs_and_restatements_separately():
    conn = FakeConn(obs_results=[(False,), None, (True,)])
    obs = [(date(2025, 1, 1), 1.0), (date(2025, 2, 1), 2.0), (date(2025, 3, 1), 3.0)]
    n, restated = _upsert(conn, _META, obs)
    assert n == 3  # all observations processed/present
    assert restated == 1  # ONLY the value change counts — not the insert, not the no-op


def test_upsert_params_reach_sql():
    conn = FakeConn(obs_results=[(False,)])
    _upsert(conn, _META, [(date(2025, 1, 1), 1.5)])
    series_sql, series_params = conn.calls[0]
    assert "INSERT INTO macro.series" in series_sql
    assert series_params == _META
    obs_sql, obs_params = conn.calls[1]
    assert obs_params == ("T:1", date(2025, 1, 1), 1.5)


def test_upsert_observation_sql_is_conditional_on_value_change():
    conn = FakeConn(obs_results=[(False,)])
    _upsert(conn, _META, [(date(2025, 1, 1), 1.0)])
    obs_sql = conn.calls[1][0]
    assert "IS DISTINCT FROM" in obs_sql  # equal-value re-ingest must NOT rewrite the row
    assert "last_changed_at = now()" in obs_sql  # a value change re-stamps the marker


def test_upsert_empty_series_writes_nothing():
    conn = FakeConn()
    assert _upsert(conn, _META, []) == (0, 0)
    assert conn.calls == []


def test_upsert_refuses_non_canonical_category():
    # category slugs appear in console URLs — anything outside the canonical set is a
    # loud config error attributed per-series, never written to the catalog
    conn = FakeConn()
    no_category = {k: v for k, v in _META.items() if k != "category"}
    bads = [no_category, dict(_META, category=None), dict(_META, category="Inflation"),
            dict(_META, category="weather")]
    for meta in bads:
        with pytest.raises(ValueError, match="category"):
            _upsert(conn, meta, [(date(2025, 1, 1), 1.0)])
    assert conn.calls == []


def test_upsert_series_sql_carries_category():
    conn = FakeConn(obs_results=[(False,)])
    _upsert(conn, _META, [(date(2025, 1, 1), 1.0)])
    series_sql = conn.calls[0][0]
    assert "category" in series_sql
    assert "category = EXCLUDED.category" in series_sql  # recategorisation propagates


def test_run_ingest_attaches_declared_categories(monkeypatch):
    # every series upsert must carry a canonical category — the strongest drift guard:
    # run the FULL dispatch with fakes and inspect what reached the SQL
    monkeypatch.setattr(ingest, "_ECB", [])
    monkeypatch.setattr(ingest, "_EUROSTAT", [])
    monkeypatch.setattr(ingest, "_BCB", [])
    monkeypatch.setattr(ingest, "_IBGE", [])
    monkeypatch.setattr(ingest, "_MARKET", [])
    monkeypatch.setattr(ingest, "fetch_treasury_par_yield", lambda *a, **k: [])
    monkeypatch.setattr(ingest, "fetch_bcb_focus_12m", _empty_focus)
    monkeypatch.setattr(ingest, "_OECD_CPI_GEOS", ["USA"])
    monkeypatch.setattr(
        ingest, "_WB",
        [("SP.POP.TOTL", "Population", "millions", "population", 1e-6, ["US"])],
    )

    def fake_wb(indicator, name, unit, geos, scale=1.0):
        meta = {"series_id": f"WB:{indicator}:{geos[0]}", "source": "worldbank", "name": name,
                "geo": geos[0], "unit": unit, "frequency": "annual"}
        return [(meta, [(date(2024, 12, 31), 341.0)])]

    monkeypatch.setattr(ingest, "fetch_worldbank", fake_wb)
    monkeypatch.setattr(ingest, "fetch_oecd_cpi", lambda geo: (
        {"series_id": f"OECD:CPI:{geo}", "source": "oecd", "name": "CPI", "geo": geo,
         "unit": "%", "frequency": "monthly"}, [(date(2025, 1, 1), 2.5)]))
    monkeypatch.setattr(ingest, "fetch_fiscaldata_debt", lambda: (
        {"series_id": "UST:DEBT", "source": "fiscaldata", "name": "d", "geo": "US",
         "unit": "USD trillions", "frequency": "daily"}, [(date(2025, 1, 2), 39.2)]))
    # one avg-rate series so the call site's "rates" literal is inspected at the SQL
    # boundary too (review finding: stubbing this to [] left the literal untested)
    monkeypatch.setattr(ingest, "fetch_fiscaldata_avg_rates", lambda: [(
        {"series_id": "UST:AVG_RATE:BILLS", "source": "fiscaldata", "name": "r",
         "geo": "US", "unit": "%", "frequency": "monthly"}, [(date(2025, 1, 31), 3.7)])])

    conn = FakeConn(obs_results=[(False,)] * 4)
    result = run_ingest(conn)
    assert all(s["ok"] for s in result["series"])
    series_categories = {p["series_id"]: p["category"] for sql, p in conn.calls
                         if "INSERT INTO macro.series" in sql}
    assert series_categories == {
        "WB:SP.POP.TOTL:US": "population",
        "OECD:CPI:USA": "inflation",
        "UST:DEBT": "debt",
        "UST:AVG_RATE:BILLS": "rates",
    }


def test_upsert_collapses_same_date_duplicates_last_wins():
    # Two rows for one date must NOT hit ON CONFLICT against each other — that would
    # count a vendor restatement that never happened. Last occurrence wins.
    conn = FakeConn(obs_results=[(False,), (False,)])
    obs = [
        (date(2025, 1, 1), 1.0),
        (date(2025, 1, 1), 1.5),  # duplicate date, later value
        (date(2025, 2, 1), 2.0),
    ]
    n, restated = _upsert(conn, _META, obs)
    assert (n, restated) == (2, 0)  # 2 unique dates; no fabricated restatement
    obs_params = [params for sql, params in conn.calls if "macro.observation" in sql]
    assert obs_params == [
        ("T:1", date(2025, 1, 1), 1.5),  # last wins
        ("T:1", date(2025, 2, 1), 2.0),
    ]


def test_run_ingest_attributes_failures_per_series(monkeypatch):
    monkeypatch.setattr(ingest, "_WB", [])
    monkeypatch.setattr(ingest, "_ECB", [])
    monkeypatch.setattr(ingest, "_EUROSTAT", [])
    monkeypatch.setattr(ingest, "_BCB", [])
    monkeypatch.setattr(ingest, "_IBGE", [])
    monkeypatch.setattr(ingest, "_MARKET", [])
    monkeypatch.setattr(ingest, "fetch_treasury_par_yield", lambda *a, **k: [])
    monkeypatch.setattr(ingest, "fetch_bcb_focus_12m", _empty_focus)
    monkeypatch.setattr(ingest, "_OECD_CPI_GEOS", ["USA", "GBR"])

    def fake_oecd(geo):
        if geo == "GBR":
            raise ValueError("boom")
        meta = dict(_META, series_id=f"OECD:CPI:{geo}", source="oecd")
        return meta, [(date(2025, 1, 1), 2.5)]

    monkeypatch.setattr(ingest, "fetch_oecd_cpi", fake_oecd)
    meta_debt = dict(_META, series_id="UST:DEBT", source="fiscaldata")
    monkeypatch.setattr(ingest, "fetch_fiscaldata_debt", lambda: (meta_debt, []))  # no data
    monkeypatch.setattr(ingest, "fetch_fiscaldata_avg_rates", lambda: [])

    conn = FakeConn(obs_results=[(False,)])
    result = run_ingest(conn)
    assert conn.autocommit is True  # per-statement commits are real commits (durability)

    by_id = {s["series_id"]: s for s in result["series"]}
    assert by_id["OECD:CPI:USA"] == {
        "series_id": "OECD:CPI:USA", "obs": 1, "restated": 0, "ok": True,
    }
    assert by_id["OECD:CPI:GBR"]["ok"] is False
    assert "boom" in by_id["OECD:CPI:GBR"]["error"]  # failure attributed to the right series
    assert by_id["UST:DEBT"] == {  # empty series: honest zero, not an error, not fabricated
        "series_id": "UST:DEBT", "obs": 0, "restated": 0, "ok": True,
    }
    assert result["total_obs"] == 1
    assert result["total_restated"] == 0

    # the end-of-run sweep still deletes obs-less catalog rows
    assert any("DELETE FROM macro.series" in sql for sql, _ in conn.calls)
