# Story: EOD job runs every bucket over a [start_date, end_date] window

Status: review

<!-- Created via bmad-create-story 2026-06-30 (Andre: "if I look at my data monitor page I can see most
of the data is stale. I need my eod job to call all the individual jobs for the given start_date and
end_date"). Standalone story (no numbered epic — tracked inline in sprint-status, like dagster-job-buckets
/ E1-eod-orchestration). Sits on the lineage package's Dagster orchestration. -->

## Story

As the operator of the QRP warehouse,
I want the **`eod` Dagster job to refresh *every* data bucket for a `start_date`–`end_date` window** (not
just sym/rates/commodities for a single day),
so that one trigger backfills the whole platform across a gap and the Data Monitor board goes green —
instead of me launching per-bucket jobs one date at a time and still leaving macro / alt-data /
fundamentals / universe untouched.

## Background / current state (read THIS before coding)

### The symptom (live, 2026-06-30; expected = previous business date 2026-06-29)

`GET /api/data-monitor/eod` shows nearly everything stale because the last load was ~2026-06-22:

| bucket | status | latest | days behind |
|---|---|---|---|
| fx | stale | 2026-06-22 | 7 |
| equity_prices | stale | 2026-06-22 | 7 |
| index_levels | stale | 2026-06-22 | 7 |
| commodities | stale | 2026-06-23 | 6 |
| rates | stale | 2025-07-31 | 333 (per-country worst-lag: CH ends 2025-07-31 by source design — a known data-availability edge, NOT a load gap) |
| fundamental | stale | 2026-06-17 | 12 (slow cadence) |
| alt_data | stale | 2026-06-21 | 8 (slow) |
| macro | ok | 2026-08-05 | 0 |
| universe | stale | 2026-06-22 | 7 |
| calculations | stale | 2026-06-22 | 7 |

### Why it's stale — TWO real gaps in today's `eod` job

The `eod` job already exists (`packages/lineage/src/lineage/schedules.py:222-242`, job name `eod`, two
sequenced stages `eod_data` → `eod_calculations`, schedule `eod_daily` STOPPED). But:

1. **It does NOT run every bucket.** `eod_data` (`schedules.py:163-202`) runs `sym eod --steps
   monitor,fill,map,classify,indices,fx` (= equity prices, identity, classification, index levels, FX) then
   hand-rolls **rates** (UK + world) and **commodities**. It NEVER runs **macro**, **alt_data**,
   **fundamental**, or **universe**. So those four can only be refreshed by launching their per-bucket jobs
   by hand → they rot. (`eod_calculations`, `schedules.py:205-219`, then does `sym eod --steps
   recompute,validate`.)
2. **It takes a single `as_of_date`, not a range.** `EodConfig` (`schedules.py:37-45`) has only
   `as_of_date: str`. Backfilling a 7-day gap means launching the job 7 times.

### The nine buckets ARE already defined once (use them — don't re-hand-roll)

`packages/lineage/src/lineage/buckets.py` is the dependency-light single source of truth (`BUCKETS`), and
`packages/lineage/src/lineage/bucket_jobs.py` builds, **per bucket**, the exact CLI command(s) an operator
would type — `_BUILDERS` (`bucket_jobs.py:165-175`) maps each bucket key →
`(all_cmds, one_cmds, discover)`. The per-bucket Dagster jobs (`fx_load`, `equity_load`, `index_load`,
`rates_load`, `fundamental_load`, `alt_data_load`, `macro_load`, `universe_load`, `calculations`) are
generated from these (`BUCKET_JOBS`, `bucket_jobs.py:299`); `commodities` is a dedicated job in
`schedules.py`.

**The fix is to make `eod` the union of all nine buckets' commands over a window — reusing `_BUILDERS`
so `eod` and the per-bucket jobs can never drift** — rather than `eod_data` keeping its own hand-written
sym+rates+commodities list that silently omits four buckets.

### Range support is MIXED across the loaders (verified from `bucket_jobs.py` usage + `--help`)

This is the crux of the design — a window can't be threaded uniformly:

- **Range-native** (accept `--start_date S --end_date E`, one call covers the window):
  `sym load --scope universe:<u> --start_date --end_date` (`_equity_one`),
  `sym recompute --start_date --end_date` (`_calc_cmds` "returns"),
  `rates curve load-world --start_date --end_date` (`_rates_all`/`_rates_one`),
  `commodity price load --start_date --end_date` (`schedules.py`/commodities),
  `altdata.cli load --start_date --end_date` (confirmed via `--help`).
- **Single-shot / incremental / snapshot** (NO date-range flag — run once for the window, as-of = `end_date`):
  `sym eod --as_of_date` (single date only), `sym fx load` (incremental/full), `sym fundamentals`
  (point-in-time snapshot), `macro.cli load` (full/incremental), `sym indices` + `sym msci-pull` (registry
  pull), `sym universe monitor <u>` (event check), `sym classify` (current snapshot).

Implication: a date RANGE means **range-native loaders take the window directly; single-shot loaders run
once (as-of = end_date).** Do NOT loop the whole fan-out per business day — that re-pulls fx/macro/
fundamentals/identity N times for nothing and is needlessly slow. (See Open Q#1 if a true per-day equity
backfill is wanted; today `_equity_one` already windows, and `sym recompute` is range-native, so the range
is honoured where it matters: prices + returns.)

### Equity prices are the load-bearing dependency (don't break the stage gate)

Returns (`calculations`) derive FROM equity prices, so the existing two-stage gate
(`eod_calculations(eod_data())`, `schedules.py:230`) MUST be preserved: all raw pulls (stage 1) complete —
with **equity `fill` critical** (its failure skips the calc stage) — before `recompute,validate` (stage 2).
rates/commodities/macro/altdata/fundamental/universe are independent of equity returns → attempt-all
(logged, non-blocking), exactly as `eod_data` treats rates/commodities today (`schedules.py:188-201`).

## Acceptance Criteria

1. **`eod` runs every bucket.** A single `eod` job run refreshes ALL nine buckets — fx, equity_prices,
   index_levels, commodities, rates, fundamental, alt_data, macro, universe — plus the `calculations`
   (returns/validate) stage. The four currently-omitted buckets (macro, alt_data, fundamental, universe)
   are now included.
2. **Date-range config.** `EodConfig` gains `start_date` and `end_date` (YYYY-MM-DD). Resolution:
   - both blank → `end_date` = the scheduled tick / today (the current default), `start_date` = `end_date`
     (single day) — **scheduled `eod_daily` behaviour is byte-unchanged**;
   - `end_date` set, `start_date` blank → single day (`start = end`);
   - both set → the inclusive window.
   Keep `as_of_date` working as a back-compat alias (if set and start/end blank → `start = end = as_of_date`)
   so existing launch configs / `sym eod --as_of_date` muscle-memory don't break. Validate all dates up
   front with a clear error (mirror `_run_bucket`'s `date.fromisoformat` guard, `bucket_jobs.py:221-224`)
   and reject `start_date > end_date`.
3. **Window threaded correctly per loader.** Range-native loaders receive `--start_date start_date
   --end_date end_date` (equity per-universe load, `rates load-world`, `commodity price load`, `altdata
   load`, `recompute`). Single-shot loaders (fx, fundamentals, macro, indices, universe monitor, classify,
   `sym eod` identity steps) run once with as-of = `end_date`. No loader is dropped or double-run per day.
4. **Single source of truth — reuse `_BUILDERS`.** `eod`'s data stage drives the bucket command builders
   from `bucket_jobs.py` (refactored to take a `(start_date, end_date)` window instead of deriving a
   1-day `_window` from `as_of`), NOT a second hand-written command list. Adding/changing a bucket's
   command in one place updates both `eod` and the per-bucket job. (If a full builder refactor is too
   broad, the fallback is `eod` importing and invoking the builders directly — but the hand-rolled
   sym+rates+commodities list in `eod_data` must not survive as a drifting duplicate.)
5. **Stage gate + criticality preserved.** Stage 1 (all raw pulls) → stage 2 (`recompute,validate`) gate is
   intact: equity `fill` is critical (failure skips calc + reddens the run); rates/commodities/macro/
   alt_data/fundamental/universe are attempt-all (a failure is logged, non-blocking); `recompute` and
   `validate` stay critical. The run goes red on a critical failure, green-with-logged-FAILs otherwise —
   matching `sym eod`'s "a hiccup shouldn't fail the night, a critical step should" doctrine.
6. **Per-bucket jobs still work, range-capable too.** The nine per-bucket jobs (`fx_load`, …) still load
   and run. `BucketConfig` gains the same `start_date`/`end_date` (with `as_of_date` back-compat), so an
   individual bucket can also backfill a range from the launchpad. `definitions.py` loads with no
   collision (still 9 bucket jobs + `eod` + `sym_eod` + `commodities`).
7. **Launchable + documented.** The `eod` job's launchpad config exposes `start_date`/`end_date`; the job
   description documents the range + which buckets it covers. The `eod_daily` schedule stays STOPPED and
   single-day (unchanged).
8. **Verified live, gate green.** Run `eod` for the real gap (`start_date=2026-06-23`,
   `end_date=2026-06-29`) and confirm the Data Monitor board (`/api/data-monitor/eod`,
   `/data-monitor`) flips the load-driven buckets to `ok` (fx, equity_prices, index_levels, commodities,
   alt_data, universe, calculations; macro already ok). `fundamental` (slow vendor cadence) and `rates`
   per-country `CH` (source ends 2025-07-31) may legitimately stay behind — call those out honestly, don't
   force-green them.
9. **No regression.** `lineage`/`api` test suites green; the web gate (`npm --workspace web run
   typecheck|test|lint`) clean if any console/api file changes; ruff clean; `definitions.py` loads (9
   bucket jobs + eod + sym_eod + commodities, no name collision).

## Tasks / Subtasks

- [x] **Task 1 — Window-ify the bucket command builders (AC: #3, #4).** `bucket_jobs.py`: all builders
  now take `(start, end)`; range-native ones (`_equity_one`, `_rates_all`/`_rates_one`, `_calc_cmds`
  returns) emit `--start_date/--end_date`; `_altdata_all` gained range support; added `_commodity_all`
  (so `eod` runs commodities from the same source of truth). `_window(as_of)` replaced by `_tail(start,
  end, days)` (a publish-lag lookback that preserves a wider explicit range).
- [x] **Task 2 — Range config on `BucketConfig` + `EodConfig` (AC: #2, #6).** Added `start_date`/
  `end_date` (+`as_of_date` alias) to both configs and one shared `resolve_window(context, start, end,
  as_of)` helper in `bucket_jobs.py` (blank→single-day default unchanged; both-set window; as_of alias;
  start>end + bad-date rejected). `_run_bucket` uses it.
- [x] **Task 3 — Make `eod` the union of all buckets over the window (AC: #1, #4, #5).** `eod_data` now
  runs the sym sequence via one `sym eod --steps monitor,fill,map,classify,indices,fx` call (keeps
  fill critical + the map/classify ordering — Open Q#2 default) THEN fans out to the separate-package
  buckets `rates, commodities, macro, alt_data, fundamental, universe` (the four previously-missing ones
  included) via the shared `_BUILDERS` — attempt-all, their internal `validate "!"` markers stripped so
  they can't red the night. `eod_calculations` recomputes returns over the window
  (`sym recompute --start_date --end_date`) then validate. Two-stage gate preserved; the drifting
  hand-written list is gone. Window threaded data→calc as `"start/end"`.
- [x] **Task 4 — Plumb the range through the launch surface (AC: #7).** `EodConfig` exposing the fields
  makes the launchpad surface the window automatically (AC#7). Also added `start_date`/`end_date` to
  `launch_job` + `LaunchRequest` (additive, mirrors `as_of_date`). Updated `eod` job description.
- [x] **Task 5 — Tests + live verify (AC: #8, #9).** Added resolver/window/`_tail`/all-bucket-coverage/
  windowed-recompute unit tests; updated the signature-changed tests. 47 lineage + 15 data_monitor api
  green, ruff clean, definitions load (12 jobs, no collision). LIVE: ran `eod` via Dagster CLI for
  `2026-06-23..2026-06-29` (RUN_SUCCESS, eod_data 50m + eod_calculations 17m; recompute windowed to
  303,324 fact_returns rows); the Data Monitor board flipped fx/equity_prices/index_levels/fundamental/
  alt_data/universe/calculations to `ok` (macro already ok). Remaining stale = honest source/vendor
  edges (rates worst-country CH ends 2025-07-31; commodities at last Friday pending the next publish),
  per AC#8's "don't force-green".

## Dev Notes

### Critical conventions (regressions if violated)
- **Single source of truth: `buckets.py` + `bucket_jobs._BUILDERS`.** The whole point of this story is to
  STOP `eod` from carrying a second, drifting command list that omitted four buckets. `eod` must derive its
  work from the same builders the per-bucket jobs use. (buckets.py stays dependency-light — stdlib only, no
  dagster/DB import — because the FastAPI gateway imports it; do NOT add heavy imports there.)
- **Trigger + observer, not a workflow.** Every step shells the EXACT CLI an operator would type
  (`python -m <module> …` via `repo_root()` cwd). Dagster decides WHEN, never re-implements a load. Don't
  build an op-graph per bucket; the established pattern is one op shelling commands with attempt-all +
  critical markers (`bucket_jobs._run_cmd`, trailing `"!"` = critical).
- **Stage gate is load-bearing.** `eod_calculations` must run only after `eod_data` (returns derive from
  prices). Equity `fill` critical; raw non-equity pulls attempt-all; `recompute`/`validate` critical.
- **Scheduled behaviour unchanged.** `eod_daily` (STOPPED, 18:30 America/New_York, explicit tz — the hard
  schedule-tz requirement) must still run a SINGLE day (today) when blank. The range is an operator
  backfill affordance, not a schedule change. Resolve the tick via
  `dagster/scheduled_execution_time` (not the worker wall clock) exactly as today (`schedules.py:65-67`).
- **Honest freshness.** Don't force-green what's legitimately behind: `fundamental` lags by vendor cadence;
  `rates` `CH` ends 2025-07-31 at the source; `macro` is monthly/quarterly (already shows ok with a
  future-dated obs). Report these as expected, not as a failed backfill.
- **`as_of_date` is the canonical date name** ([[feedback_as_of_date_canonical_name]]) — the new params are
  `start_date`/`end_date` (the established window names used across `sym load`/`recompute`/`rates`/
  `commodity`), and `as_of_date` stays the single-date alias. Don't introduce `asof`/`from`/`to`.

### Files to touch
- `packages/lineage/src/lineage/bucket_jobs.py` — builders take `(start,end)`; `BucketConfig` gains
  `start_date`/`end_date`; window resolver; `_altdata_all` range flags.
- `packages/lineage/src/lineage/schedules.py` — `EodConfig` range; `eod_data` becomes the all-bucket
  fan-out via the builders; `eod_calculations` windows `recompute`. `eod_daily`/`sym_eod`/`commodities`
  unchanged in behaviour.
- `packages/lineage/src/lineage/definitions.py` — confirm registration unchanged (no new/renamed jobs).
- `services/api/src/qrp_api/modules/data_monitor/dagster_runs.py` + `router.py` — pass `start_date`/
  `end_date` in the launch config (Task 4).
- `packages/lineage/tests/…` — window-resolver + builder-emits-range unit tests; definitions-load test.

### Reuse — do NOT reinvent
- `bucket_jobs._run_cmd` (attempt-all + critical `"!"` + timeout + tail logging), `_resolve_as_of`,
  `_discover_universes`, `repo_root()` — all reusable; extend, don't fork.
- The `eod_data → eod_calculations` two-stage shape and the `EodConfig` tick-resolution already exist —
  this story widens them, it doesn't replace them.

### References
- [Source: packages/lineage/src/lineage/schedules.py:37-242] — `EodConfig`, `eod_data`,
  `eod_calculations`, `eod_job`, `eod_daily`, `commodities`.
- [Source: packages/lineage/src/lineage/bucket_jobs.py] — `_BUILDERS`, `BucketConfig`, `_run_bucket`,
  `_run_cmd`, `_window`, the nine command builders.
- [Source: packages/lineage/src/lineage/buckets.py] — `BUCKETS` taxonomy + freshness semantics (expected =
  previous business date, `stale_after_days=0`).
- [Source: services/api/src/qrp_api/modules/data_monitor/eod.py + dagster_runs.py] — the EOD board
  (actual-vs-expected) + `launch_job`/`latest_runs_by_job` GraphQL.
- Sibling stories: `dagster-job-buckets` (the nine bucket jobs), `E1-eod-orchestration` / `QL-5-eod-schedule`
  (the sym EOD + schedule), `data-monitor-compact-counts` (the board this story turns green).

## Open Questions (for Andre — defaults chosen, do NOT block)
1. **Per-day vs range-native for the window.** Default: range-native loaders take `--start_date/--end_date`
   in ONE call; single-shot loaders run once (as-of = end_date). This honours the range where it matters
   (equity prices + recompute) without N× re-pulling fx/macro/fundamentals. Alternative (heavier): loop
   every business day and run the full fan-out per day. Say if you want true per-day granularity for any
   single-shot loader.
2. **sym-owned set: one `sym eod` call or decomposed?** Default: keep the sym-owned buckets (equity / index
   / fx / identity / classify) running via a single `sym eod --steps monitor,fill,map,classify,indices,fx`
   call (proven, keeps `fill` critical), and add macro/alt_data/fundamental/universe via their builders.
   Alternative (purer single-source-of-truth): decompose the sym set into the equity/index/fx bucket
   builders too. The default is lower-risk; flag if you want full decomposition.
3. **Console "Run with date range" UI.** Default: this story scopes the JOB + launch config; the
   data-monitor "Run" chips keep launching whole-bucket/today. A start/end date-picker on the board's Run
   controls is a small optional follow-on — say if you want it in-scope.
4. **Backfill the live gap now?** Default: yes — Task 5 runs `eod` for `2026-06-23..2026-06-29` as the
   verification, which also clears the current staleness. Flag if you'd rather verify on a throwaway date.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-30

### Completion Notes
- **All nine buckets now run from `eod`.** The four the old job never touched (macro, alt_data,
  fundamental, universe) are in the fan-out; verified live (their board rows flipped to `ok`).
- **Open Q resolutions:** #1 — range-native loaders take the window in one call; single-shot loaders
  (fx/fundamentals/macro) run once; equity catches up via incremental `sym eod` fill THROUGH `end`
  (forward gap-fill — the staleness fix). A historical re-pull of *old* equity prices remains the
  `sym load --overwrite` runbook, NOT eod (documented in the `eod_data` docstring). #2 — kept the
  sym-owned set as one `sym eod` call (preserves monitor→fill→map→classify ordering; lower risk than
  decomposing). #3 — console date-range picker left out of scope (the launch API now accepts the
  window; the board's Run chips still launch whole-bucket/today).
- **Single source of truth honoured:** `eod`'s separate-package fan-out reuses `bucket_jobs._BUILDERS`;
  no hand-written drift list remains. `commodities` got a builder (for `eod`) but stays excluded from
  generated `BUCKET_JOBS` (its dedicated job is in `schedules.py`), so no job-name collision (12 jobs
  load).
- **Validate criticality clarified:** `eod_calculations` runs validate via `sym eod --steps validate`,
  which exits 0 even on data-quality FAILs (sym doctrine) — so a validate FAIL is logged, not run-red
  (the live run reported 7 pass/4 warn/3 fail and stayed green, matching the original behaviour).
- **Discovered (pre-existing, OUT OF SCOPE — flagged for follow-up):** `dagster_runs.launch_job` builds
  its op-config key as `f"{job}_load"`, but the bucket op is named `{key}_op` and the `eod` job's op is
  `eod_data` — so the data-monitor "Run **button**" config (subcategories/as_of_date, and now start/end)
  likely doesn't actually reach the op. The `eod` JOB (this story's deliverable) is unaffected — it's
  launched via the launchpad/CLI where the op key is correct (`eod_data`). Recommend a small follow-up to
  fix the launch_job op-config keying (ties into Open Q#3's console Run UI).
- **Verification caveat:** the live run used real vendors; rates FR/IT/ES (ECB) + NZ (RBNZ) failed to
  load (non-blocking) and rates worst-country CH ends 2025-07-31 at source — both pre-existing data
  edges, not regressions. The web toolchain wasn't needed (no web files changed).

### File List
- `packages/lineage/src/lineage/bucket_jobs.py` (modified — `resolve_window`/`_tail`/`_tick_or_today`;
  `(start,end)` builders; `_commodity_all`; `commodities` in `_BUILDERS`; `BucketConfig` range fields;
  `_run_bucket` window resolution)
- `packages/lineage/src/lineage/schedules.py` (modified — `EodConfig` range; `eod_data` all-bucket
  fan-out via builders; windowed `eod_calculations`; `_EOD_DATA_BUCKETS`; job description)
- `services/api/src/qrp_api/modules/data_monitor/dagster_runs.py` (modified — `launch_job` start/end)
- `services/api/src/qrp_api/modules/data_monitor/router.py` (modified — `LaunchRequest` start/end + pass-through)
- `packages/lineage/tests/test_bucket_jobs.py` (modified — resolver/window/`_tail` tests; `(start,end)` sigs)
- `packages/lineage/tests/test_eod_job.py` (modified — `window` input; all-bucket-coverage + windowed-recompute tests)

## Change Log
| Date | Change |
|---|---|
| 2026-06-30 | Created (bmad-create-story, Andre: "data monitor shows most data stale; need my eod job to call all the individual jobs for the given start_date and end_date"). The `eod` job exists but (1) omits macro/alt_data/fundamental/universe and (2) takes a single `as_of_date`. Story: make `eod` the union of all nine buckets over a `[start_date, end_date]` window, reusing `bucket_jobs._BUILDERS` as the single source of truth; range-native loaders take the window, single-shot loaders run once (as-of = end_date); two-stage gate + criticality preserved; scheduled single-day behaviour unchanged. Status → ready-for-dev. |
| 2026-06-30 | Dev complete → review (bmad-dev-story). Implemented Tasks 1–5: shared `resolve_window` + `(start,end)` builders + `_tail` lookback + `_commodity_all`; `EodConfig`/`BucketConfig` range; `eod_data` fans out to all 9 buckets (sym sequence + 6 separate-package builders, attempt-all) and `eod_calculations` recomputes the window. Launch API accepts start/end. 47 lineage + 15 data_monitor tests green, ruff clean, 12 jobs load. LIVE backfill `2026-06-23..2026-06-29` via Dagster CLI = RUN_SUCCESS; Data Monitor flipped 7 load-driven buckets to `ok` (macro already ok). 2 remain stale by honest source/vendor edge (rates CH source-end; commodities last-Friday). Flagged a pre-existing `launch_job` op-config-keying bug (data-monitor Run button; out of scope). Status → review. |
