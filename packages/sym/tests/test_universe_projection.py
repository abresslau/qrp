"""Tests for the point-in-time membership projection (Story U1.4). DB-free.

`project_membership` is a pure function over events → per-FIGI intervals; these
cover the state machine, FIGI-level rename coalescing, correct-toggle,
out-of-order determinism, zero-length dropping, and an invert(project)==log
round-trip. The DB rebuild + EXCLUDE no-overlap are verified live.
"""

from __future__ import annotations

from datetime import date

from sym.universe.projection import (
    Interval,
    MembershipEvent,
    project_membership,
)

X = "BBG000000001"  # a CompositeFIGI


def _ev(change, day, eid, figi=X, raw="ticker:A@XNAS"):
    return MembershipEvent(figi, change, date(2024, 1, day), eid, raw, "test")


def test_join_then_leave_is_one_closed_interval():
    out = project_membership([_ev("join", 2, 1), _ev("leave", 10, 2)])
    assert out[X] == [Interval(date(2024, 1, 2), date(2024, 1, 10), "ticker:A@XNAS", "test")]


def test_open_ended_when_no_leave():
    out = project_membership([_ev("join", 2, 1)])
    assert out[X] == [Interval(date(2024, 1, 2), None, "ticker:A@XNAS", "test")]


def test_ticker_rename_same_figi_stays_one_continuous_interval():
    # leave(FB)@5 + join(META)@5 on the SAME FIGI -> coalesced to one interval.
    events = [
        _ev("join", 2, 1, raw="ticker:FB@XNAS"),
        _ev("leave", 5, 2, raw="ticker:FB@XNAS"),
        _ev("join", 5, 3, raw="ticker:META@XNAS"),
    ]
    out = project_membership(events)
    assert out[X] == [Interval(date(2024, 1, 2), None, "ticker:FB@XNAS", "test")]


def test_correct_toggles_state():
    # join then a corrective event closes the open interval.
    out = project_membership([_ev("join", 2, 1), _ev("correct", 8, 2)])
    assert out[X] == [Interval(date(2024, 1, 2), date(2024, 1, 8), "ticker:A@XNAS", "test")]


def test_out_of_order_events_are_deterministic():
    forward = [_ev("join", 2, 1), _ev("leave", 10, 2)]
    shuffled = [_ev("leave", 10, 2), _ev("join", 2, 1)]
    assert project_membership(forward) == project_membership(shuffled)


def test_zero_length_membership_is_dropped():
    # join and leave the same day -> not a member, no interval.
    assert project_membership([_ev("join", 4, 1), _ev("leave", 4, 2)]) == {X: []}


def test_invert_project_roundtrips():
    # Build a log from intervals, project it, and recover the same intervals.
    intervals = [
        Interval(date(2024, 1, 2), date(2024, 1, 10)),
        Interval(date(2024, 3, 1), None),
    ]
    log = []
    eid = 0
    for iv in intervals:
        eid += 1
        log.append(MembershipEvent(X, "join", iv.valid_from, eid))
        if iv.valid_to is not None:
            eid += 1
            log.append(MembershipEvent(X, "leave", iv.valid_to, eid))
    projected = project_membership(log)[X]
    assert [(i.valid_from, i.valid_to) for i in projected] == [
        (i.valid_from, i.valid_to) for i in intervals
    ]


def test_separate_figis_are_independent():
    y = "BBG000000002"
    out = project_membership([_ev("join", 2, 1), _ev("join", 3, 2, figi=y)])
    assert out[X][0].valid_from == date(2024, 1, 2)
    assert out[y][0].valid_from == date(2024, 1, 3)
