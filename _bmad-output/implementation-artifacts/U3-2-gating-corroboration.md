# Story U3.2: Sanity-gating, corroboration, and reversible audit

Status: review

## Story

As the pipeline,
I want surprising membership changes gated and corroborated before they are recorded,
so that a bad parse or vandalized source can't silently corrupt a universe (AR-9 two-stage).

## Acceptance Criteria

1. A monitor diff churning more than a tunable guard threshold is flagged for review, **not** auto-applied.
2. A detected change must **persist N days or be confirmed by a second source** before it is recorded.
3. A recorded change later found wrong is reversed by an appended corrective event (appended, reversible audit — never destructive).
4. DB-free tests cover threshold gating + corroboration + reversal.

## Tasks / Subtasks

- [x] Task 1: pure decision logic — `churn_ratio`, `is_surprising`, `is_promotable` (churn always operator-only; else persistence OR corroboration) (AC #1, #2)
- [x] Task 2: `stage_changes` (upsert proposals; first-sight insert, repeat bumps seen_count + records corroborating source) over `membership_proposal` (AC #1, #2)
- [x] Task 3: `promote_ready_proposals` (append to event log + mark confirmed) + `stage_and_promote` orchestration (AC #2)
- [x] Task 4: operator `confirm_proposal`/`reject_proposal`; `reverse_change` (appended `correct` event) (AC #3)
- [x] Task 5: DB-free tests (pure logic) + live verification of staging/promotion/corroboration/reversal (AC #4)

## Dev Notes

- Two-stage (AR-9): all monitor-discovered changes are *staged* in the mutable `membership_proposal` table; only promotion appends to the immutable event log. Surprising churn (`reason='churn_threshold'`) is never auto-promoted — operator-only via `universe review` (U3.4).
- Corroboration = a *different* source seeing the same `(member, change, date)` (recorded in `corroborating_sources`); persistence = `today - first_seen >= persist_days`. Either promotes a non-churn proposal.
- Reversal appends a `change='correct'` event at the wrong change's effective date — the projection state machine toggles the interval (closes a wrong open / re-opens a wrong close), so corrections are a reversible appended audit trail.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `gating.py`: pure `churn_ratio`/`is_surprising`/`is_promotable`; DB `stage_changes`, `promote_ready_proposals`, `stage_and_promote`, `pending_proposals`, `confirm_proposal`, `reject_proposal`, `reverse_change`.
- **Live-verified** on a synthetic universe (cleaned up after): churn (10 changes vs current 1) → 10 staged, 0 promoted, reason=churn_threshold; ordinary change → not promoted same-day, promoted on day 3 (event-log row appears); two-source corroboration → promoted same-day; reversal → `correct` event appended.
- 6 DB-free tests; ruff clean.

### File List
- `src/sym/universe/gating.py` (new)
- `tests/test_universe_gating.py` (new)
- `_bmad-output/implementation-artifacts/U3-2-gating-corroboration.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U3.2: sanity-gating (churn threshold), corroboration/persistence promotion, reversible corrective-event audit. Live-verified end-to-end. 6 DB-free tests. |
