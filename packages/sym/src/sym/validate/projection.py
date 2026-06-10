"""Membership projection reconciliation (Story V5).

The stored ``universe_membership`` interval table is a *projection* of the
append-only event log. This check re-projects the log from scratch (the U1.4
projector) and asserts it equals what's stored — catching a stale or hand-edited
projection that drifted from the truth. It also checks the ``pit_valid_from``
honesty boundary is not set *earlier* than the earliest dated leave (which would
expose a survivorship-biased range). Reconciliation is a pure set-compare.
"""

from __future__ import annotations

from datetime import date

import psycopg

from sym.universe.projection import _membership_events, project_membership
from sym.universe.registry import LEAVE
from sym.validate.results import CheckResult

Intervals = dict[str, set[tuple[date, date | None]]]


def reconcile(stored: Intervals, projected: Intervals) -> list[str]:
    """FIGIs whose stored intervals differ from a fresh projection (pure).

    Returns one description per diverging FIGI (missing/extra/mismatched
    intervals). Empty list = the projection is in sync with the log.
    """
    diffs: list[str] = []
    for figi in sorted(set(stored) | set(projected)):
        s = stored.get(figi, set())
        p = projected.get(figi, set())
        if s != p:
            only_stored = s - p
            only_proj = p - s
            diffs.append(
                f"{figi}: stored-only={sorted(map(str, only_stored))} "
                f"projected-only={sorted(map(str, only_proj))}"
            )
    return diffs


def check_projection_reconciliation(conn: psycopg.Connection) -> CheckResult:
    """`universe_membership` must equal a fresh re-projection of each universe's log."""
    universes = [r[0] for r in conn.execute("SELECT universe_id FROM universe").fetchall()]
    failures: list[str] = []
    warnings: list[str] = []
    for uid in universes:
        events = _membership_events(conn, uid)
        projected: Intervals = {
            figi: {(iv.valid_from, iv.valid_to) for iv in ivs}
            for figi, ivs in project_membership(events).items()
        }
        stored: Intervals = {}
        for figi, vf, vt in conn.execute(
            "SELECT composite_figi, valid_from, valid_to FROM universe_membership "
            "WHERE universe_id = %s",
            (uid,),
        ).fetchall():
            stored.setdefault(figi, set()).add((vf, vt))
        failures += [f"{uid}/{d}" for d in reconcile(stored, projected)]

        # pit honesty: the boundary should not be set earlier than the earliest
        # dated leave the *source* records (below which leave-completeness — hence
        # survivorship-safety — is not guaranteed). Compare against ALL leave events
        # (resolved or not), matching how refresh derives pit.
        pit = conn.execute(
            "SELECT pit_valid_from FROM universe WHERE universe_id = %s", (uid,)
        ).fetchone()[0]
        earliest_leave = conn.execute(
            "SELECT min(effective_date) FROM membership_event "
            "WHERE universe_id = %s AND change = %s",
            (uid, LEAVE),
        ).fetchone()[0]
        if earliest_leave is not None and pit is not None and pit < earliest_leave:
            warnings.append(
                f"{uid}: pit_valid_from {pit} precedes earliest recorded leave {earliest_leave}"
            )
        elif earliest_leave is not None and pit is None:
            # NULL pit with dated leaves is the MOST dishonest state — queries have no
            # refusal boundary at all over a window with known survivorship gaps.
            warnings.append(
                f"{uid}: pit_valid_from is NULL but dated leaves exist "
                f"(earliest {earliest_leave}) — no PIT refusal boundary"
            )

    return CheckResult.from_items(
        "projection_reconciliation",
        checked=len(universes),
        failures=failures,
        warnings=warnings,
        detail=f"{len(universes)} universes re-projected vs stored membership",
    )
