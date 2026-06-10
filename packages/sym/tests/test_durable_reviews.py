"""Durable review surfaces (Story S.1). DB-free.

Per-flag-type price reviews (audit + ingest flags coexist) and persistent FX
rejections with the accept-un-wedges-band resolution flow.
"""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal

import pytest

from sym.fx.review import FxReviewError, list_fx_reviews, resolve_fx_review

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
    assert "SET flag_type = EXCLUDED.flag_type" not in audit_src
    assert "flag_type = EXCLUDED.flag_type" not in ingest_src


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
    # default keeps the pre-S.1 resolve-all-at-date behavior
    conn2 = _Conn()
    resolve_review(conn2, "BBG000000001", D, resolution="rejected")
    assert "flag_type" not in conn2.calls[0][0]


def test_gate_reader_is_distinct():
    import inspect

    from sym.returns import loader

    assert "SELECT DISTINCT session_date FROM prices_review" in inspect.getsource(loader)


# --- fx rejection persistence ------------------------------------------------------


def test_load_fx_persists_both_rejection_kinds():
    from sym.fx.ingest import load_fx

    class _Src:
        SOURCE = "frankfurter"

        def fetch(self, ccys, start, end):
            from sym.fx.ingest import FxObservation

            return [
                FxObservation("BRL", D, Decimal("-1")),          # non_positive
                FxObservation("BRL", date(2026, 6, 11), Decimal("99")),  # band (no prev)
            ]

    class _Conn:
        autocommit = False

        def __init__(self):
            self.rejections, self.inserted = [], []

        def execute(self, sql, params=None):
            if "INSERT INTO fx_rate_review" in sql:
                self.rejections.append(params)
                return _Cur()
            if "SELECT rate FROM fx_rate" in sql:
                return _Cur(one=(Decimal("5.0"),))   # prior rate seeds the band
            if "INSERT INTO fx_rate" in sql:
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
            if "FROM fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("BRL", D, Decimal("9.99"), "frankfurter", False))
            if "INSERT INTO fx_rate " in sql or "INSERT INTO fx_rate\n" in sql:
                return _Cur()
            if "UPDATE fx_rate_review" in sql:
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    conn = _Conn()
    assert resolve_fx_review(conn, 4, accept=True) == "accepted"
    fx_inserts = [p for sql, p in conn.calls if "INSERT INTO fx_rate (" in sql]
    assert fx_inserts and fx_inserts[0][2] == Decimal("9.99")
    closes = [sql for sql, _ in conn.calls if "UPDATE fx_rate_review" in sql]
    assert closes and "NOT reviewed" in closes[0]    # concurrent-close guard


def test_reject_closes_without_inserting():
    class _Conn:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "FROM fx_rate_review WHERE review_id" in sql:
                return _Cur(one=("BRL", D, Decimal("9.99"), "frankfurter", False))
            if "UPDATE fx_rate_review" in sql:
                return _Cur(one=(4,))
            return _Cur()

        def transaction(self):
            return contextlib.nullcontext()

    conn = _Conn()
    assert resolve_fx_review(conn, 4, accept=False) == "rejected"
    assert not any("INSERT INTO fx_rate (" in sql for sql, _ in conn.calls)


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
        resolve_fx_review(_Conn(("BRL", D, Decimal("1"), "frankfurter", True)), 4,
                          accept=True)


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

    from tests.test_fx_coverage import _Conn as _CovConn

    from sym.validate.fx import check_fx_coverage

    r = check_fx_coverage(
        _CovConn(["BRL"], 10, {"BRL": (_d(2026, 6, 10), Decimal("5.0"))},
                 open_rejections=3),
        as_of_date=_d(2026, 6, 10),
    )
    assert r.status == "warn"
    assert any("3 open FX rejection" in s for s in r.samples)
