# Story V5: Membership projection reconciliation

Status: review

## Story

As the operator,
I want `universe_membership` proven to match the event log,
so that a stale or hand-edited projection can never drift from the truth.

## Acceptance Criteria

1. A fresh `project_membership(events)` equals the stored `universe_membership` intervals (drift → fail, naming FIGIs).
2. `pit_valid_from` is not set earlier than the earliest recorded leave (survivorship-boundary consistency).
3. Reuses the U1.4 projector + property test; DB-free on synthetic, live-verified.

## Tasks / Subtasks

- [x] Task 1: pure `reconcile(stored, projected)` interval set-compare per FIGI
- [x] Task 2: `check_projection_reconciliation` — re-project each universe's log vs stored; compare
- [x] Task 3: pit-honesty check (pit not before earliest recorded leave, using all leave events)
- [x] Task 4: DB-free tests + live verification

## Dev Notes

- Reuses `sym.universe.projection.project_membership` + `_membership_events` (resolved events) for the interval compare; the pit check queries `membership_event` for the earliest leave among **all** events (resolved or not), matching how `refresh` derives pit — an early version compared against resolved-only leaves and produced spurious warns.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/projection.py`: pure `reconcile` (per-FIGI interval set-diff) + `check_projection_reconciliation` (re-project vs stored + pit-honesty).
- **Live-verified: `pass`** — 0 drift across all 12 universes (stored membership exactly matches a fresh re-projection); 0 pit warnings after fixing the leave-set used for the pit comparison.
- 4 DB-free tests; ruff clean.

### File List
- `src/sym/validate/projection.py` (new)
- `tests/test_validate_projection.py` (new)
- `_bmad-output/implementation-artifacts/V5-projection-reconciliation.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V5: projection reconciliation (re-project vs stored) + pit-honesty. Live: 0 drift, 0 warnings. 4 DB-free tests. |
