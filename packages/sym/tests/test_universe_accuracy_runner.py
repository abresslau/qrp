"""Accuracy-gate runner + reverse CLI (Story U3.5, Tasks 4-5). DB-free.

Covers ``run_configured_accuracy_check`` (config validation, independence check,
proxy tolerance, FIGI-level cross-scheme fallback) and the ``sym universe
accuracy`` / ``sym universe reverse`` command wiring (args, exit codes).
"""

from __future__ import annotations

import contextlib
from datetime import date

import pytest

import sym.db
from sym.cli import main
from sym.universe import accuracy as accuracy_mod
from sym.universe.accuracy import run_configured_accuracy_check
from sym.universe.registry import JOIN, MembershipChange, UniverseError

D = date(2026, 6, 10)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, *, config=None, source_pref=("b3",), maintained=(),
                 figis=(), symbology=None):
        self.autocommit = False
        self._config = config or {}
        self._source_pref = list(source_pref)
        self._maintained = list(maintained)      # open raw_identifier tokens
        self._figis = list(figis)                # open composite_figis
        self._symbology = symbology or {}        # symbol_value -> composite_figi
        self.checks: list[tuple] = []            # universe_accuracy_check INSERTs
        self.events: list[tuple] = []            # membership_event INSERTs (reverse)
        self.rebuilt = 0

    def execute(self, sql, params=None):
        if "SELECT kind, config, source_pref FROM universe" in sql:
            return _Cur(one=("index", self._config, self._source_pref))
        if "SELECT DISTINCT raw_identifier" in sql and "universe_membership" in sql:
            return _Cur(rows=[(t,) for t in self._maintained])
        if "SELECT DISTINCT composite_figi" in sql and "universe_membership" in sql:
            return _Cur(rows=[(f,) for f in self._figis])
        if "INSERT INTO universe_accuracy_check" in sql:
            self.checks.append(params)
            return _Cur()
        if "security_symbology" in sql:
            values = params[1]  # candidates list
            for v in values:
                if v in self._symbology:
                    return _Cur(one=(self._symbology[v], None))
            return _Cur(one=None)
        if "FROM securities" in sql:
            return _Cur(one=None)
        if "INSERT INTO membership_event" in sql:
            self.events.append((params[1], params[2]))
            return _Cur(one=(len(self.events),))
        # reverse's resolve+rebuild traffic
        if "membership_event e" in sql:
            return _Cur(rows=[])
        if "count(DISTINCT e.raw_identifier)" in sql:
            return _Cur(one=(0,))
        if "DELETE FROM universe_membership" in sql:
            self.rebuilt += 1
            return _Cur()
        if "INSERT INTO universe_membership" in sql:
            return _Cur()
        raise AssertionError(sql)

    def transaction(self):
        return contextlib.nullcontext()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Source:
    def __init__(self, tokens):
        self._tokens = set(tokens)
        self.last_snapshot_tokens = None

    def fetch(self, index_key, start, end):
        self.last_snapshot_tokens = set(self._tokens)
        return [MembershipChange(t, JOIN, end, "ref") for t in sorted(self._tokens)]


def _patch_source(monkeypatch, tokens):
    monkeypatch.setattr(accuracy_mod, "get_index_source", lambda a, **cfg: _Source(tokens))


IBOV_CFG = {"index": "ibov", "accuracy_reference": "wikipedia"}


def test_unconfigured_reference_refuses():
    conn = _Conn(config={"index": "ibov"})
    with pytest.raises(UniverseError, match="accuracy_reference"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D)


def test_reference_same_as_primary_refuses():
    conn = _Conn(config={"index": "ibov", "accuracy_reference": "b3"}, source_pref=("b3",))
    with pytest.raises(UniverseError, match="independent"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D)


def test_matching_sets_pass_and_audit_row_written(monkeypatch):
    toks = ["ticker:PETR4@BVMF", "ticker:VALE3@BVMF"]
    conn = _Conn(config=IBOV_CFG, maintained=toks)
    _patch_source(monkeypatch, toks)
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.alarm is False and result.divergence == 0.0
    assert result.reference_source == "wikipedia"
    assert len(conn.checks) == 1  # audit row persisted


def test_divergence_alarms(monkeypatch):
    conn = _Conn(config=IBOV_CFG,
                 maintained=["ticker:A@BVMF", "ticker:B@BVMF", "ticker:C@BVMF",
                             "ticker:D@BVMF"])
    _patch_source(monkeypatch, ["ticker:A@BVMF"])
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.alarm is True and result.divergence == 0.75


def test_etf_reference_gets_proxy_tolerance(monkeypatch):
    cfg = {"index": "ibov", "accuracy_reference": "etf_holdings"}
    conn = _Conn(config=cfg, maintained=["ticker:A@BVMF"])
    _patch_source(monkeypatch, ["ticker:A@BVMF"])
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.threshold == pytest.approx(
        accuracy_mod.DEFAULT_THRESHOLD + accuracy_mod.DEFAULT_PROXY_TOLERANCE
    )


def test_cross_scheme_compares_on_figis(monkeypatch):
    # Maintained is ticker-tokenised, the reference emits isin: tokens. Naive token
    # comparison would diverge toward 1.0 regardless of truth — both sides must be
    # resolved to FIGIs first.
    conn = _Conn(
        config=IBOV_CFG,
        maintained=["ticker:PETR4@BVMF", "ticker:VALE3@BVMF"],
        figis=["BBG000000PET", "BBG000000VAL"],
        symbology={"BRPETRACNPR6": "BBG000000PET", "BRVALEACNOR0": "BBG000000VAL"},
    )
    _patch_source(monkeypatch, ["isin:BRPETRACNPR6", "isin:BRVALEACNOR0"])
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.divergence == 0.0 and result.alarm is False


def test_cross_scheme_unresolvable_reference_token_stays_divergent(monkeypatch):
    # An isin the local resolver can't map can't be corroborated — it must count
    # toward divergence, not silently vanish from the comparison.
    conn = _Conn(
        config=IBOV_CFG,
        maintained=["ticker:PETR4@BVMF"],
        figis=["BBG000000PET"],
        symbology={"BRPETRACNPR6": "BBG000000PET"},
    )
    _patch_source(monkeypatch, ["isin:BRPETRACNPR6", "isin:XXUNKNOWN0000"])
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.divergence > 0.0


def test_empty_reference_refuses(monkeypatch):
    conn = _Conn(config=IBOV_CFG, maintained=["ticker:A@BVMF"])

    class _Empty:
        last_snapshot_tokens = None

        def fetch(self, index_key, start, end):
            return []

    monkeypatch.setattr(accuracy_mod, "get_index_source", lambda a, **cfg: _Empty())
    with pytest.raises(UniverseError, match="no members"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D)


# --- CLI wiring ---------------------------------------------------------------


def test_cli_accuracy_exit_codes(monkeypatch, capsys):
    conn = _Conn(config=IBOV_CFG, maintained=["ticker:A@BVMF", "ticker:B@BVMF"])
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    _patch_source(monkeypatch, ["ticker:A@BVMF", "ticker:B@BVMF"])
    assert main(["universe", "accuracy", "ibov"]) == 0
    assert "ok" in capsys.readouterr().out

    _patch_source(monkeypatch, ["ticker:Z@BVMF"])
    assert main(["universe", "accuracy", "ibov"]) == 2  # alarm
    assert "ALARM" in capsys.readouterr().out


def test_cli_accuracy_unconfigured_is_error(monkeypatch, capsys):
    conn = _Conn(config={"index": "ibov"})
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    assert main(["universe", "accuracy", "ibov"]) == 1
    assert "accuracy_reference" in capsys.readouterr().err


def test_cli_accuracy_threshold_flag(monkeypatch, capsys):
    conn = _Conn(config=IBOV_CFG,
                 maintained=["ticker:A@BVMF", "ticker:B@BVMF", "ticker:C@BVMF"])
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    _patch_source(monkeypatch, ["ticker:A@BVMF", "ticker:B@BVMF"])  # div = 1/3
    assert main(["universe", "accuracy", "ibov", "--threshold", "0.5"]) == 0
    capsys.readouterr()
    assert main(["universe", "accuracy", "ibov", "--threshold", "0.1"]) == 2


def test_cli_reverse_appends_and_rebuilds(monkeypatch, capsys):
    conn = _Conn()
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    rc = main(["universe", "reverse", "ibov", "ticker:B@BVMF", "leave", "2026-06-10"])
    assert rc == 0
    assert ("ticker:B@BVMF", "correct") in conn.events
    assert conn.rebuilt == 1
    assert "reversed" in capsys.readouterr().out


def test_cli_reverse_bad_date_is_error(monkeypatch, capsys):
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn())
    rc = main(["universe", "reverse", "ibov", "ticker:B@BVMF", "leave", "not-a-date"])
    assert rc == 1
    assert "effective_date" in capsys.readouterr().err
