"""Review-queue gating (Story 1.9 — chunk-4 D1; Story 1.4 AC2/AC3 made real). DB-free.

The queue stops being write-only: open rows GATE resolution runs (no OpenFIGI
query, no assignment), and `resolve_review` closes rows (with or without a
steward FIGI pick), freeing the key for re-queue per the partial unique index.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import sym.db
from sym.cli import main
from sym.identity import review_queue as rq
from sym.identity.figi import resolve_universe
from sym.identity.review_queue import (
    ReviewQueueError,
    open_review_keys,
    resolve_review,
)
from sym.identity.universe import SeedSecurity


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, *, open_keys=(), review_row=None, list_rows=None):
        self.autocommit = False
        self._open = list(open_keys)
        self._review_row = review_row        # (source_key, source_input, resolved_at)
        self._list_rows = list_rows or []
        self.enqueued: list[tuple] = []
        self.resolved_ids: list[int] = []

    update_hits = True  # set False to simulate a concurrent resolution

    def execute(self, sql, params=None):
        if "SELECT source_key FROM securities_review_queue" in sql:
            return _Cur(rows=[(k,) for k in self._open])
        if "SELECT mic, exch_code FROM exchange" in sql:
            return _Cur(rows=[("XNAS", "UW"), ("XNYS", "UN")])
        if "INSERT INTO securities_review_queue" in sql:
            self.enqueued.append((params[0], params[3]))
            return _Cur(one=(99, True))
        if "FROM securities_review_queue WHERE review_id" in sql:
            return _Cur(one=self._review_row)
        if "UPDATE securities_review_queue" in sql and "resolved_at = now()" in sql:
            if not self.update_hits:
                return _Cur(one=None)
            self.resolved_ids.append(params[-1])
            self.close_notes = getattr(self, "close_notes", []) + [params[0]]
            return _Cur(one=(params[-1],))
        if "FROM securities_review_queue" in sql:  # list query
            return _Cur(rows=self._list_rows)
        raise AssertionError(sql)

    def transaction(self):
        import contextlib

        return contextlib.nullcontext()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Client:
    """Fake OpenFIGI client recording every query it receives."""

    def __init__(self):
        self.queries: list = []

    def map_identifiers(self, queries):
        self.queries.extend(queries)
        return [[] for _ in queries]  # everything no-match -> enqueue path


def _seed(name, ticker, mic, isin=None):
    return SeedSecurity(name, "test", ticker, mic, isin, None)


# --- the gate ------------------------------------------------------------------


def test_queued_seed_is_skipped_entirely():
    # AC1 + AC5: queued seeds never reach OpenFIGI and are counted. The open key
    # is DERIVED via source_key (not a string literal) so key-construction drift
    # breaks this test rather than silently leaking through the gate.
    seed = _seed("Twitter", "TWTR", "XNYS")
    conn = _Conn(open_keys=[rq.source_key(seed.resolution_inputs()[0])])
    client = _Client()
    summary = resolve_universe(conn, client, [seed])
    assert summary.skipped_queued == 1
    assert client.queries == []                 # zero OpenFIGI traffic
    assert conn.enqueued == []                  # nothing re-classified either


def test_gate_matches_any_resolution_input_key():
    # The queued row may carry the ISIN-fallback key while the seed's primary is
    # the ticker key — the gate must check EVERY input, not just the head.
    seed = _seed("Twitter", "TWTR", "XNYS", isin="US90184L1026")
    conn = _Conn(open_keys=[rq.source_key(seed.resolution_inputs()[1])])
    client = _Client()
    summary = resolve_universe(conn, client, [seed])
    assert summary.skipped_queued == 1 and client.queries == []


def test_unqueued_seeds_still_flow():
    conn = _Conn(open_keys=["ticker:TWTR@XNYS"])
    client = _Client()
    summary = resolve_universe(
        conn, client,
        [_seed("Twitter", "TWTR", "XNYS"), _seed("Apple", "AAPL", "XNAS")],
    )
    assert summary.skipped_queued == 1
    assert len(client.queries) == 1 and client.queries[0].symbol_value == "AAPL"
    assert summary.no_figi_found == 1           # the free seed ran the normal path
    assert summary.skipped_names == ["Twitter"]


# --- queue read/close API --------------------------------------------------------


def test_open_review_keys():
    conn = _Conn(open_keys=["ticker:A@XNAS", "isin:X1"])
    assert open_review_keys(conn) == {"ticker:A@XNAS", "isin:X1"}


def test_resolve_review_dismiss_closes_row():
    conn = _Conn(review_row=("ticker:ENE@XNYS", {"symbol_type": "ticker"}, None))
    assert resolve_review(conn, 4) == "dismissed"
    assert conn.resolved_ids == [4]


def test_resolve_review_unknown_or_already_resolved_raises():
    with pytest.raises(ReviewQueueError, match="no review row"):
        resolve_review(_Conn(review_row=None), 999)
    done = _Conn(review_row=("k", {}, datetime(2026, 6, 1)))
    with pytest.raises(ReviewQueueError, match="already resolved"):
        resolve_review(done, 4)


def test_resolve_review_assignment_validates_and_writes(monkeypatch):
    written = {}

    def fake_write_security(conn, *, seed, composite_figi, share_class_figi):
        written.update(figi=composite_figi, ticker=seed.ticker, mic=seed.mic)
        return True

    monkeypatch.setattr(rq, "write_security", fake_write_security)
    source_input = {"name": "Enron", "category": "test",
                    "symbol_type": "ticker", "symbol_value": "ENE", "mic": "XNYS"}
    conn = _Conn(review_row=("ticker:ENE@XNYS", source_input, None))
    outcome = resolve_review(conn, 4, composite_figi="BBG000000ENE")
    assert outcome == "assigned"
    assert written == {"figi": "BBG000000ENE", "ticker": "ENE", "mic": "XNYS"}
    assert conn.resolved_ids == [4]


def test_resolve_review_rejects_bad_figi_and_unassignable_input():
    conn = _Conn(review_row=("ticker:ENE@XNYS",
                             {"symbol_type": "ticker", "symbol_value": "ENE",
                              "mic": "XNYS"}, None))
    with pytest.raises(ReviewQueueError, match="FIGI"):
        resolve_review(conn, 4, composite_figi="not-a-figi")
    isin_only = _Conn(review_row=("isin:X1", {"symbol_type": "isin",
                                              "symbol_value": "X1"}, None))
    with pytest.raises(ReviewQueueError, match="ticker"):
        resolve_review(isin_only, 5, composite_figi="BBG000000ENE")


def test_resolve_review_normalizes_lowercase_figi(monkeypatch):
    written = {}
    monkeypatch.setattr(rq, "write_security",
                        lambda conn, *, seed, composite_figi, share_class_figi:
                        written.update(figi=composite_figi) or True)
    source_input = {"name": "Enron", "symbol_type": "ticker",
                    "symbol_value": "ENE", "mic": "XNYS"}
    conn = _Conn(review_row=("ticker:ENE@XNYS", source_input, None))
    resolve_review(conn, 4, composite_figi="bbg000000ene")
    assert written["figi"] == "BBG000000ENE"


def test_resolve_review_validates_share_class_figi():
    conn = _Conn(review_row=("ticker:ENE@XNYS",
                             {"symbol_type": "ticker", "symbol_value": "ENE",
                              "mic": "XNYS"}, None))
    with pytest.raises(ReviewQueueError, match="ShareClassFIGI"):
        resolve_review(conn, 4, composite_figi="BBG000000ENE",
                       share_class_figi="nope")


def test_resolve_review_write_failure_is_typed_and_row_stays_open(monkeypatch):
    # Constraint 4: a write_security failure (collision, unknown MIC) must surface
    # as a clean ReviewQueueError — and the row must NOT close.
    def boom(conn, *, seed, composite_figi, share_class_figi):
        raise RuntimeError("symbology collision")

    monkeypatch.setattr(rq, "write_security", boom)
    source_input = {"name": "Enron", "symbol_type": "ticker",
                    "symbol_value": "ENE", "mic": "XNYS"}
    conn = _Conn(review_row=("ticker:ENE@XNYS", source_input, None))
    with pytest.raises(ReviewQueueError, match="assignment failed"):
        resolve_review(conn, 4, composite_figi="BBG000000ENE")
    assert conn.resolved_ids == []


def test_resolve_review_concurrent_close_raises():
    conn = _Conn(review_row=("ticker:ENE@XNYS", {"symbol_type": "ticker"}, None))
    conn.update_hits = False  # someone else resolved it between SELECT and UPDATE
    with pytest.raises(ReviewQueueError, match="concurrently"):
        resolve_review(conn, 4)
    assert conn.resolved_ids == []


def test_resolve_review_records_outcome_in_detail():
    conn = _Conn(review_row=("ticker:ENE@XNYS", {"symbol_type": "ticker"}, None))
    resolve_review(conn, 4)
    assert any("dismissed" in n for n in conn.close_notes)


def test_resolve_review_parses_string_source_input(monkeypatch):
    # psycopg normally hands jsonb back as a dict, but the str branch exists —
    # exercise it for real.
    written = {}
    monkeypatch.setattr(rq, "write_security",
                        lambda conn, *, seed, composite_figi, share_class_figi:
                        written.update(ticker=seed.ticker) or True)
    payload = json.dumps({"name": "Enron", "symbol_type": "ticker",
                          "symbol_value": "ENE", "mic": "XNYS"})
    conn = _Conn(review_row=("ticker:ENE@XNYS", payload, None))
    assert resolve_review(conn, 4, composite_figi="BBG000000ENE") == "assigned"
    assert written["ticker"] == "ENE"


def test_resolve_review_rejects_unusable_source_input():
    conn = _Conn(review_row=("ticker:ENE@XNYS", ["not", "a", "dict"], None))
    with pytest.raises(ReviewQueueError, match="unusable"):
        resolve_review(conn, 4, composite_figi="BBG000000ENE")
    blank = _Conn(review_row=("ticker:ENE@XNYS",
                              {"symbol_type": "ticker", "symbol_value": "",
                               "mic": "XNYS"}, None))
    with pytest.raises(ReviewQueueError, match="unusable"):
        resolve_review(blank, 4, composite_figi="BBG000000ENE")


# --- CLI -------------------------------------------------------------------------


def test_cli_review_list(monkeypatch, capsys):
    rows = [(4, "ticker:ENE@XNYS", "no_figi_found", 0, None,
             datetime(2026, 6, 8), None)]
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn(list_rows=rows))
    assert main(["review", "list"]) == 0
    out = capsys.readouterr().out
    assert "ticker:ENE@XNYS" in out and "no_figi_found" in out


def test_cli_review_list_empty(monkeypatch, capsys):
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn(list_rows=[]))
    assert main(["review", "list"]) == 0
    assert "no open review items" in capsys.readouterr().out


def test_cli_review_resolve_exit_codes(monkeypatch, capsys):
    conn = _Conn(review_row=("ticker:ENE@XNYS", {"symbol_type": "ticker"}, None))
    monkeypatch.setattr(sym.db, "connect", lambda: conn)
    assert main(["review", "resolve", "4"]) == 0
    assert "dismissed" in capsys.readouterr().out

    monkeypatch.setattr(sym.db, "connect", lambda: _Conn(review_row=None))
    assert main(["review", "resolve", "999"]) == 1
    assert "no review row" in capsys.readouterr().err


def test_cli_share_class_requires_figi(monkeypatch, capsys):
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn())
    rc = main(["review", "resolve", "4", "--share-class-figi", "BBG000000SC1"])
    assert rc == 1
    assert "--figi" in capsys.readouterr().err


def test_cli_review_list_all_empty_message(monkeypatch, capsys):
    monkeypatch.setattr(sym.db, "connect", lambda: _Conn(list_rows=[]))
    assert main(["review", "list", "--all"]) == 0
    out = capsys.readouterr().out
    assert "no review items" in out and "open" not in out


def test_skipped_names_overflow_indicator(capsys):
    # 12 gated seeds: 10 named + an explicit "+2 more" — never a silent cut.
    seeds = [_seed(f"Name{i}", f"T{i}", "XNYS") for i in range(12)]
    keys = [rq.source_key(s.resolution_inputs()[0]) for s in seeds]
    conn = _Conn(open_keys=keys)
    summary = resolve_universe(conn, _Client(), seeds)
    assert summary.skipped_queued == 12
    # the CLI line itself (formatting lives in cli.py; assert via the helper there)
    from sym.cli import _format_skipped_line

    line = _format_skipped_line(summary)
    assert "+2 more" in line and "Name9" in line and "Name11" not in line
