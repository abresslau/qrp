# Story E1: Scheduler-agnostic EOD pipeline

Status: review

## Story

As the operator,
I want a daily EOD pipeline that an external scheduler can drive without coupling sym to it,
so that I can run prices+returns+validation nightly under Airflow or Prefect (undecided) and switch freely.

## Acceptance Criteria

1. sym carries no Airflow/Prefect dependency; exposes idempotent steps + a coarse `sym eod` runner.
2. Daily core order: monitor -> delta -> benchmarks -> recompute -> validate; each error-isolated; critical steps (delta/recompute) fail the run (non-zero exit), non-critical surface but don't.
3. `--dry-run` plan, `--steps`/`--skip` selection.
4. Thin Airflow + Prefect example wrappers (shell out to `sym eod --steps <step>`); module-architecture doc.
5. DB-free tests + live dry-run/step verification.

## Tasks / Subtasks

- [x] Task 1: `eod.py` — `EodStep`/`DAILY_STEPS`, pure `select_steps`, `run_eod` (runner injection, error isolation, critical rollup), default runner dispatching to existing logic
- [x] Task 2: CLI `sym eod [--dry-run --steps --skip]` (ASCII output; exit 2 on critical failure)
- [x] Task 3: `docs/orchestration/` Airflow + Prefect wrappers + README; `docs/architecture-modules.md`; runbook §8
- [x] Task 4: DB-free tests + live verification

## Dev Notes

- Scheduler-agnostic: the orchestrator runs one task per step via `sym eod --steps <step>` (fine-grained retries) or `sym eod` (cron). sym never imports Airflow/Prefect.
- Reused the existing idempotent commands (monitor/delta/benchmarks/recompute/validate); tiered cadence keeps fundamentals (weekly) + snapshot-calendar (occasional) out of the daily default.
- CLI output is ASCII (a `✓`/`✗` version crashed the Windows cp1252 console — fixed).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `eod.py`: pure `select_steps` + `run_eod` (runner-injected, error-isolated, critical rollup) + default dispatcher; `sym eod` CLI.
- `docs/orchestration/` (Airflow DAG + Prefect flow + README, examples that shell out — zero deps in sym); `docs/architecture-modules.md` (sym_id + contract backbone, 3 future modules, data/repo strategy); runbook §8.
- **Live-verified:** `sym eod --dry-run` prints the 5-step plan; `sym eod --steps validate` ran validate (overall=fail surfaced, non-critical -> EOD ok, exit 0). Caught + fixed a Windows-console unicode crash.
- 6 DB-free tests; full suite 337 pass; ruff clean.

### File List
- `src/sym/eod.py` (new); `src/sym/cli.py` (eod command)
- `docs/orchestration/{README.md,airflow_dag.py,prefect_flow.py}` (new); `docs/architecture-modules.md` (new); `docs/runbook.md` (§8)
- `tests/test_eod.py` (new)
- `_bmad-output/implementation-artifacts/E1-eod-orchestration.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story E1: scheduler-agnostic EOD runner (`sym eod`) + orchestration wrappers + module-architecture doc. Live-verified. 6 DB-free tests; 337 pass. |
