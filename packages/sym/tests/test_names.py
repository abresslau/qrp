"""Tests for effective-dated company names (SCD writer). DB-free."""

from __future__ import annotations

from datetime import date

from sym.identity.names import (
    INSERTED,
    REPLACED,
    UNCHANGED,
    UPDATED,
    write_name,
)

FIGI = "BBG000B9XRY4"


class _Cur:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, current=None):
        self._current = current  # (name, valid_from) or None
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.strip().upper().startswith("SELECT"):
            return _Cur(self._current)
        return _Cur(None)

    def sql(self):
        return " ".join(s.upper() for s, _ in self.calls)


def test_first_name_is_inserted():
    conn = _Conn(current=None)
    assert write_name(conn, FIGI, "APPLE INC", as_of=date(2026, 6, 6)) == INSERTED
    assert "INSERT INTO SECURITY_NAMES" in conn.sql()
    assert "SET VALID_TO" not in conn.sql()  # nothing to close


def test_unchanged_name_is_noop():
    conn = _Conn(current=("APPLE INC", date(2020, 1, 1)))
    assert write_name(conn, FIGI, "APPLE INC", as_of=date(2026, 6, 6)) == UNCHANGED
    assert "INSERT" not in conn.sql() and "UPDATE" not in conn.sql()


def test_same_day_correction_updates_in_place():
    # current row written today -> overwrite, don't close (avoids valid_to == valid_from)
    conn = _Conn(current=("APPLE COMPUTER INC", date(2026, 6, 6)))
    assert write_name(conn, FIGI, "APPLE INC", as_of=date(2026, 6, 6)) == UPDATED
    sql = conn.sql()
    assert "UPDATE SECURITY_NAMES SET NAME" in sql
    assert "SET VALID_TO" not in sql and "INSERT" not in sql


def test_rename_on_a_later_day_closes_then_inserts():
    # Facebook -> Meta: prior row from an earlier day is closed, new row inserted
    conn = _Conn(current=("FACEBOOK INC-CLASS A", date(2012, 5, 18)))
    assert write_name(conn, FIGI, "META PLATFORMS INC-CLASS A", as_of=date(2022, 6, 9)) == REPLACED
    sql = conn.sql()
    assert "SET VALID_TO" in sql  # prior name closed
    assert "INSERT INTO SECURITY_NAMES" in sql
    assert "DELETE" not in sql  # SCD closes, never deletes
