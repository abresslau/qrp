"""Symbology SCD transitions (Story 1.10, chunk-4 D2). DB-free.

A stateful fake models the security_symbology table so the close/insert/in-place
logic is asserted BEHAVIORALLY: a rename closes the old row at the new row's
valid_from (boundary day belongs to the successor — data-conventions §4), a
same-day rename updates in place (the valid_to > valid_from CHECK forbids
close+insert), and collisions still refuse loudly.
"""

from __future__ import annotations

from datetime import date

import pytest

from sym.identity.symbology import (
    SymbologyCollisionError,
    SymbologyTransitionError,
    write_security,
)
from sym.identity.universe import SeedSecurity
from sym.validate.symbology import check_symbology_transitions

D0, D1 = date(2025, 1, 2), date(2025, 7, 23)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows if rows is not None else []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    """Models exchange, securities, and security_symbology as in-memory state."""

    def __init__(self, symbology=None, securities=None):
        # symbology rows: dict(figi, type, value, mic, valid_from, valid_to)
        self.symbology = symbology or []
        self.securities = securities or set()

    def _open(self, **match):
        return [r for r in self.symbology
                if r["valid_to"] is None
                and all(r[k] == v for k, v in match.items())]

    def execute(self, sql, params=None):
        if "FROM exchange" in sql:
            return _Cur(one=("USD", "US"))
        if "INSERT INTO securities" in sql:
            figi = params[0]
            if figi in self.securities:
                return _Cur(one=None)
            self.securities.add(figi)
            return _Cur(one=(figi,))
        if "SELECT composite_figi FROM security_symbology" in sql:
            # collision/holder probe by (type, value, mic)
            t, v, mic = params
            holders = self._open(type=t, value=v, mic=mic)
            return _Cur(one=(holders[0]["figi"],) if holders else None)
        if "SELECT symbol_value, mic, valid_from FROM security_symbology" in sql:
            figi, t = params
            return _Cur(rows=[(r["value"], r["mic"], r["valid_from"])
                              for r in self._open(figi=figi, type=t)])
        if "UPDATE security_symbology" in sql and "SET symbol_value" in sql:
            # in-place rewrite, keyed by the OLD (value, mic)
            new_value, new_mic, _country, figi, t, old_value, old_mic = params
            hit = self._open(figi=figi, type=t, value=old_value, mic=old_mic)
            for r in hit:
                r["value"], r["mic"] = new_value, new_mic
            return _Cur(rows=[(1,)] * len(hit))
        if "UPDATE security_symbology" in sql and "SET valid_to" in sql:
            # precise per-row close, keyed by (value, mic)
            valid_to, figi, t, old_value, old_mic = params
            closed = self._open(figi=figi, type=t, value=old_value, mic=old_mic)
            for r in closed:
                r["valid_to"] = valid_to
            return _Cur(rows=[(1,)] * len(closed))
        if "INSERT INTO security_symbology" in sql:
            figi, t, v, mic, _country, vf = params
            self.symbology.append(
                dict(figi=figi, type=t, value=v, mic=mic, valid_from=vf, valid_to=None))
            return _Cur()
        raise AssertionError(sql)

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()


def _seed(ticker, mic="XNYS", isin=None):
    return SeedSecurity("Block Inc", "test", ticker, mic, isin, None)


def _write(conn, ticker="XYZ", figi="BBG0018SLC07", valid_from=D1, **kw):
    return write_security(conn, seed=_seed(ticker, **kw), composite_figi=figi,
                          share_class_figi=None, valid_from=valid_from)


def test_rename_closes_old_row_and_opens_new():
    # The §4 worked example: SQ open since D0; rename to XYZ at D1.
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="ticker", value="SQ",
                                 mic="XNYS", valid_from=D0, valid_to=None)],
                 securities={"BBG0018SLC07"})
    _write(conn, "XYZ")
    sq = next(r for r in conn.symbology if r["value"] == "SQ")
    xyz = next(r for r in conn.symbology if r["value"] == "XYZ")
    assert sq["valid_to"] == D1          # exclusive end — D1 belongs to XYZ
    assert xyz["valid_from"] == D1 and xyz["valid_to"] is None
    assert len(conn._open(type="ticker")) == 1


def test_same_day_rename_updates_in_place():
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="ticker", value="SQ",
                                 mic="XNYS", valid_from=D1, valid_to=None)],
                 securities={"BBG0018SLC07"})
    _write(conn, "XYZ", valid_from=D1)
    assert len(conn.symbology) == 1      # no close+insert
    assert conn.symbology[0]["value"] == "XYZ"
    assert conn.symbology[0]["valid_to"] is None


def test_isin_change_transitions_too():
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="isin", value="US0000OLD000",
                                 mic=None, valid_from=D0, valid_to=None)],
                 securities={"BBG0018SLC07"})
    _write(conn, "XYZ", isin="US0000NEW000")
    old = next(r for r in conn.symbology if r["value"] == "US0000OLD000")
    assert old["valid_to"] == D1
    assert len(conn._open(type="isin")) == 1


def test_collision_still_refuses_and_changes_nothing():
    conn = _Conn(symbology=[
        dict(figi="BBG0018SLC07", type="ticker", value="SQ", mic="XNYS",
             valid_from=D0, valid_to=None),
        dict(figi="BBG000OTHER0", type="ticker", value="XYZ", mic="XNYS",
             valid_from=D0, valid_to=None),
    ], securities={"BBG0018SLC07", "BBG000OTHER0"})
    with pytest.raises(SymbologyCollisionError):
        _write(conn, "XYZ")
    sq = next(r for r in conn.symbology if r["value"] == "SQ")
    assert sq["valid_to"] is None        # old row untouched


def test_identical_rerun_is_noop():
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="ticker", value="XYZ",
                                 mic="XNYS", valid_from=D0, valid_to=None)],
                 securities={"BBG0018SLC07"})
    _write(conn, "XYZ")
    assert len(conn.symbology) == 1
    assert conn.symbology[0]["valid_from"] == D0    # untouched


def test_mic_change_is_a_transition():
    # Relisting XNYS -> XNAS: same value, different mic — still one open row after.
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="ticker", value="XYZ",
                                 mic="XNYS", valid_from=D0, valid_to=None)],
                 securities={"BBG0018SLC07"})
    _write(conn, "XYZ", mic="XNAS")
    assert len(conn._open(type="ticker")) == 1
    assert conn._open(type="ticker")[0]["mic"] == "XNAS"


def test_backdated_write_refuses_and_changes_nothing():
    # An open row NEWER than the incoming valid_from can be neither rewritten nor
    # closed (the CHECK forbids valid_to <= valid_from) — silent acceptance would
    # mint exactly the duplicate-open state the audit check exists to catch.
    conn = _Conn(symbology=[dict(figi="BBG0018SLC07", type="ticker", value="XYZ",
                                 mic="XNYS", valid_from=D1, valid_to=None)],
                 securities={"BBG0018SLC07"})
    with pytest.raises(SymbologyTransitionError, match="backdated"):
        _write(conn, "ABC", valid_from=D0)
    assert len(conn.symbology) == 1 and conn.symbology[0]["value"] == "XYZ"


def test_noop_path_still_sweeps_pre_existing_drift():
    # Pre-1.10 drift: SQ and XYZ both open. A routine re-run of the CURRENT value
    # (XYZ) — the most likely live write — must still close the stale SQ row.
    later = date(2025, 8, 1)
    conn = _Conn(symbology=[
        dict(figi="BBG0018SLC07", type="ticker", value="SQ", mic="XNYS",
             valid_from=D0, valid_to=None),
        dict(figi="BBG0018SLC07", type="ticker", value="XYZ", mic="XNYS",
             valid_from=D1, valid_to=None),
    ], securities={"BBG0018SLC07"})
    _write(conn, "XYZ", valid_from=later)
    sq = next(r for r in conn.symbology if r["value"] == "SQ")
    xyz = next(r for r in conn.symbology if r["value"] == "XYZ")
    assert sq["valid_to"] == later
    assert xyz["valid_to"] is None and xyz["valid_from"] == D1  # survivor untouched
    assert len(conn._open(type="ticker")) == 1


def test_same_day_drift_refuses():
    # Two differing opens sharing the new valid_from: a blind in-place UPDATE
    # would rewrite BOTH to identical rows (EXCLUDE violation) — refuse instead.
    conn = _Conn(symbology=[
        dict(figi="BBG0018SLC07", type="ticker", value="AAA", mic="XNYS",
             valid_from=D1, valid_to=None),
        dict(figi="BBG0018SLC07", type="ticker", value="BBB", mic="XNYS",
             valid_from=D1, valid_to=None),
    ], securities={"BBG0018SLC07"})
    with pytest.raises(SymbologyTransitionError, match="duplicate-open"):
        _write(conn, "CCC", valid_from=D1)


def test_bridge_isolates_collision_per_member(monkeypatch):
    from sym.universe import ingest as ingest_mod
    from sym.universe.ingest import ensure_universe_securities

    class _BridgeConn:
        autocommit = False

        def execute(self, sql, params=None):
            return _Cur(rows=[("ticker:AAA@XNAS", "BBG000000AA1", None),
                              ("ticker:BBB@XNAS", "BBG000000BB1", None)])

        def transaction(self):
            import contextlib

            return contextlib.nullcontext()

    calls = []

    def fake_write(conn, *, seed, composite_figi, share_class_figi):
        calls.append(seed.ticker)
        if seed.ticker == "AAA":
            raise SymbologyCollisionError("recycled")
        return True

    monkeypatch.setattr(ingest_mod, "write_security", fake_write)
    summary = ensure_universe_securities(_BridgeConn(), "u")
    assert calls == ["AAA", "BBB"]          # the collision did not abort the loop
    assert summary.skipped_collision == 1 and summary.created == 1


# --- the V3 audit check ---------------------------------------------------------


class _CheckConn:
    def __init__(self, dup_rows=(), orphan_rows=(), overlap_rows=(), total=2199):
        self._dup, self._orphan = list(dup_rows), list(orphan_rows)
        self._overlap, self._total = list(overlap_rows), total

    def execute(self, sql, params=None):
        if "count(*) FROM security_symbology" in sql:
            return _Cur(one=(self._total,))
        if "HAVING count(*) > 1" in sql:
            return _Cur(rows=self._dup)
        if "daterange" in sql:
            return _Cur(rows=self._overlap)
        if "NOT EXISTS" in sql:
            return _Cur(rows=self._orphan)
        raise AssertionError(sql)


def test_check_flags_duplicate_open_rows():
    result = check_symbology_transitions(_CheckConn(dup_rows=[("BBG0018SLC07", "ticker", 2)]))
    assert result.status == "fail"
    assert any("2 open" in s for s in result.samples)


def test_check_flags_overlapping_ranges():
    # The remaining half of the V3 overlap AC: closed/open ranges of one
    # (figi, type) overlapping each other.
    result = check_symbology_transitions(
        _CheckConn(overlap_rows=[("BBG0018SLC07", "ticker")]))
    assert result.status == "fail"
    assert any("overlap" in s for s in result.samples)


def test_check_warns_closed_without_successor():
    result = check_symbology_transitions(
        _CheckConn(orphan_rows=[("BBG0018SLC07", "ticker", "SQ", D1)]))
    assert result.status == "warn"


def test_check_clean_passes_with_real_denominator():
    result = check_symbology_transitions(_CheckConn(total=2199))
    assert result.status == "pass"
    assert result.checked == 2199  # rows scanned, not offender count
