# Story 2.6: Pipeline run logging and monitoring surface

Status: review

## Story

As an operator,
I want each run to write a queryable log record,
so that the pipeline log is the primary operational monitoring surface in v1.

## Acceptance Criteria

1. **Given** a run, **Then** a `pipeline_run_log` record captures timestamp, mode, attempted, succeeded, failed/skipped, and anomaly counts; `status = success` (0 errors) or `partial` (with failure count).
2. **Given** OI-3, **Then** a deliberate decision is recorded: `pipeline_run_log` (run-level counts) is separate from the per-figi `pipeline_backfill_progress` cursor.
3. **Given** DBeaver, **Then** the log is queryable with no external logging infra in v1 (NFR-7).

## Tasks / Subtasks

- [x] Task 1: `pipeline_run_log` migration (AC: #1, #2, #3)
  - [x] columns: run_id, mode, source, started_at, finished_at, attempted, loaded, skipped, errored, rows_written, anomaly_flags, gaps, status, detail, created_at
  - [x] CHECKs: `status IN (success, partial)` and `(errored = 0) = (status = success)`; counts ≥ 0; finished ≥ started; index on started_at
  - [x] table comment recording the OI-3 decision (run-level log vs per-figi cursor); revert + verify; sqitch.plan entry
- [x] Task 2: wire logging into `run_load` (AC: #1)
  - [x] capture started_at/finished_at; write one `pipeline_run_log` row from the `LoadSummary`; `status` derived (`partial` iff errored>0); `detail` = first few errors
  - [x] `LoadSummary.status` property + `run_id`; `now` injectable for tests
- [x] Task 3: CLI surfaces the run id (AC: #3)
  - [x] `backfill`/`delta`/`dev` print the logged `run #N [status]`
- [x] Task 4: tests in `tests/test_pipeline.py`
  - [x] `LoadSummary.status` (success/partial); `_write_run_log` writes the record + returns run_id; `run_load` logs a row with the right status (success on clean, partial on a failing figi)

## Dev Notes

- **OI-3 resolution (AC #2):** `pipeline_run_log` is **run-level** (one row per backfill/delta/dev invocation, with aggregate counts + status) and is deliberately *separate* from `pipeline_backfill_progress`, which is **per-figi resume state** (cursor + status). Different grains, different purposes; recorded in the table comment.
- **NFR-7 / no external infra:** the log is a plain table queried in DBeaver — no logging service in v1. It's the primary operational surface.
- **Append-only:** a run record is written once at the end of `run_load`; no `updated_at` (it's never updated — `started_at`/`finished_at` are the meaningful times, `created_at` is the write audit).
- **Scope:** logs the price-load runs (`run_load`: backfill/delta/dev). `resolve`/`classify`/`snapshot-calendar` could log later; FR-8/AR-13 is about the price pipeline.
- **Durability:** `run_load` already runs `conn.autocommit = True`, so the final log INSERT commits immediately even though it's written after the per-figi loop.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.6: Pipeline run logging and monitoring surface]
- [Source: _bmad-output/planning-artifacts/epics.md#OI-3 — FR-8 run-log decision]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `pipeline_run_log` is run-level (one row per `run_load` invocation); `status` derived `partial` iff any figi errored, enforced both in code and a DB CHECK `(errored = 0) = (status = 'success')`. Append-only (no updated_at).
- **OI-3 recorded** in the table comment: run-level log vs the per-figi `pipeline_backfill_progress` cursor — different grains, kept separate.
- `run_load` writes the log after the loop (committed immediately via the existing autocommit); the CLI prints `run #N [status]`.
- **Verified live:** `sym delta` → run #1 [success], `sym dev` → run #2 [success], both queryable in `pipeline_run_log` with timings/counts. 107 tests pass, ruff clean.

### File List

- `migrations/deploy|revert|verify/pipeline_run_log.sql` (new) — run-level log table.
- `migrations/sqitch.plan` (modified) — `pipeline_run_log` change.
- `src/sym/ingest/pipeline.py` (modified) — `_write_run_log`, `LoadSummary.status`/`run_id`, `run_load` logs the run.
- `src/sym/cli.py` (modified) — prints `run #N [status]`.
- `tests/test_pipeline.py` (modified) — status + run-log tests.
- `_bmad-output/implementation-artifacts/2-6-run-logging.md` (new) — this spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.6: `pipeline_run_log` run-level monitoring table (FR-8, NFR-7); `run_load` logs each run with derived success/partial status; CLI surfaces `run #N`. OI-3 (run-log vs cursor) recorded. Verified live. Status → review. |
