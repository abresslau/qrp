"""run_monitor routing through leaver-diff + gating (Story U3.5, Tasks 2-3). DB-free.

The fake connection dispatches by SQL substring (the established pattern) and records
membership_event/membership_proposal writes so the tests can assert WHERE a discovery
landed: staged as a proposal vs appended directly vs promoted to the log.
"""

from __future__ import annotations

import contextlib
from datetime import date

from sym.universe import monitor as monitor_mod
from sym.universe.gating import StageSummary, stage_and_promote
from sym.universe.monitor import MONITOR_GATED, MONITOR_SUCCESS, run_monitor
from sym.universe.registry import JOIN, LEAVE, POLL_BOUNDED, MembershipChange

D = date(2026, 6, 10)


class _Cur:
    def __init__(self, one=None, rows=None):
        self._one, self._rows = one, rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _Conn:
    """Fake for run_monitor + gating + (local) resolve/rebuild queries."""

    def __init__(self, *, open_tokens=(), pending_rows=None):
        self.autocommit = False
        self._open = list(open_tokens)          # tokens whose latest log event is a join
        self._pending = pending_rows or []      # canned promotable proposal rows
        self.proposals: list[tuple] = []        # staged INSERTs (raw, change, reason)
        self.proposal_bumps: list[str] = []     # poll-bounded re-sight UPDATEs (raw)
        self.rejected: set[str] = set()         # raws with a rejected proposal on file
        self.events: list[tuple] = []           # membership_event INSERTs (raw, change)
        self.event_exists = True                # answer for reverse's existence guard
        self.rebuilt = 0                        # universe_membership DELETE = rebuild ran
        self._next_pid = 100

    def execute(self, sql, params=None):
        if "SELECT kind, config, source_pref FROM universe" in sql:
            return _Cur(one=("criteria", {}, None))  # criteria -> local resolver (no network)
        if "SELECT DISTINCT ON (raw_identifier)" in sql:
            return _Cur(rows=[(t, "join") for t in self._open])
        if "INSERT INTO universe_monitor_log" in sql:
            return _Cur(one=(1,))
        if "SELECT 1 FROM membership_proposal" in sql:
            if "status = 'rejected'" in sql:
                return _Cur(one=(1,) if params[1] in self.rejected else None)
            # pending-existence probe (surprising-run duplicate guard)
            return _Cur(one=(1,) if any(p[0] == params[1] for p in self.proposals) else None)
        if "SELECT 1 FROM membership_event" in sql:
            return _Cur(one=(1,) if self.event_exists else None)
        if "UPDATE membership_proposal" in sql and "last_seen_date" in sql:
            # persistence bump (triple- or quad-key); raw sits at index 4 in both layouts
            raw = params[4]
            if any(p[0] == raw for p in self.proposals):
                self.proposal_bumps.append(raw)
                return _Cur(one=(1,))
            return _Cur(one=None)
        if "INSERT INTO membership_proposal" in sql:
            raw, change, reason = params[1], params[2], params[-1]
            self.proposals.append((raw, change, reason))
            self._next_pid += 1
            return _Cur(one=(self._next_pid,))
        if "FROM membership_proposal" in sql and "status = 'pending'" in sql:
            return _Cur(rows=self._pending)
        if "UPDATE membership_proposal" in sql:  # confirm/decide
            return _Cur(one=(1,))
        if "INSERT INTO membership_event" in sql:
            self.events.append((params[1], params[2]))
            return _Cur(one=(len(self.events),))
        # resolve_universe_members pending-tokens query
        if "FROM membership_event e" in sql and "LEFT JOIN universe_member_resolution" in sql:
            return _Cur(rows=[])
        # rebuild_projection reads + writes
        if "FROM membership_event e" in sql:
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


class _Provider:
    def __init__(self, changes, snapshot=None):
        self._changes = changes
        self.last_snapshot_tokens = snapshot

    def members(self, start, end):
        return list(self._changes)


def _patch_provider(monkeypatch, provider):
    monkeypatch.setattr(monitor_mod, "get_provider", lambda kind, **cfg: provider)


def _join(tok, d=D):
    return MembershipChange(tok, JOIN, d, "b3:IBOV", POLL_BOUNDED)


def test_snapshot_leaver_is_derived_and_staged(monkeypatch):
    # 20 open members; the declared snapshot misses only B -> a leave for B is derived
    # and STAGED (never appended directly to the immutable log). 1/20 = 5% churn stays
    # under the gate so the run is an ordinary success.
    open_toks = ["ticker:B@BVMF"] + [f"ticker:M{i}@BVMF" for i in range(19)]
    conn = _Conn(open_tokens=open_toks)
    snapshot = set(open_toks) - {"ticker:B@BVMF"}
    provider = _Provider([_join("ticker:M0@BVMF")], snapshot=snapshot)
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert s.status == MONITOR_SUCCESS
    assert s.leavers == 1 and s.joiners == 0
    assert ("ticker:B@BVMF", "leave", "awaiting_persistence") in conn.proposals
    assert conn.events == []  # nothing applied on first sighting
    assert s.proposed == 1 and s.applied == 0


def test_no_snapshot_means_no_derived_leaves(monkeypatch):
    # Provider declared NO snapshot (dated-history feed) -> absence must not
    # synthesize leaves; only the genuinely-new join is staged.
    conn = _Conn(open_tokens=["ticker:B@BVMF"])
    provider = _Provider([_join("ticker:NEW@BVMF")], snapshot=None)
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert s.joiners == 1 and s.leavers == 0
    assert all(change != "leave" for _raw, change, _r in conn.proposals)


def test_churn_gate_blocks_mass_change(monkeypatch):
    # 10 open members, snapshot keeps only 4 -> 6 leaves = 60% churn > 10% threshold:
    # everything gated as churn_threshold, nothing promoted, status = gated.
    open_toks = [f"ticker:T{i}@BVMF" for i in range(10)]
    keep = set(open_toks[:4])
    conn = _Conn(open_tokens=open_toks)
    provider = _Provider([_join(t) for t in sorted(keep)], snapshot=keep)
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert s.status == MONITOR_GATED
    assert s.applied == 0 and conn.events == []
    assert {r for (_raw, _c, r) in conn.proposals} == {"churn_threshold"}


def test_promotion_appends_and_rebuilds(monkeypatch):
    # A pending leave that has persisted 2 days promotes: appended to the log,
    # the projection rebuilt, applied counted.
    pending = [(
        7, "ticker:B@BVMF", "leave", D, "poll_bounded", "b3:IBOV",
        "awaiting_persistence", date(2026, 6, 8), D, ["b3:IBOV"],
    )]
    conn = _Conn(open_tokens=["ticker:A@BVMF", "ticker:B@BVMF"], pending_rows=pending)
    provider = _Provider([_join("ticker:A@BVMF"), _join("ticker:B@BVMF")],
                         snapshot={"ticker:A@BVMF", "ticker:B@BVMF"})
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert ("ticker:B@BVMF", "leave") in conn.events
    assert conn.rebuilt == 1
    assert s.applied == 1


def test_poll_bounded_resight_bumps_existing_proposal():
    # A poll-bounded change re-sighted next day with a SHIFTED effective date must bump
    # the EXISTING pending proposal (persistence accrues), not mint a new row daily.
    conn = _Conn()
    day1 = [MembershipChange("ticker:X@BVMF", LEAVE, date(2026, 6, 9), "b3:IBOV", POLL_BOUNDED)]
    stage_and_promote(conn, "ibov", day1, current_count=100, as_of_date=date(2026, 6, 9))
    assert len(conn.proposals) == 1
    day2 = [MembershipChange("ticker:X@BVMF", LEAVE, date(2026, 6, 10), "b3:IBOV", POLL_BOUNDED)]
    staged, _promoted = stage_and_promote(conn, "ibov", day2, current_count=100, as_of_date=D)
    assert len(conn.proposals) == 1  # no second row
    assert conn.proposal_bumps == ["ticker:X@BVMF"]
    assert staged.updated == 1 and staged.staged == 0


def test_stage_summary_carries_surprising_flag():
    conn = _Conn()
    changes = [MembershipChange(f"ticker:N{i}@BVMF", JOIN, D, "x", POLL_BOUNDED) for i in range(5)]
    staged, promoted = stage_and_promote(conn, "u", changes, current_count=10, as_of_date=D)
    assert isinstance(staged, StageSummary)
    assert staged.surprising is True and promoted == 0


def test_confirm_and_reverse_rebuild_projection():
    from sym.universe.gating import confirm_proposal, reverse_change

    class _ConfConn(_Conn):
        def execute(self, sql, params=None):
            if "FROM membership_proposal WHERE proposal_id" in sql:
                return _Cur(one=("ibov", "ticker:B@BVMF", "leave", D, "poll_bounded",
                                 "b3:IBOV", "pending"))
            return super().execute(sql, params)

    conn = _ConfConn()
    assert confirm_proposal(conn, 7) is True
    assert ("ticker:B@BVMF", "leave") in conn.events
    assert conn.rebuilt == 1

    conn2 = _Conn()
    assert reverse_change(conn2, "ibov", "ticker:B@BVMF", "leave", D) is True
    assert conn2.rebuilt == 1


def test_provider_leave_and_derived_leave_count_once(monkeypatch):
    # FMP-shaped case: a genuine leaver appears in the dated history (EXACT leave)
    # AND is absent from the declared snapshot. One departure must count once —
    # not double the leaver count and churn numerator.
    from sym.universe.registry import EXACT

    open_toks = ["ticker:B@BVMF"] + [f"ticker:M{i}@BVMF" for i in range(19)]
    conn = _Conn(open_tokens=open_toks)
    snapshot = set(open_toks) - {"ticker:B@BVMF"}
    provider = _Provider(
        [_join("ticker:M0@BVMF"),
         MembershipChange("ticker:B@BVMF", LEAVE, date(2026, 6, 9), "b3:IBOV", EXACT)],
        snapshot=snapshot,
    )
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert s.leavers == 1 and s.proposed == 1
    assert len(conn.proposals) == 1


def test_surprising_run_grants_no_persistence_credit():
    # Day 1 (calm): leave staged pending. Day 2 (churn-gated): the suspect run's
    # re-sighting must not bump persistence, must not corroborate, and must not
    # mint a duplicate row.
    conn = _Conn()
    day1 = [MembershipChange("ticker:X@BVMF", LEAVE, date(2026, 6, 9), "b3:IBOV", POLL_BOUNDED)]
    stage_and_promote(conn, "ibov", day1, current_count=100, as_of_date=date(2026, 6, 9))
    assert len(conn.proposals) == 1
    day2 = [MembershipChange(f"ticker:X{i}@BVMF", LEAVE, D, "b3:IBOV", POLL_BOUNDED)
            for i in range(30)] + [
        MembershipChange("ticker:X@BVMF", LEAVE, D, "b3:IBOV", POLL_BOUNDED)]
    staged, promoted = stage_and_promote(conn, "ibov", day2, current_count=100, as_of_date=D)
    assert staged.surprising is True and promoted == 0
    assert conn.proposal_bumps == []                       # no persistence credit
    assert not any(p[0] == "ticker:X@BVMF" and p[2] == "churn_threshold"
                   for p in conn.proposals)                # no duplicate row either
    assert staged.updated == 0


def test_rejected_change_resight_is_operator_only():
    # An operator-rejected change re-sighted under a shifted poll date re-stages
    # for VISIBILITY but with a reason that never auto-promotes.
    from sym.universe.gating import REASON_REJECTED_RESIGHT, is_promotable

    conn = _Conn()
    conn.rejected.add("ticker:X@BVMF")
    changes = [MembershipChange("ticker:X@BVMF", LEAVE, D, "b3:IBOV", POLL_BOUNDED)]
    stage_and_promote(conn, "ibov", changes, current_count=100, as_of_date=D)
    assert ("ticker:X@BVMF", "leave", REASON_REJECTED_RESIGHT) in conn.proposals
    assert is_promotable(
        REASON_REJECTED_RESIGHT, date(2026, 6, 1), D, 5, persist_days=2, min_corroborations=2
    ) is False


def test_empty_discoveries_still_run_promotion_heartbeat(monkeypatch):
    # All provider output re-states current membership -> zero discoveries, but the
    # daily run still promotes yesterday's now-persisted proposals.
    pending = [(
        8, "ticker:GONE@BVMF", "leave", D, "poll_bounded", "b3:IBOV",
        "awaiting_persistence", date(2026, 6, 7), date(2026, 6, 9), ["b3:IBOV"],
    )]
    conn = _Conn(open_tokens=["ticker:A@BVMF"], pending_rows=pending)
    provider = _Provider([_join("ticker:A@BVMF")], snapshot={"ticker:A@BVMF"})
    _patch_provider(monkeypatch, provider)
    s = run_monitor(conn, "ibov", as_of_date=D)
    assert s.applied == 1 and ("ticker:GONE@BVMF", "leave") in conn.events
