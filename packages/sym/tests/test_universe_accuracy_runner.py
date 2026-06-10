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
        self.event_exists = True                 # answer for reverse's existence guard
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
        if "SELECT 1 FROM membership_event" in sql:
            return _Cur(one=(1,) if self.event_exists else None)
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


def test_reference_in_fallback_pref_refuses():
    # A fallback archetype can SERVE the universe during a primary outage — a
    # reference anywhere in source_pref corroborates nothing.
    conn = _Conn(config={"index": "ibov", "accuracy_reference": "wikipedia"},
                 source_pref=("b3", "wikipedia"))
    with pytest.raises(UniverseError, match="independent"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D)


def test_reference_fetch_failure_is_universe_error(monkeypatch):
    class _Boom:
        def fetch(self, index_key, start, end):
            raise ValueError("garbled JSON")

    conn = _Conn(config=IBOV_CFG, maintained=["ticker:A@BVMF"])
    monkeypatch.setattr(accuracy_mod, "get_index_source", lambda a, **cfg: _Boom())
    with pytest.raises(UniverseError, match="fetch failed"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D)


def test_autocommit_set_before_first_query(monkeypatch):
    # psycopg forbids toggling autocommit once an implicit transaction is open —
    # the runner must set it before its first SELECT.
    class _Strict(_Conn):
        def execute(self, sql, params=None):
            assert self.autocommit is True, f"query before autocommit: {sql[:60]}"
            return super().execute(sql, params)

    toks = ["ticker:A@BVMF"]
    conn = _Strict(config=IBOV_CFG, maintained=toks)
    _patch_source(monkeypatch, toks)
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


def test_library_threshold_validated(monkeypatch):
    # The CLI validates too, but a scheduler/notebook calling the library
    # directly must not silently get a gate that never (or always) alarms.
    conn = _Conn(config=IBOV_CFG, maintained=["ticker:A@BVMF"])
    _patch_source(monkeypatch, ["ticker:A@BVMF"])
    with pytest.raises(UniverseError, match="threshold"):
        run_configured_accuracy_check(conn, "ibov", as_of_date=D, threshold=42)


def test_audit_row_records_comparison_basis(monkeypatch):
    # A FIGI-fallback pass must be distinguishable from a raw-token pass in the
    # persisted audit row.
    conn = _Conn(
        config=IBOV_CFG,
        maintained=["ticker:SAP@XETR"],
        figis=["BBG000000SAP"],
        symbology={"SAP": "BBG000000SAP"},
    )
    _patch_source(monkeypatch, ["ticker:SAP@XNYS"])
    run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert "figi" in str(conn.checks[0])

    conn2 = _Conn(config=IBOV_CFG, maintained=["ticker:A@BVMF"])
    _patch_source(monkeypatch, ["ticker:A@BVMF"])
    run_configured_accuracy_check(conn2, "ibov", as_of_date=D)
    assert "raw" in str(conn2.checks[0])


def test_same_scheme_zero_overlap_falls_back_to_figis(monkeypatch):
    # Same ticker: scheme but different MIC conventions (XETR vs XNYS for a
    # cross-listed reference) would diverge toward 1.0 on raw tokens — zero
    # overlap with a shared scheme must trigger the FIGI fallback too.
    conn = _Conn(
        config=IBOV_CFG,
        maintained=["ticker:SAP@XETR"],
        figis=["BBG000000SAP"],
        symbology={"SAP": "BBG000000SAP"},
    )
    _patch_source(monkeypatch, ["ticker:SAP@XNYS"])
    result = run_configured_accuracy_check(conn, "ibov", as_of_date=D)
    assert result.divergence == 0.0 and result.alarm is False


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


def test_cli_reverse_refuses_never_recorded_change(monkeypatch, capsys):
    # A typo'd (token, change, date) must not append a context-free corrective
    # that corrupts the projection while printing success.
    conn = _Conn()
    conn.event_exists = False
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    rc = main(["universe", "reverse", "ibov", "ticker:B@BVMF", "leave", "2026-06-10"])
    assert rc == 1
    assert conn.events == [] and conn.rebuilt == 0
    assert "nothing to reverse" in capsys.readouterr().err


def test_cli_accuracy_rejects_out_of_range_threshold(monkeypatch, capsys):
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn(config=IBOV_CFG))
    assert main(["universe", "accuracy", "ibov", "--threshold", "1.5"]) == 1
    assert "threshold" in capsys.readouterr().err
    assert main(["universe", "accuracy", "ibov", "--threshold", "-0.1"]) == 1
