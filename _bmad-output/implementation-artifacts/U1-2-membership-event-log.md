# Story U1.2: Append-only membership event log

Status: review

## Story

As the pipeline,
I want membership changes recorded in an append-only event log,
so that history is immutable and corrections never mutate the past (AR-6/AR-10).

## Acceptance Criteria

1. A migration adds `membership_event` (`event_id`, `universe_id` FK → universe, `raw_identifier`, `change` ∈ {join, leave, correct}, `effective_date`, `effective_date_precision` ∈ {exact, poll_bounded}, `source`, `provenance` jsonb, `recorded_at`).
2. An append API: appending the same `(universe_id, raw_identifier, change, effective_date)` twice is **idempotent** (dedupe key); the table is **insert-only** (no update/delete path in the module).
3. Two sources reporting the same change at **conflicting effective dates** are both recorded (different `effective_date` → different rows) with provenance; source-precedence is resolved at projection (Story U1.4), documented here.
4. DB-free tests cover append validation + dedupe semantics; the idempotency + conflicting-dates behavior is verified live.

## Tasks / Subtasks

- [x] Task 1: `membership_event` migration (deploy/revert/verify + sqitch.plan) — FK to universe, `change`/`precision` CHECKs, dedupe UNIQUE `(universe_id, raw_identifier, change, effective_date)`, projection index; no updated_at (append-only) (AC #1, #2)
- [x] Task 2: validation helpers `validate_change` / `validate_precision` in registry (mirror `validate_kind`); `CHANGE_KINDS` / `PRECISIONS` constants (AC #2)
- [x] Task 3: append API `src/sym/universe/events.py` — `append_change` / `append_changes` (ON CONFLICT DO NOTHING → idempotent; insert-only) (AC #2, #3)
- [x] Task 4: DB-free tests (validation-before-DB, insert vs conflict via fake conn) + live verification (idempotent re-append; conflicting dates → 2 rows) (AC #4)

## Dev Notes

- **Append-only, immutable (AR-6/AR-10):** the event log is the *truth*; the `universe_membership` interval table (U1.4) is a projection of it. So `membership_event` has **no `updated_at` / no trigger** — rows are never updated. Corrections are a new `change='correct'` event, never a mutation. The module exposes only append + (later) read — no update/delete.
- **Dedupe key = `(universe_id, raw_identifier, change, effective_date)`** (UNIQUE). Appending the identical change twice is a no-op (`ON CONFLICT DO NOTHING` → `RETURNING` empty → `False`). Two sources reporting the *same* change at *different* effective dates are different rows (date differs) → both kept; precedence is a projection-time concern (U1.4), so U1.2 just records both with their `source`/`provenance`.
- **`effective_date_precision`** (`exact` | `poll_bounded`) carries from the provider's `MembershipChange` (Feynman finding: dated APIs = exact; snapshot diffs = poll_bounded).
- **Patterns:** migration style follows `currency.sql`/`price_storage.sql`; `change`/`precision` CHECKs mirror `securities_status_chk`; `event_id BIGINT GENERATED ALWAYS AS IDENTITY` (PG18). Validation helpers + typed errors mirror U1.1's `validate_kind`/`validate_universe_id`. DB-free-tests + live-verification per project convention.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.2]
- [Source: _bmad-output/planning-artifacts/briefs/brief-sym-2026-06-06/addendum.md#B (event log), ADR-8]
- [Source: src/sym/universe/registry.py — MembershipChange + validate_* pattern (U1.1)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `membership_event` append-only log deployed via Docker sqitch + verified: FK→universe, `change` CHECK ∈ {join,leave,correct}, `effective_date_precision` CHECK ∈ {exact,poll_bounded}, dedupe UNIQUE `(universe_id,raw_identifier,change,effective_date)`, projection index `(universe_id,effective_date,event_id)`. **No `updated_at`/trigger** — immutability is structural (corrections are `change='correct'` events).
- `validate_change`/`validate_precision` + `CHANGE_KINDS`/`PRECISIONS` constants added to `registry.py` (mirroring `validate_kind`); typed `InvalidMembershipEventError`.
- `events.py`: `append_change` (validates before DB; `ON CONFLICT DO NOTHING` → idempotent, returns True inserted / False duplicate) + `append_changes` (counts inserted). Module exposes **only append** — no update/delete path.
- **Verified live:** first append True, duplicate False (idempotent); two sources at conflicting effective dates (FMP 2024-03-15 exact + ETF 2024-03-18 poll_bounded) both recorded = 2 rows. Temp universe + events cleaned up.
- 170 tests pass (+6 in `test_universe_events.py`), ruff clean.

### File List

- `migrations/deploy|revert|verify/membership_event.sql` (new) — append-only event log.
- `migrations/sqitch.plan` (modified) — added `membership_event` change.
- `src/sym/universe/registry.py` (modified) — `CHANGE_KINDS`/`PRECISIONS`, `validate_change`/`validate_precision`, `InvalidMembershipEventError`.
- `src/sym/universe/events.py` (new) — `append_change` / `append_changes`.
- `tests/test_universe_events.py` (new, 6 tests) — append validation + insert/conflict contract.
- `_bmad-output/implementation-artifacts/U1-2-membership-event-log.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story U1.2: append-only `membership_event` log (immutable, AR-6/AR-10) + `append_change`/`append_changes` (idempotent dedupe) + change/precision validators. 170 tests pass, ruff clean; migration deployed + verified; idempotency + conflicting-date behavior verified live. Status → review. |
