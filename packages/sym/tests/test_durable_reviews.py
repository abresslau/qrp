"""Durable review surfaces (Story S.1). DB-free.

Per-flag-type price reviews (audit + ingest flags coexist) and persistent FX
rejections with the accept-un-wedges-band resolution flow.
"""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

import pytest
from fx.review import FxReviewError, list_fx_reviews, resolve_fx_review

D = date(2026, 6, 10)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


# --- prices_review per-flag conflict keys -----------------------------------------


def test_both_writers_upsert_on_the_three_column_key():
    # The clobber fix is the conflict target: (figi, date, TYPE). Both writers'
    # SQL must carry it, and neither may overwrite flag_type on conflict.
    import inspect

    from sym.ingest import pipeline, prices

    audit_src = inspect.getsource(pipeline)
    ingest_src = inspect.getsource(prices)
    for src in (audit_src, ingest_src):
        assert "ON CONFLICT (composite_figi, session_date, flag_type)" in src
    for src in (audit_src, ingest_src):
        assert "flag_type = EXCLUDED.flag_type" not in src


def test_resolve_review_can_target_one_flag_type():
    from sym.ingest.prices import resolve_review

    class _Conn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, list(params)))
            return _Cur(one=("BBG000000001",))

    conn = _Conn()
    resolve_review(conn, "BBG000000001", D, resolution="confirmed",
                   flag_type="price_jump")
    sql, params = conn.calls[0]
    assert "flag_type = %s" in sql and "price_jump" in params


def test_resolve_review_refuses_ambiguity_and_unknown_types():
    from sym.ingest.prices import resolve_review

    class _Multi:
        def __init__(self, open_count):
            self._n = open_count
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append(sql)
            if "count(*)" in sql:
                return _Cur(one=(self._n,))
            return _Cur(one=("BBG000000001",))

    # >1 open flags without a type: one verdict would clobber-by-resolution
    with pytest.raises(ValueError, match="pass flag_type"):
        resolve_review(_Multi(2), "BBG000000001", D, resolution="confirmed")
    # single open flag: the no-type default still works
    assert resolve_review(_Multi(1), "BBG000000001", D, resolution="rejected")
    # typo'd type is loud, not a silent False
    with pytest.raises(ValueError, match="unknown flag_type"):
        resolve_review(_Multi(1), "BBG000000001", D, resolution="confirmed",
                       flag_type="price_jmp")


# --- fx rejection persistence ------------------------------------------------------


def test_load_fx_persists_both_rejection_kinds():
    from fx.ingest import load_fx

    class _Src:
        SOURCE = "frankfurter"

        def fetch(self, ccys, start, end):
            from fx.ingest import FxObservation

            return [
                FxObservation("BRL", D, Decimal("-1")),          # non_positive
                FxObservation("BRL", date(2026, 6, 11), Decimal("99")),  # band (no prev)
            ]

    class _Conn:
        autocommit = False

        def __init__(self):
            self.rejections, self.inserted = [], []

        def execute(self, sql, params=None):
            if "INSERT INTO fx.fx_rate_review" in sql:
                self.rejections.append(params)
                return _Cur()
            if "SELECT 1 FROM fx.fx_rate_review" in sql:
                return _Cur(one=None)                # drain gate: no open rejections
            if "SELECT rate FROM fx.fx_rate" in sql:
                return _Cur(one=(Decimal("5.0"),))   # prior rate seeds the band
            if "INSERT INTO fx.fx_rate" in sql:
                self.inserted.append(params)
                return _Cur(one=("BRL",))
            raise AssertionError(sql)

    conn = _Conn()
    summary = load_fx(conn, _Src(), start_date=D, end_date=date(2026, 6, 11),
                      currencies=["BRL"])
    assert summary.implausible == 2 and conn.inserted == []
    reasons = {r[-1] for r in conn.rejections}
    assert reasons == {"non_positive", "band_exceeded"}
    band_row = next(r for r in conn.rejections if r[-1] == "band_exceeded")
    assert band_row[3] == Decimal("5.0")             # prior_rate recorded
    assert band_row[4] is not None                   # relative_move recorded


def test_accept_inserts_rate_and_closes():
    class _Conn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "FROM fx.fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("BRL", D, Decimal("9.99"), "frankfurter",
                                 "band_exceeded", False))
            if "INSERT INTO fx.fx_rate" in sql:
                return _Cur(one=("BRL",))
            if "UPDATE fx.fx_rate_review" in sql:
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    conn = _Conn()
    assert resolve_fx_review(conn, 4, accept=True) == ("accepted", True)
    fx_inserts = [p for sql, p in conn.calls
                  if "INSERT INTO fx.fx_rate" in sql and "review" not in sql]
    assert fx_inserts and fx_inserts[0][2] == Decimal("9.99")
    closes = [sql for sql, _ in conn.calls if "UPDATE fx.fx_rate_review" in sql]
    assert closes and "NOT reviewed" in closes[0]    # concurrent-close guard


def test_reject_closes_without_inserting():
    class _Conn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "FROM fx.fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("BRL", D, Decimal("9.99"), "frankfurter",
                                 "band_exceeded", False))
            if "UPDATE fx.fx_rate_review" in sql:
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    conn = _Conn()
    assert resolve_fx_review(conn, 4, accept=False) == ("rejected", False)
    assert not any("INSERT INTO fx.fx_rate" in sql and "review" not in sql
                   for sql, _ in conn.calls)


def test_resolve_guards_unknown_and_already_resolved():
    class _Conn:
        def __init__(self, row):
            self._row = row

        def execute(self, sql, params=None):
            return _Cur(one=self._row)

        def transaction(self):
            return contextlib.nullcontext()

    with pytest.raises(FxReviewError, match="no fx review row"):
        resolve_fx_review(_Conn(None), 999, accept=True)
    with pytest.raises(FxReviewError, match="already resolved"):
        resolve_fx_review(
            _Conn(("BRL", D, Decimal("1"), "frankfurter", "band_exceeded", True)),
            4, accept=True)


def test_list_fx_reviews_open_only_by_default():
    class _Conn:
        def __init__(self):
            self.sqls = []

        def execute(self, sql, params=None):
            self.sqls.append(sql)
            return _Cur(rows=[])

    conn = _Conn()
    list_fx_reviews(conn)
    assert "WHERE NOT reviewed" in conn.sqls[0]
    conn2 = _Conn()
    list_fx_reviews(conn2, include_resolved=True)
    assert "WHERE NOT reviewed" not in conn2.sqls[0]


def test_fx_coverage_warns_on_open_rejections():
    from datetime import date as _d

    from sym.validate.fx import check_fx_coverage
    from test_fx_coverage import _Conn as _CovConn

    cov = _CovConn(["BRL"], 10, {"BRL": (_d(2026, 6, 10), Decimal("5.0"))},
                   open_rejections=3)  # one fake serves both the sym + fx reads
    r = check_fx_coverage(cov, cov, as_of_date=_d(2026, 6, 10))
    assert r.status == "warn"
    assert any("3 open FX rejection" in s for s in r.samples)


def test_accept_honest_when_rate_already_stored():
    # live-proven review finding: ON CONFLICT no-op must NOT report insertion.
    class _Conn:
        def execute(self, sql, params=None):
            if "FROM fx.fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("BRL", D, Decimal("9.99"), "frankfurter",
                                 "band_exceeded", False))
            if "INSERT INTO fx.fx_rate" in sql:
                return _Cur(one=None)            # conflict: a rate already exists
            if "UPDATE fx.fx_rate_review" in sql:
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    assert resolve_fx_review(_Conn(), 4, accept=True) == ("accepted", False)


def test_accept_refuses_non_positive():
    class _Conn:
        def execute(self, sql, params=None):
            return _Cur(one=("BRL", D, Decimal("-1"), "frankfurter",
                             "non_positive", False))

        def transaction(self):
            return contextlib.nullcontext()

    with pytest.raises(FxReviewError, match="non-positive"):
        resolve_fx_review(_Conn(), 4, accept=True)


def test_accept_insert_failure_is_typed_and_row_stays_open():
    # regression for the gap found in the S.1 live test (currency FK).
    import psycopg

    class _Conn:
        def __init__(self):
            self.closed = []

        def execute(self, sql, params=None):
            if "FROM fx.fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("ZZZ", D, Decimal("9.99"), "frankfurter",
                                 "band_exceeded", False))
            if "INSERT INTO fx.fx_rate" in sql:
                raise psycopg.errors.ForeignKeyViolation("currency missing")
            if "UPDATE fx.fx_rate_review" in sql:
                self.closed.append(params)
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    conn = _Conn()
    with pytest.raises(FxReviewError, match="cannot accept"):
        resolve_fx_review(conn, 4, accept=True)
    assert conn.closed == []                     # the row was NOT closed


def test_load_fx_supersedes_moot_rejections():
    # The drain: a successful insert for a key with an open rejection closes it.
    from fx.ingest import load_fx

    class _Src:
        SOURCE = "frankfurter"

        def fetch(self, ccys, start, end):
            from fx.ingest import FxObservation

            return [FxObservation("BRL", D, Decimal("5.1"))]

    class _Conn:
        autocommit = False

        def __init__(self):
            self.superseded = []

        def execute(self, sql, params=None):
            if "SELECT 1 FROM fx.fx_rate_review" in sql:
                return _Cur(one=(1,))            # open rejections exist for BRL
            if "SELECT rate FROM fx.fx_rate" in sql:
                return _Cur(one=(Decimal("5.0"),))
            if "INSERT INTO fx.fx_rate " in sql:
                return _Cur(one=("BRL",))        # insert lands
            if "UPDATE fx.fx_rate_review" in sql and "superseded" in sql:
                self.superseded.append(params)
                return _Cur()
            raise AssertionError(sql)

    conn = _Conn()
    load_fx(conn, _Src(), start_date=D, end_date=D, currencies=["BRL"])
    assert len(conn.superseded) == 1
    assert conn.superseded[0][0] == "BRL" and conn.superseded[0][1] == D
