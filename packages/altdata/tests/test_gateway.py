"""Gateway tests for altdata — fake conn asserting the window-rate SQL and shaping."""

from __future__ import annotations

from datetime import date

from altdata.gateway import _SERIES_SQL, DbAltdataGateway


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, results):
        # results: list of row-lists, popped per execute call
        self._results = list(results)
        self.calls: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor(self._results.pop(0))


def test_series_sql_rates_are_calendar_day_sums_with_source_anchors():
    # the honest-rate claim: sum over the trailing window / window DAYS. The anchor follows
    # the source's missing-day semantics — true-zero counts (sec_edgar) anchor on TODAY
    # with NULL→0 (an idle filer decays to 0 instead of a perpetual 30/7 spike from
    # self-anchoring); lag-shaped series (wikipedia) anchor on their own latest obs_date.
    assert "/ 7.0" in _SERIES_SQL and "/ 30.0" in _SERIES_SQL
    assert "WHEN b.source = 'sec_edgar' THEN CURRENT_DATE ELSE b.last_date END" in _SERIES_SQL
    assert "coalesce(sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 7), 0)" in _SERIES_SQL
    assert "coalesce(sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 30), 0)" in _SERIES_SQL
    assert "max(obs_date) AS last_date" in _SERIES_SQL
    assert "GROUP BY 1, 2, 3" in _SERIES_SQL  # per (figi, source, metric), not global


def test_series_shapes_rows_and_computes_spike():
    rows = [
        ("FIGI_A0000000", "AAPL", "Apple", "wikipedia", "pageviews", "Apple_Inc.", "views",
         121, date(2026, 6, 5), 14630.0, 10360.8, 9958.2),
        ("FIGI_A0000000", "AAPL", "Apple", "sec_edgar", "filings_form4", "0000320193",
         "filings", 12, date(2026, 5, 29), 3.0, 0.428, 0.4),
        # zero 30d rate: spike must be None, not a division error
        ("FIGI_B0000000", "KO", "Coca-Cola", "sec_edgar", "filings_8k", "0000021344",
         "filings", 2, date(2026, 1, 2), 1.0, None, 0.0),
    ]
    gw = DbAltdataGateway(FakeConn([rows]))
    out = gw.series()
    assert out[0]["source"] == "wikipedia"
    assert out[0]["detail"] == "Apple_Inc."  # provenance surfaced
    assert out[0]["as_of_date"] == "2026-06-05"
    assert abs(out[0]["attention_spike"] - 10360.8 / 9958.2) < 1e-9
    assert out[1]["metric"] == "filings_form4"
    assert out[1]["latest_value"] == 3.0
    assert out[2]["attention_spike"] is None


def test_observations_keys_by_figi_source_metric():
    meta = ("FIGI_A0000000", "AAPL", "Apple", "sec_edgar", "filings_form4", "0000320193",
            "filings")
    obs = [(date(2026, 5, 28), 1.0), (date(2026, 5, 29), 3.0)]
    conn = FakeConn([[meta], obs])
    out = DbAltdataGateway(conn).observations("FIGI_A0000000", "sec_edgar", "filings_form4")
    assert out["observations"] == [
        {"obs_date": "2026-05-28", "value": 1.0},
        {"obs_date": "2026-05-29", "value": 3.0},
    ]
    # both queries carry the full series key
    for _sql, params in conn.calls:
        assert params == ("FIGI_A0000000", "sec_edgar", "filings_form4")


def test_observations_missing_series_returns_none():
    conn = FakeConn([[]])
    assert DbAltdataGateway(conn).observations("FIGI_X0000000", "wikipedia", "pageviews") is None
