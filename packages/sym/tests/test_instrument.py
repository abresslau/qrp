"""Tests for the universal instrument identity layer (Benchmark epic B1). DB-free."""

from __future__ import annotations

from sym.identity.instrument import (
    EQUITY,
    INDEX,
    SRC_COMPOSITE_FIGI,
    SRC_YAHOO,
    ensure_instrument,
)


class _FakeConn:
    """Records executes; returns canned rows for the queries ensure_instrument runs."""

    def __init__(self, existing_xref: dict[tuple[str, str], int] | None = None):
        self.existing = existing_xref or {}
        self.inserts: list[str] = []
        self._last_params = None

    def execute(self, sql, params=None):
        self._last_sql = sql
        self._last_params = params
        if "INSERT INTO instrument_xref" in sql:
            self.inserts.append("xref")
        elif "INSERT INTO instrument " in sql:
            self.inserts.append("instrument")
        return self

    def fetchone(self):
        sql = self._last_sql
        if "SELECT sym_id FROM instrument_xref" in sql:
            source, value = self._last_params
            sid = self.existing.get((source, value))
            return (sid,) if sid is not None else None
        if "RETURNING sym_id" in sql:
            return (999,)  # new instrument id
        return None


def test_constants():
    assert EQUITY == "equity" and INDEX == "index"


def test_ensure_returns_existing_when_xref_maps_and_does_not_create():
    conn = _FakeConn(existing_xref={(SRC_COMPOSITE_FIGI, "BBG000B9XRY4"): 42})
    sid = ensure_instrument(conn, EQUITY, xrefs={SRC_COMPOSITE_FIGI: "BBG000B9XRY4"})
    assert sid == 42
    assert "instrument" not in conn.inserts  # idempotent: no new instrument created


def test_ensure_creates_new_when_no_xref_matches():
    conn = _FakeConn()
    sid = ensure_instrument(
        conn, INDEX, name="S&P 500", xrefs={SRC_YAHOO: "^GSPC"}
    )
    assert sid == 999
    assert "instrument" in conn.inserts  # created
    assert "xref" in conn.inserts        # and the yahoo xref attached
