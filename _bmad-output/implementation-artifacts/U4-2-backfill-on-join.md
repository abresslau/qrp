# Story U4.2: Historical backfill on join

Status: review

## Story

As the pipeline,
I want a new joiner's prior price history backfilled over its membership window,
so that a name added today does not leave a hole for the dates it was already a member.

## Acceptance Criteria

1. A member that joins with a past `valid_from` backfills its price history over its membership window (not just go-forward).
2. A re-run is idempotent and respects the per-figi cursor + immutability (AR-10).
3. DB-free tests cover the backfill-window computation; live-verified for a member with prior history.

## Tasks / Subtasks

- [x] Task 1: `floor_for(figi)` = member's earliest `valid_from`, threaded into `compute_window` as the backfill floor (AC #1)
- [x] Task 2: idempotency via the existing per-figi `pipeline_backfill_progress` cursor + immutable prices_raw (AC #2)
- [x] Task 3: DB-free window tests + live verification (AC #3)

## Dev Notes

- `universe_securities` returns each member's `min(valid_from)` as the backfill floor; `run_universe_load` passes it via `floor_for`. So a member that was in the index since 1994 backfills from 1994, not the generic 1990 floor or "today".
- Backfill reuses the existing resumable engine (cursor never advances without rows; a re-run skips up-to-date names), so idempotency + immutability come for free (AR-10).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `floor_for` hook in `run_load` + `universe_securities` `member_from` → backfill starts at the member's join, covering its whole membership window.
- DB-free tests assert `compute_window('backfill', None, floor=member_from, end)` == `(member_from, end)` and that an up-to-date member is skipped.
- Live: the sp500 dev/bridge runs exercised the selection + window path with real members (member_from values from 1994+).

### File List
- `src/sym/ingest/pipeline.py` (modified — floor_for)
- `src/sym/universe/ingest.py` (member_from selection)
- `tests/test_universe_ingest.py`

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U4.2: per-figi backfill floor from membership valid_from (joiner window backfill). |
