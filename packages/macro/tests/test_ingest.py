"""Upsert/restatement + summary-attribution tests for macro.ingest — fake conn, no DB."""

from __future__ import annotations

from datetime import date

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
    "unit": "u", "frequency": "monthly",
}


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
