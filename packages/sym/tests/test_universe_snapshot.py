"""Tests for reproducible universe snapshots (Story U1.6). DB-free.

`members_from_events` is the pure core: projecting an event subset to as-of
membership. These prove a pinned subset (events <= a watermark) ignores
later-appended leaves/corrections, so a pin is reproducible. The DB event-id
filtering + latest-vs-pinned divergence are verified live.
"""

from __future__ import annotations

from datetime import date

from sym.universe.projection import MembershipEvent
from sym.universe.snapshot import members_from_events

X = "BBG000000001"
ASOF = date(2026, 1, 1)


def _ev(change, day, eid):
    return MembershipEvent(X, change, date(2024, 1, day), eid, "ticker:A@XNAS", "test")


def test_member_present_when_only_join_seen():
    # Pin at the join (event 1) -> still a member as-of a much later date.
    assert members_from_events([_ev("join", 2, 1)], ASOF) == {X}


def test_later_leave_excluded_when_pinned_before_it():
    pinned = [_ev("join", 2, 1)]  # log-version cut before the leave
    full = [_ev("join", 2, 1), _ev("leave", 10, 2)]  # leave appended later
    # Pinned (ignoring the later leave) keeps the member; the full log drops it.
    assert members_from_events(pinned, ASOF) == {X}
    assert members_from_events(full, ASOF) == set()


def test_pin_reproducible_under_later_correction():
    # A correction appended after the pin must not change the pinned answer.
    pinned = [_ev("join", 2, 1), _ev("leave", 5, 2)]
    corrected = [*pinned, _ev("correct", 5, 3)]  # later toggle reopening at day 5
    before = members_from_events(pinned, ASOF)   # left at day 5 -> not a member at 2026
    after = members_from_events(pinned, ASOF)    # same pinned subset -> identical
    assert before == after == set()
    # the unpinned (corrected) log differs: the toggle reopens membership
    assert members_from_events(corrected, ASOF) == {X}


def test_as_of_before_join_is_not_a_member():
    assert members_from_events([_ev("join", 10, 1)], date(2024, 1, 5)) == set()
