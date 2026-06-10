"""Provenance-aware corrective pairing (Story U3.7, ledger D3). DB-free.

A `correct` event whose provenance.reverses names a change kind is a TOMBSTONE
for exactly the event matching (raw_identifier, change, effective_date) — both
are excluded from the state machine. A corrective with no reverses provenance
(legacy) or no matching target keeps the old toggle behavior, counted.
"""

from __future__ import annotations

from datetime import date

from sym.universe.projection import (
    Interval,
    MembershipEvent,
    pair_corrections,
    project_membership,
)

X = "BBG000000001"


def _ev(change, day, eid, figi=X, raw="ticker:A@XNAS", provenance=None):
    return MembershipEvent(figi, change, date(2024, 1, day), eid, raw, "test", provenance)


def _rev(target_change, day, eid, **kw):
    return _ev("correct", day, eid, provenance={"reverses": target_change}, **kw)


def test_corrective_annihilates_exactly_its_target():
    # join D2, WRONG leave D10, corrective(reverses=leave)@D10 -> leave voided,
    # membership stays open from D2.
    out = project_membership([_ev("join", 2, 1), _ev("leave", 10, 2), _rev("leave", 10, 3)])
    assert out[X] == [Interval(date(2024, 1, 2), None, "ticker:A@XNAS", "test")]


def test_intervening_event_does_not_invert_intent():
    # THE D3 bug: wrong join D5 for token B, genuine join D5 for token A (same
    # figi, different raw), corrective targets B's join. Under the old toggle the
    # corrective would CLOSE whatever was open (A's genuine membership); under
    # pairing it annihilates only B's join.
    events = [
        _ev("join", 5, 1, raw="ticker:B@XNAS"),          # wrong
        _ev("join", 5, 2, raw="ticker:A@XNAS"),          # genuine
        _rev("join", 5, 3, raw="ticker:B@XNAS"),         # reverses B's join
    ]
    out = project_membership(events)
    assert out[X] == [Interval(date(2024, 1, 5), None, "ticker:A@XNAS", "test")]


def test_pairing_is_per_raw_identifier_not_per_figi():
    # Two raw tokens resolve to one FIGI; the corrective names token B's leave —
    # token A's identical-date leave must NOT be annihilated.
    events = [
        _ev("join", 2, 1, raw="ticker:A@XNAS"),
        _ev("leave", 9, 2, raw="ticker:A@XNAS"),         # genuine — must survive
        _ev("join", 3, 3, raw="ticker:B@XNAS"),
        _ev("leave", 9, 4, raw="ticker:B@XNAS"),         # wrong
        _rev("leave", 9, 5, raw="ticker:B@XNAS"),
    ]
    survivors, paired, _ = pair_corrections(events)
    # Only B's leave was annihilated; A's identical-date leave SURVIVES.
    assert paired == 1
    assert any(e.raw_identifier == "ticker:A@XNAS" and e.change == "leave"
               for e in survivors)
    assert not any(e.raw_identifier == "ticker:B@XNAS" and e.change == "leave"
                   for e in survivors)
    # FIGI-level outcome: A's genuine leave closes the membership at D9 — had
    # the corrective cross-annihilated A's leave, the interval would stay open.
    out = project_membership(events)
    assert out[X] == [Interval(date(2024, 1, 2), date(2024, 1, 9), "ticker:A@XNAS", "test")]


def test_legacy_provenance_less_correct_keeps_toggle():
    out = project_membership([_ev("join", 2, 1), _ev("correct", 8, 2)])
    assert out[X] == [Interval(date(2024, 1, 2), date(2024, 1, 8), "ticker:A@XNAS", "test")]


def test_unmatched_reverses_falls_back_to_toggle_and_is_counted():
    counters: dict[str, int] = {}
    # corrective names a leave that doesn't exist at that date -> toggle (closes)
    out = project_membership(
        [_ev("join", 2, 1), _rev("leave", 8, 2)], counters
    )
    assert out[X][0].valid_to == date(2024, 1, 8)
    assert counters.get("toggle_corrections") == 1
    assert counters.get("paired_corrections", 0) == 0


def test_paired_corrections_counted():
    counters: dict[str, int] = {}
    project_membership(
        [_ev("join", 2, 1), _ev("leave", 10, 2), _rev("leave", 10, 3)], counters
    )
    assert counters.get("paired_corrections") == 1
    assert counters.get("toggle_corrections", 0) == 0


def test_pair_corrections_pure_function():
    events = [_ev("join", 2, 1), _ev("leave", 10, 2), _rev("leave", 10, 3)]
    survivors, paired, toggles = pair_corrections(events)
    assert [e.event_id for e in survivors] == [1]
    assert paired == 1 and toggles == 0
