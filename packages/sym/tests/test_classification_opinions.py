"""Opinion-store SCD writer + run_opinion_matrix — DB-free stateful fake conn."""

from __future__ import annotations

import contextlib
from datetime import date

from sym.classification.gics import GicsClassification


def _op(figi, sector, source, ig=None, ind=None, sub=None):
    return GicsClassification(
        composite_figi=figi, sector_name=sector, industry_group_name=ig,
        industry_name=ind, sub_industry_name=sub, source=source,
    )


class _Cur:
    def __init__(self, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class _OpinionConn:
    """Stateful fake for gics_source_opinion: one effective row per (figi, source)."""

    def __init__(self):
        self.effective: dict[tuple[str, str], tuple] = {}  # (figi, source) -> (levels, valid_from)

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT") and "FROM gics_source_opinion" in s:
            figi, source = params[0], params[1]
            row = self.effective.get((figi, source))
            return _Cur(one=(*row[0], row[1]) if row else None)
        if s.startswith("UPDATE") and "SET valid_to" in s:
            _vt, figi, source = params
            self.effective.pop((figi, source), None)
            return _Cur()
        if s.startswith("UPDATE") and "SET sector_code" in s:  # in-place
            levels = (params[1], params[3], params[5], params[7])
            figi, source = params[8], params[9]
            vf = self.effective[(figi, source)][1]
            self.effective[(figi, source)] = (levels, vf)
            return _Cur()
        if s.startswith("INSERT INTO gics_source_opinion"):
            figi, source = params[0], params[1]
            levels = (params[3], params[5], params[7], params[9])
            self.effective[(figi, source)] = (levels, params[10])
            return _Cur()
        raise AssertionError(f"unexpected SQL: {s[:80]}")

    def transaction(self):
        return contextlib.nullcontext()


def _apply(conn, plans, d):
    from sym.classification.opinions import apply_source_opinions

    return apply_source_opinions(conn, plans, as_of_date=d)


def test_insert_then_unchanged_then_change():
    conn = _OpinionConn()
    s1 = _apply(conn, [_op("F1", "Energy", "wikidata")], date(2026, 6, 1))
    assert s1.rows_inserted == 1 and conn.effective[("F1", "wikidata")][0][0] == "Energy"

    # re-apply identical → unchanged no-op
    s2 = _apply(conn, [_op("F1", "Energy", "wikidata")], date(2026, 6, 2))
    assert s2.unchanged == 1 and s2.rows_inserted == 0

    # change on a later day → close + insert
    s3 = _apply(conn, [_op("F1", "Utilities", "wikidata")], date(2026, 6, 3))
    assert s3.rows_closed == 1 and s3.rows_inserted == 1
    assert conn.effective[("F1", "wikidata")][0][0] == "Utilities"


def test_same_day_change_updates_in_place():
    conn = _OpinionConn()
    _apply(conn, [_op("F1", "Energy", "wikidata")], date(2026, 6, 1))
    s = _apply(conn, [_op("F1", "Materials", "wikidata")], date(2026, 6, 1))  # same day
    assert s.rows_updated == 1 and s.rows_closed == 0 and s.rows_inserted == 0
    assert conn.effective[("F1", "wikidata")][0][0] == "Materials"


def test_multiple_sources_coexist_for_one_company():
    conn = _OpinionConn()
    _apply(conn, [_op("F1", "Information Technology", "financedatabase")], date(2026, 6, 1))
    _apply(conn, [_op("F1", "Information Technology", "wikidata")], date(2026, 6, 1))
    _apply(conn, [_op("F1", "Consumer Discretionary", "google")], date(2026, 6, 1))
    # all three sources hold an effective opinion of F1 at once — the whole point of the matrix
    assert set(conn.effective) == {("F1", "financedatabase"), ("F1", "wikidata"), ("F1", "google")}
    assert conn.effective[("F1", "google")][0][0] == "Consumer Discretionary"


# --- run_opinion_matrix orchestrator ---------------------------------------------------


def test_run_opinion_matrix_runs_gated_sources_and_isolates_errors(monkeypatch):
    import sym.classification.registry as reg
    from sym.classification.gics import SecurityIdentity

    monkeypatch.setattr(
        reg, "read_active_identities", lambda conn: [SecurityIdentity("F1", ticker="X")]
    )

    def _fake_apply(conn, plans):
        return reg.OpinionSummary(
            source=(plans[0].source if plans else ""),
            classified=len(plans),
            rows_inserted=len(plans),
        )

    monkeypatch.setattr(reg, "apply_source_opinions", _fake_apply)

    class _Ok:
        source = "ok"

        def fetch(self, ids):
            return {i.composite_figi: _op(i.composite_figi, "Energy", "ok") for i in ids}

    class _Boom:
        def fetch(self, ids):
            raise RuntimeError("source down")

    monkeypatch.setattr(
        reg, "_opinion_specs",
        lambda *, llm_enabled: [
            ("ok", _Ok, None, ""),
            ("boom", _Boom, None, ""),
            ("keyed", _Ok, (lambda: False), "keyed: skipped — no key"),
        ],
    )
    results = reg.run_opinion_matrix(object(), llm_enabled=False)
    by = {r.name: r for r in results}
    assert by["ok"].summary is not None and by["ok"].summary.rows_inserted == 1
    assert by["boom"].error is not None and "source down" in by["boom"].error  # isolated
    assert by["keyed"].skipped and "no key" in by["keyed"].skip_line
