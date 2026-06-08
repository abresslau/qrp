# Story U3.4: `universe review` operator digest

Status: review

## Story

As Andre,
I want a single `universe review` surface for everything needing my attention,
so that gated changes, stale monitors, and quality alarms never pile up unseen.

## Acceptance Criteria

1. `universe review` lists in one place: pending sanity-gated changes (with confirm/reject), stale monitors, aging-unresolved members, accuracy-gate alarms.
2. Confirming a gated change appends it to the log (un-gating); rejecting records a rejection — both appended events, never a mutation.
3. DB-free tests cover digest assembly + confirm/reject; live-verified end-to-end with a synthetic gated change.

## Tasks / Subtasks

- [x] Task 1: `build_digest` assembling the four attention sources (pending proposals, stale monitors, aging-unresolved, accuracy alarms) (AC #1)
- [x] Task 2: `aging_unresolved` query (retained-but-old members) + pure `format_digest` (AC #1)
- [x] Task 3: CLI `universe review` / `universe monitor` / `universe confirm [--reject]` (AC #1, #2)
- [x] Task 4: DB-free tests (format/clear/sections) + live verification of digest + confirm/reject (AC #3)

## Dev Notes

- The digest reuses U3.1–U3.3 building blocks (`pending_proposals`, `stale_monitors`, `accuracy_alarms`) plus `aging_unresolved`; `format_digest` is pure and unit-tested.
- Confirm = `gating.confirm_proposal` (appends the change + marks confirmed); reject = `gating.reject_proposal` (records rejection, nothing appended) — both leave the event log append-only.
- `universe monitor <id>` exposes the U3.1 monitor on the CLI so an operator (or a scheduler) can run maintenance and clear staleness.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `review.py`: `Digest` (+`is_clear`), `aging_unresolved`, `build_digest`, pure `format_digest`.
- `cli.py`: `universe review`, `universe monitor`, `universe confirm [--reject]`.
- **Live-verified:** `sym universe review` renders all four sections (showed sp400/sp600 stale-never-monitored); a synthetic gated proposal → confirm appends 1 event-log row, reject appends none, statuses {confirmed, rejected}. Cleaned up.
- 4 DB-free tests; ruff clean.

### File List
- `src/sym/universe/review.py` (new)
- `src/sym/cli.py` (modified — review/monitor/confirm subcommands)
- `tests/test_universe_review.py` (new)
- `_bmad-output/implementation-artifacts/U3-4-review-digest.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U3.4: universe review operator digest + monitor/confirm/reject CLI. Live-verified. 4 DB-free tests. Completes Epic U3. |
