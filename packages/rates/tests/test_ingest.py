"""fill_curve — vintages, plausibility routing, and the tail-case desync gate. DB-free."""

from __future__ import annotations

import contextlib
from datetime import date

from rates.ingest import fill_curve
from rates.sources.boe import CurvePoint


class _Cur:
    def __init__(self, one=None, all_=None):
        self._one, self._all = one, all_ or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    """Dispatches by SQL marker. `insert_result` is what the upsert's RETURNING yields:
    (True,)=inserted, (False,)=restated, None=skipped (equal-value)."""

    def __init__(self, seed_prev=None, insert_result=(True,)):
        self.seed_prev = seed_prev or []
        self.insert_result = insert_result
        self.reviews: list = []
        self.inserts: list = []
        self.insert_sql: list[str] = []

    def execute(self, sql, params=None):
        if "curve_point_review" in sql:
            self.reviews.append(params)
            return _Cur(one=None)
        if "DISTINCT ON (curve_set" in sql:
            return _Cur(all_=self.seed_prev)
        if "INSERT INTO rates.curve_point" in sql:
            self.inserts.append(params)
            self.insert_sql.append(sql)
            return _Cur(one=self.insert_result)
        return _Cur()

    def transaction(self):
        return contextlib.nullcontext()


class _Source:
    SOURCE = "boe"

    def __init__(self, pts):
        self._pts = pts

    def fetch(self, *, start_date=None, end_date=None):
        return list(self._pts)


def _p(cs, b, rt, t, d, v):
    return CurvePoint(cs, b, rt, t, d, v)


def test_first_load_inserts_with_first_value_equal_to_value():
    d = date(2026, 6, 1)
    src = _Source([
        _p("glc", "nominal", "spot", 1.0, d, 4.1), _p("glc", "nominal", "spot", 2.0, d, 4.2),
    ])
    conn = _Conn(insert_result=(True,))
    s = fill_curve(conn, src, end_date=d)
    assert s.inserted == 2 and s.restated == 0 and s.flagged == 0
    assert {row["v"] for row in conn.inserts} == {4.1, 4.2}
    # value AND first_value bind the SAME param on insert (one published value → two vintages)
    assert all("%(v)s,%(v)s" in sql for sql in conn.insert_sql)


def test_restate_and_skip_paths():
    d = date(2026, 6, 1)
    src = _Source([_p("glc", "nominal", "spot", 1.0, d, 4.1)])
    assert fill_curve(_Conn(insert_result=(False,)), src, end_date=d).restated == 1
    assert fill_curve(_Conn(insert_result=None), src, end_date=d).skipped_existing == 1


def test_implausible_move_routes_to_review_not_store():
    d = date(2026, 6, 2)
    # seed: yesterday this tenor was 4.0; today it's 41.0 (decimal shift) → > 5pp band → review
    seed = [("glc", "nominal", "spot", 1.0, 4.0)]
    src = _Source([_p("glc", "nominal", "spot", 1.0, d, 41.0)])
    conn = _Conn(seed_prev=seed)
    s = fill_curve(conn, src, end_date=d)
    assert s.flagged == 1 and s.inserted == 0
    assert len(conn.reviews) == 1 and len(conn.inserts) == 0
    assert s.flagged_samples and "4.00->41.00" in s.flagged_samples[0]


def test_plausible_move_within_band_is_stored():
    d = date(2026, 6, 2)
    seed = [("glc", "nominal", "spot", 1.0, 4.0)]
    src = _Source([_p("glc", "nominal", "spot", 1.0, d, 4.3)])  # +0.3pp, fine
    conn = _Conn(seed_prev=seed)
    s = fill_curve(conn, src, end_date=d)
    assert s.flagged == 0 and s.inserted == 1


def test_tail_case_gates_a_desynced_day():
    # day A is complete (glc+ois); day B is missing ois → tail load skips B (desynced current day)
    a, b = date(2026, 6, 1), date(2026, 6, 2)
    pts = [
        _p("glc", "nominal", "spot", 1.0, a, 4.0), _p("ois", "nominal", "spot", 1.0, a, 3.9),
        _p("glc", "nominal", "spot", 1.0, b, 4.1),  # b has no ois
    ]
    conn = _Conn()
    s = fill_curve(conn, _Source(pts), end_date=b, start_date=None)  # tail
    assert s.gated_days == [b.isoformat()]
    assert s.inserted == 2  # only day A's two points landed


def test_backfill_inserts_partial_history():
    # same data, but an explicit start_date (backfill) → partial days are legit history, inserted
    a, b = date(2026, 6, 1), date(2026, 6, 2)
    pts = [
        _p("glc", "nominal", "spot", 1.0, a, 4.0), _p("ois", "nominal", "spot", 1.0, a, 3.9),
        _p("glc", "nominal", "spot", 1.0, b, 4.1),
    ]
    conn = _Conn()
    s = fill_curve(conn, _Source(pts), end_date=b, start_date=a)  # backfill
    assert s.gated_days == [] and s.inserted == 3
