"""Snapshot-pin resolution watermark (Story U1.7, ledger D2). DB-free.

A pin is (universe_id, as_of_date, log_version, resolved_through): the events
watermark already existed (U1.6); these cover the RESOLUTION watermark — the
upgrade bump that makes it meaningful, the query filter, and the capture helper.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sym.universe.projection import _membership_events
from sym.universe.resolution import MemberResolution, ResolutionSummary, _write_resolutions
from sym.universe.snapshot import current_resolution_version, members_pinned

T = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, one=None, rows=None):
        self.calls: list[tuple[str, tuple]] = []
        self._one, self._rows = one, rows or []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Cur(one=self._one, rows=self._rows)


def test_upgrade_upsert_bumps_resolved_at():
    # The watermark is DEFEATED unless the unresolved->resolved upgrade stamps
    # resolved_at = now(): an upgraded row would keep its INSERT-time default,
    # predate any pin, and leak into every old pin's member set.
    conn = _Conn(one=("ticker:A@XNAS",))
    _write_resolutions(
        conn, "u",
        {"ticker:A@XNAS": MemberResolution("ticker:A@XNAS", "BBG000000001", None, "resolved")},
        ResolutionSummary(),
    )
    sql = conn.calls[0][0]
    update_clause = sql.split("DO UPDATE", 1)[1]
    assert "resolved_at = now()" in update_clause


def test_membership_events_filters_by_resolved_through():
    conn = _Conn(rows=[])
    _membership_events(conn, "u", resolved_through=T)
    sql, params = conn.calls[0]
    assert "r.resolved_at <= %s" in sql
    assert T in params


def test_membership_events_without_watermark_has_no_filter():
    conn = _Conn(rows=[])
    _membership_events(conn, "u")
    sql, _params = conn.calls[0]
    assert "resolved_at" not in sql.split("SELECT", 1)[1].split("FROM", 1)[0]
    assert "r.resolved_at <= " not in sql


def test_members_pinned_forwards_both_watermarks():
    class _PinConn(_Conn):
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "pit_valid_from" in sql or "FROM universe " in sql:
                return _Cur(one=(date(2020, 1, 1),))
            return _Cur(rows=[])

    conn = _PinConn()
    members_pinned(conn, "u", date(2026, 6, 9), 500, resolved_through=T)
    event_sql, params = next(
        (sql, p) for sql, p in conn.calls if "membership_event" in sql
    )
    assert "e.event_id <= %s" in event_sql and 500 in params
    assert "r.resolved_at <= %s" in event_sql and T in params


def test_current_resolution_version_capture():
    conn = _Conn(one=(T,))
    assert current_resolution_version(conn, "u") == T
    sql, params = conn.calls[0]
    assert "max(resolved_at)" in sql and params == ("u",)
