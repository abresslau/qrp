"""Tests for security lifecycle: soft-delete + survivorship-safe filtering (Story 1.7)."""

import re
from datetime import date
from pathlib import Path

import pytest

from sym.identity.lifecycle import (
    ACTIVE,
    DELISTED,
    _active_filter,
    delist_security,
    set_status,
)


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _RecordingConn:
    """Captures executed SQL + params; returns a canned single row."""

    def __init__(self, row=("BBG000000201",)):
        self._row = row
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return _FakeCursor(self._row)


# --- _active_filter --------------------------------------------------------


def test_active_filter_default_excludes_delisted():
    assert _active_filter(include_delisted=False) == "status = 'active'"


def test_active_filter_include_widens_to_all():
    assert _active_filter(include_delisted=True) == "TRUE"


# --- delist_security -------------------------------------------------------


def test_delist_rejects_active_status():
    conn = _RecordingConn()
    with pytest.raises(ValueError):
        delist_security(conn, "BBG000000201", delist_date=date(2024, 1, 1), status=ACTIVE)
    assert conn.calls == []  # rejected before any DB write


def test_delist_sets_status_and_date():
    conn = _RecordingConn()
    found = delist_security(conn, "BBG000000201", delist_date=date(2024, 1, 1))
    assert found is True
    sql, params = conn.calls[0]
    assert "UPDATE securities" in sql
    assert "DELETE" not in sql.upper()
    assert params == (DELISTED, date(2024, 1, 1), "BBG000000201")


def test_delist_returns_false_when_not_found():
    conn = _RecordingConn(row=None)
    assert delist_security(conn, "BBG000000999", delist_date=date(2024, 1, 1)) is False


def test_set_status_active_clears_delist_date():
    conn = _RecordingConn()
    set_status(conn, "BBG000000201", status=ACTIVE)
    sql, params = conn.calls[0]
    assert params[0] == ACTIVE
    assert params[1] is True  # clear_delist flag


# --- soft-delete invariant (AC3) -------------------------------------------


def test_no_hard_delete_of_securities_in_source():
    """No code path may hard-delete a security row (survivorship invariant)."""
    src = Path(__file__).resolve().parents[1] / "src" / "sym"
    # \b after "securities" excludes securities_review_queue (underscore is a word char).
    hard_delete = re.compile(r"delete\s+from\s+securities\b", re.IGNORECASE)
    offenders = []
    for py in src.rglob("*.py"):
        if hard_delete.search(py.read_text(encoding="utf-8")):
            offenders.append(py.name)
    assert offenders == [], f"hard-delete of securities found in: {offenders}"
