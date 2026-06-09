# Story QL.5: Daily schedule for `sym eod` (Dagster as trigger only)

Status: done

## Story

As the **QRP owner-operator**,
I want **a daily Dagster schedule that runs the existing `sym eod` pipeline**,
so that **the end-of-day load runs on a cadence with run history + auto-retry — while I can always still run it (and every step) manually, exactly as before**.

## Context

Andre's firm constraints: **(1) manual running must stay easy and unchanged**; **(2) no complex
workflows in Dagster.** So Dagster is a *trigger + observer only* — it does NOT model the EOD steps
as a Dagster op/asset graph. `sym` already owns the daily sequence (`monitor → delta → benchmarks
→ recompute → validate`); the schedule simply fires the same `sym eod` CLI. Minimum scaffolding:
one op → one job → one schedule.

## Acceptance Criteria
1. **Minimal, not a workflow:** a single op shells out to `sym eod` (sym owns the step logic);
   one single-op job; one `ScheduleDefinition`. No multi-step Dagster DAG, asset-job, or sensor.
2. **Manual-first, unchanged:** `uv run sym eod` (and `sym eod --steps …` / `--dry-run`) still the
   real, Dagster-independent path; the per-step lineage assets remain individually materializable.
   The schedule runs the identical command.
3. **Safe by default:** schedule ships **STOPPED** (`DefaultScheduleStatus.STOPPED`) so nothing
   mutates data unattended until enabled in the Dagster UI (one toggle).
4. **Recovery/observability:** an op `RetryPolicy` auto-retries transient EOD failures; Dagster
   retains the run log (captured `sym eod` stdout) for retrieval.
5. **No regression:** `dagster definitions validate` passes; the job + schedule register; the
   31-asset catalog + lineage console are unaffected.
6. **Any-date, consistent naming:** the pipeline runs for an arbitrary business date via a single
   canonical name — CLI `sym eod --as_of_date YYYY-MM-DD` and Dagster launchpad `as_of_date` —
   defaulting to today when omitted. The name matches the documented `as_of_date` column convention
   end-to-end (`--as_of_date` → `as_of_date` var → `run_eod(as_of_date=…)`); the legacy `--asof`
   flags on the other date-bearing subcommands were reconciled to `--as_of_date` too. Invalid dates
   are rejected (exit 1).
7. Reviewed.

### Out of scope
- Modeling EOD steps as Dagster ops/assets (explicitly NOT wanted).
- Auto-enabling the schedule; alerting/notifications; console schedule UI (Dagster UI owns it).

## Tasks / Subtasks
- [x] `schedules.py`: `sym_eod` op (runs `sym eod`) + `sym_eod_job` + `sym_eod_daily` schedule (STOPPED)
- [x] Wire jobs + schedules into `definitions.py`
- [x] Verify (validate, schedule registers, manual path intact) + review

### Review Findings
_Focused review 2026-06-09. Constraint adherence "exemplary"; no blockers._
- [x] [Review][Patch] on failure, log the stdout `[FAIL] <step>` detail at error level (the actionable detail is on stdout, not stderr) [schedules.py]
- [x] [Owner][Critical] **explicit `execution_timezone`** added — `America/New_York` (US equity close, DST-aware), cron `30 18 * * 1-5`. Now a standing convention: every schedule MUST declare a timezone (memory: feedback_schedule_explicit_timezone).
- [x] [Review][Note] `sym eod` exits non-zero only on a *critical* step (delta/recompute) failure — by sym's "a hiccup shouldn't fail the night" design — so a `validate`/monitor hiccup won't turn the run red; its status is in the captured log. Documented in the op docstring (kept sym's exit-code contract; did not add stdout-parsing).

## Dev Notes
- Reuse `sym_run.repo_root`; run `[sys.executable, "-m", "sym.cli", "eod"]` via subprocess, log
  stdout, raise on non-zero (so Dagster marks the run failed + retries).
- Cron default: weekdays after close, editable (`30 22 * * 1-5`, UTC). Enable in UI when ready.
- Manual paths (always available, no Dagster needed): `uv run sym eod`; in Dagster UI, launch the
  `sym_eod` job; or materialize individual sym assets (each runs its own `sym` subcommand).

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Completion Notes List
- Minimal as required: one op (`sym_eod` → `sym eod` CLI) → one job (`sym_eod_job`) → one schedule
  (`sym_eod_daily`). No Dagster op-graph/asset-job/sensor; sym owns the step sequence.
- **Explicit timezone** `America/New_York`, cron `30 18 * * 1-5` (weekday evenings after US close),
  `default_status=STOPPED`, `RetryPolicy(max_retries=2, delay=300)`.
- Verified: `dagster definitions validate` passes; reload shows `sym_eod_daily` (cron + tz +
  STOPPED) + `sym_eod_job`; 31-asset catalog + lineage console unaffected. Reviewed; patches applied.
- Manual paths unchanged: `uv run sym eod` (+ `--steps`/`--dry-run`); per-step sym assets still
  individually materializable; or launch `sym_eod_job` in the Dagster UI.
- **`as_of_date` parameterization (AC6):** `sym eod` gained `--as_of_date YYYY-MM-DD` (default
  today) threading through `run_eod(as_of_date=…)` → `_default_runner` to every step (delta cursor,
  benchmark/returns window end, fx end). Renamed `run_eod`'s misleading `today` param → `as_of_date`
  (it accepts any date, not just today). Reconciled the 5 other `--asof` flags (fx convert/restate,
  universe members/coverage/benchmarks) → `--as_of_date` for one consistent operator vocabulary
  matching the `as_of_date` column convention. Dagster `EodConfig.as_of_date` passes it through.
  Verified: past-date plan, default, invalid-date rejection (exit 1), 6 eod tests, validate.
  - *Deferred (not user-facing):* deeper engine params still use `asof`/`today` internally
    (`ingest.pipeline`, `returns.windows/loader`, `universe.gating`) — a standard term, no CLI/column
    surface; a full internal rename is a larger core refactor left as optional follow-up.

### File List
- `packages/lineage/src/lineage/schedules.py` (new), `definitions.py` (jobs + schedules wiring)
- `packages/sym/src/sym/cli.py` (`--as_of_date` flags), `eod.py` (`run_eod` `as_of_date` param)
- `docs/runbook.md` (`--asof` → `--as_of_date`)
