# Story V7: `sym validate` orchestration, report & review integration

Status: review

## Story

As the operator,
I want one command that runs every invariant and tells me what's wrong,
so that cross-layer health is a single, CI-able check.

## Acceptance Criteria

1. `sym validate [--universe <id>]` runs V1–V6, prints a structured pass/warn/fail report, exits non-zero on any fail.
2. A `validation_run_log` row records each run; incomplete members surface in `universe review`.
3. DB-free tests for report/exit logic; live end-to-end run.

## Tasks / Subtasks

- [x] Task 1: `run_all` (V1–V6) + pure `summarize` + pure `format_report`
- [x] Task 2: `write_run_log` (validation_run_log) + `validate` (run → log → overall)
- [x] Task 3: CLI `sym validate --universe`; exit 2 on fail
- [x] Task 4: `universe review` "incomplete members" section (from the completeness log)
- [x] Task 5: DB-free tests + live end-to-end

## Dev Notes

- `run_all` orders V1 (writes the completeness log) first, then the read-only checks. Overall status = worst of all results; the CLI maps fail → exit 2 (CI/operator gate), warn/pass → 0.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/runner.py`: `run_all`, pure `summarize`/`format_report`, `write_run_log`, `validate`.
- `cli.py`: `sym validate [--universe]` (exit 2 on fail). `review.py`: "incomplete members" digest section + `is_clear` accounts for completeness fails.
- **Live end-to-end** `sym validate` → overall **FAIL** (exit 2), 5 pass / 1 warn / 3 fail of 9 checks. Passing: referential integrity, identity completeness, symbology uniqueness, projection reconciliation, readiness. The 3 fails are the known/in-flight items the suite is designed to surface:
  - completeness — fundamentals not yet loaded (deferred behind the running price backfill) + GICS not run for index members;
  - price_calendar_consistency — XTKS old-holiday off-calendar bars (calendar-vs-Yahoo);
  - unpriced_securities — 147 active unpriced (price backfill still in flight).
- 4 DB-free tests (summarize/format/exit); full suite **313 pass**, ruff clean. Completes Epic V.

### File List
- `src/sym/validate/runner.py` (new)
- `src/sym/cli.py` (modified — `validate` command)
- `src/sym/universe/review.py` (modified — incomplete-members section)
- `tests/test_validate_runner.py` (new)
- `_bmad-output/implementation-artifacts/V7-validate-orchestration.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V7: `sym validate` orchestration + report + run-log + review integration. Live end-to-end (exit 2 on fail). 313 tests pass. Completes Epic V. |
