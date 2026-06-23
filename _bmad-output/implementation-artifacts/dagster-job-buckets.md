# Story: Dagster job buckets — bucketed, sub-selectable, date-parameterised data jobs

Status: done

<!-- Created via bmad-create-story 2026-06-23 (Andre: "you need to create jobs into big buckets: fx,
equity prices, index levels, rates, fundamental, alt data, calculations. each of the category will then
be broken down further, for instance rates: by country. equity by universe, etc. I should be able to
trigger these jobs via dagster. the job by default will run for all subcategories by default but I should
be able to select if multiple or just one task and for any given date").
This generalises the existing trigger-only Dagster code location (packages/lineage) — today it has only
sym_eod_job / rates_curve_job / rates_world_job — into a clean set of nine *bucket* jobs, each with a
launchpad-selectable subcategory list (default = all) and an as-of/window date. Dagster-only surface; no
web work. Honors the house "Dagster = trigger + observer, sym/rates own the steps" design.
Buckets revised after creation (Andre): added `universe` (check/refresh constituents) + `macro` (split out
of `alt_data`) → nine buckets total. -->

## Story

As the operator of QRP,
I want the data pipeline exposed in Dagster as **nine big-bucket jobs** — `fx`, `equity_prices`,
`index_levels`, `rates`, `fundamental`, `alt_data`, `macro`, `universe`, `calculations` — where **each job
runs all of its subcategories by default** but I can **launch it for one, several, or all subcategories and
for any business date** from the Dagster launchpad,
so that I have one obvious, uniform way to trigger and backfill any slice of the warehouse (e.g. "just
reload rates for `DE` and `US` as of 2026-06-18", or "re-pull equity prices for `sp500` only") without
hand-typing CLI flags or modelling a bespoke job per slice.

And (**Part B**) I want a new top-level **Data Monitor** area whose first page, **EOD**, shows the warehouse
**broken down by those same nine buckets** — each row reporting **expected business date vs the actual
latest date** (a clear ok/stale/missing verdict) and, **if easily available**, the **latest Dagster run**
for that bucket's job — so that every morning I can see at a glance which datasets are current, which are
behind, and which job last touched each one, in one place. **Data Monitor is the home for ALL data/ETL
monitoring**, so it **supersedes and replaces the sym _Overview_ page** (whose freshness + last-run +
warehouse-summary content moves here); the old `/sym/overview` page is removed.

## Scope / non-goals (read first)

- **Two parts, built B-then-A (Andre: "create the Data Monitor first").** **Part B** = a read-only
  **Data Monitor** area (a new top-level rail area) whose first page **EOD** (`apps/web` + a small
  aggregating API endpoint) reports each bucket's freshness + latest run, and which **supersedes the sym
  Overview page**. **Part A** = the nine Dagster jobs (trigger/backfill surface = the Dagster launchpad at
  `uv run dagster dev -m lineage.definitions -p 3333`). The two share ONE bucket taxonomy (below) — build
  it first, since both parts consume it.
- **Single source of truth for the bucket taxonomy.** The nine buckets + their datasets live in ONE
  import-light module (`lineage/buckets.py`, NO top-level `dagster` import) consumed by BOTH the job
  builder (Part A) and the EOD monitor gateway (Part B). Adding/removing a bucket is a one-place edit.
- **Do NOT reinvent the steps.** sym and rates already own every load/compute step behind idempotent CLI
  commands. Each bucket op **shells the exact same CLI an operator would type** (the established
  `packages/lineage/src/lineage/schedules.py` pattern), capturing stdout into the run log. No new ingest
  logic, no new SQL, no asset-graph rewrite.
- **This complements `sym_eod_job`, it does not replace it.** `sym eod` stays the coarse "run the whole
  night" entry point; these buckets are the *targeted, sub-selectable, date-parameterised* entry points
  for re-runs and backfills. Keep both.
- **Default model = config-driven jobs**, NOT static Dagster partitions — see Open Design Q1 (decided).

## Background / current state (reuse, do NOT fork)

- The Dagster code location lives in **`packages/lineage`** and is deliberately a *trigger + observer*:
  one `@op` per CLI invocation, an `in_process_executor` (Windows spawn/SQLite-lock safety), schedules
  ship **STOPPED**. Entry: `lineage/definitions.py` →
  `Definitions(assets=all_assets(), jobs=[...], schedules=[...], executor=in_process_executor)`.
  [Source: packages/lineage/src/lineage/definitions.py]
- **The exact pattern to generalise** is in `lineage/schedules.py`:
  - a `Config` subclass with an `as_of_date: str = ""` field (blank → resolve at run time, preferring the
    scheduled tick over the worker clock);
  - an `@op(retry_policy=RetryPolicy(max_retries=2, delay=300))` that builds a `[sys.executable, "-m",
    "<pkg>.cli", ...]` command, runs it via `subprocess.run(cwd=repo_root(), capture_output=True,
    text=True, timeout=...)`, logs the tail, and `raise`s only on a *critical* non-zero exit;
  - a `@job` wrapping the op and a `ScheduleDefinition` with **`execution_timezone` ALWAYS set explicitly**
    ([[feedback_schedule_explicit_timezone]]) and `default_status=DefaultScheduleStatus.STOPPED`.
  [Source: packages/lineage/src/lineage/schedules.py — `EodConfig`/`sym_eod`, `rates_world_load`]
- **`repo_root()` + `run_sym()`** helpers are in `lineage/sym_run.py` (used by both the schedules and the
  runnable assets in `assets.py`). Reuse them; add a thin generic `run_cli(context, module, *args)` if a
  non-sym/non-rates module is needed, rather than copy-pasting subprocess boilerplate.
- The runnable-asset list in `lineage/assets.py` already maps each sym table to its producing CLI
  (`sym resolve` / `sym load` / `sym fx load` / `sym benchmarks` / `sym recompute` / `sym classify` /
  `sym fundamentals --all` …) — it is the authoritative inventory of which command produces which bucket.
  [Source: packages/lineage/src/lineage/assets.py — `_RUNNABLE_SYM`]

### Bucket → subcategory dimension → underlying CLI (the spec to implement)

Every underlying command is **already date-aware** and **idempotent** (immutable writes / deterministic
recompute), so "for any given date" and "safe to re-run" come for free from the CLIs.

| Bucket | Subcategory dimension | Underlying CLI (per subcategory) | Date handling |
|---|---|---|---|
| `fx` | by **source** (`frankfurter`, `ecb`, `fawazahmed0`) — small set; default all | `sym fx load` (multi-source; windowed) | `--start_date`/`--end_date` window |
| `equity_prices` | by **universe** (`sp500`, `sp400`, `sp600`, `dax`, `cac40`, `ftse100`, `ibex35`, `ftsemib`, `aex`, `smi`, `estoxx50`, `nasdaq100`, …) | `sym load --scope universe:<id> [--start_date --end_date]` | window; omit → incremental-from-cursor |
| `index_levels` | by **provider/family** (`yahoo` benchmarks, `msci`) | `sym benchmarks` · `sym msci-pull` | latest-tail (provider-driven) |
| `rates` | by **country** (ISO-2: `GB` + `DE`,`FR`,`IT`,`ES`,`US`,`JP`,`CH`,`CA`,`AU`,`NZ`,`SE`,`NO`,`HK`,`BR`,`EU`) | `GB` → `rates curve load`; others → `rates curve load-world --country XX [--start_date --end_date]` | window |
| `fundamental` | by **universe** | `sym fundamentals --all` \| `--universe <id>` | as-of latest (vendor-driven) |
| `alt_data` | by **source** (`wikipedia` pageviews; future altdata feeders) | altdata loader | obs-date windowed where supported |
| `macro` | by **source** (`worldbank`, `ecb`, `oecd`, `fiscaldata`, `bcb`/Focus/IBGE) | `python -m macro.ingest` (`run_ingest`) | obs-date driven by source |
| `universe` | by **universe** (`sp500`, `dax`, `ftse100`, `nasdaq100`, …) | `sym universe monitor <id>` (discover + append constituent changes) ⟶ optional `sym universe refresh <id>` (re-resolve + rebuild membership) | monitor is "as of now"; membership is PIT-projected |
| `calculations` | by **calc type** (`returns`=`sym recompute`, `gics`=`sym classify`, `index_returns`=`sym benchmarks` recompute, `signals`=signals compute) | the listed CLIs | `sym recompute --start_date --end_date`; others as-of-latest |

**Subcategory lists must be discovered at run time, not hardcoded where a registry exists:**
- `equity_prices` / `fundamental` / `universe` subcategories = `sym universe list` (the live universe set) —
  so a newly added universe shows up automatically and "all" really means all. These three share the SAME
  discovery callable.
- `rates` subcategories = the rates country registry (`rates countries` / the `sources` registry that
  `load-world` already iterates; note `GB` is on the BoE-archive path, not `load-world`).
- `fx` / `index_levels` / `alt_data` / `macro` / `calculations` subcategory sets are small and fixed — a
  module-level constant per bucket is fine, but keep it in ONE place each bucket reads. For `macro` the set
  is the source list inside `macro.ingest.run_ingest` (worldbank/ecb/oecd/fiscaldata/bcb).

**Two bucket-specific notes:**
- **`macro`** has no CLI today — it's `macro.ingest.run_ingest(conn)` behind a `python -m macro.ingest`
  entrypoint that runs ALL sources attempt-all. To honor per-source selection (AC#2), add a thin
  `--source <name>` filter to that entrypoint (small, in-scope; the per-source fetchers already exist in
  `sources.py`). If a clean filter is impractical, treat `macro` as a single "all" subcategory for v1 and
  log that selection is deferred — do NOT silently ignore the selector.
  [Source: packages/macro/src/macro/ingest.py:386 `run_ingest`, :511 `__main__`; sources.py fetch_* per source]
- **`universe`** = "check constituents". The discover-and-append step is `sym universe monitor <id>` (gated;
  appends `membership_event` rows, surfaced in `sym universe review`). `sym universe refresh <id>` is the
  heavier re-resolve+reproject. Default the bucket to **`monitor`** per universe (the daily "are constituents
  still right" check) and expose `refresh` via an optional config flag (e.g. `mode: "monitor"|"refresh"`,
  default `monitor`) — refreshing every universe unprompted is expensive (OpenFIGI throttled).
  [Source: packages/sym/src/sym/cli.py:1673-1691 — `universe refresh|members|monitor|review|coverage`; docs/runbook.md §2–§3]

Hardcoding the universe/country list would silently drift from what's actually loaded
([[project_universe_reload_no_gaps]] is the analogous "the list is the only guard" lesson) — discover it.

## Acceptance Criteria — Part A (Dagster jobs)

1. **Nine bucket jobs exist** in the Dagster code location, named exactly `fx`, `equity_prices`,
   `index_levels`, `rates`, `fundamental`, `alt_data`, `macro`, `universe`, `calculations`, each registered
   in `lineage/definitions.py` `Definitions(jobs=[...])` and visible in the Dagster UI Jobs list with a
   one-line description.
2. **Each job takes a `Config` with a subcategory selector and a date.** Launching with **no config runs
   ALL subcategories** for the resolved date. The selector is a `list[str]` (empty/omitted ⇒ all) so the
   launchpad lets the operator pick **one, several, or all** subcategories. An unknown subcategory value is
   rejected with a clear error listing the valid set (fail fast, don't silently no-op).
3. **Date is parameterised per job** via the same `as_of_date`/window convention as `EodConfig`: blank ⇒
   today (preferring the scheduled tick over the worker clock, exactly as `sym_eod`/`rates_world_load` do);
   set ⇒ that business date / window is passed through to every underlying CLI invocation. Windowed buckets
   (`equity_prices`, `rates`, `fx`, `calculations:returns`) translate a single `as_of_date` into the
   appropriate `--start_date`/`--end_date` (single-day or short tail, matching the existing
   `rates_world_load` 12-day-tail idiom).
4. **Subcategory iteration is attempt-all + isolated.** Within a job run, each selected subcategory runs in
   its own `try/except`; one subcategory failing is logged (`[FAIL] <bucket>:<subcat> …`) and the run
   continues to the rest. The op raises (turning the run red + triggering the existing retry policy) only
   when a **critical** subcategory fails — mirroring `sym eod`'s "a hiccup shouldn't fail the night, a
   critical step should" rule. A per-run summary (attempted / ok / skipped / failed per subcategory) is
   logged at the end.
5. **Subcategory lists are discovered, not hardcoded, where a registry exists** (`equity_prices` /
   `fundamental` from `sym universe list`; `rates` from the rates country registry). Adding a universe or
   country surfaces in the job's "all" set with no Dagster code change.
6. **No duplication of subprocess boilerplate.** The bucket ops reuse `repo_root()` and the
   established `subprocess.run(..., capture_output=True, text=True, timeout=…)` + tail-logging + critical/
   non-critical exit handling; common logic factored into one helper (e.g. `run_cli`/`run_bucket`) rather
   than copied nine times.
7. **`sym_eod_job` and the existing `rates_curve_job`/`rates_world_job` + their schedules still exist and
   still work** (this story adds jobs; it does not remove the coarse EOD entry point). Existing schedules
   continue to ship STOPPED.
8. **Tests** (the lineage package already has 22+ DB-free tests): unit tests that (a) the config default
   (empty list) expands to the full discovered subcategory set; (b) an explicit subset is honored and an
   unknown value is rejected; (c) the single-`as_of_date`→window translation is correct for a windowed
   bucket; (d) one subcategory raising does not abort the others (attempt-all). Tests must not require a
   live DB or network — stub the CLI runner / registry lookups (the lineage tests already run DB-free).
9. **Verification artifact:** `dagster definitions validate -m lineage.definitions` passes (no dangling
   deps / config-schema errors), and the nine jobs render in `uv run dagster dev`. Record the validate
   output + a launchpad screenshot/dump in the story's Dev Agent Record. Do NOT enable any schedule.

## Tasks / Subtasks — Part A (Dagster jobs)

- [ ] **Task 1 — Bucket spec + subcategory discovery** (AC: #1, #5)
  - [ ] Define a single `buckets.py` (in `packages/lineage/src/lineage/`) describing the nine buckets:
        for each, the subcategory dimension, how to enumerate "all" (a discovery callable for
        universe/country buckets; a constant for fixed ones), and the CLI-command template per subcategory.
  - [ ] Universe discovery: parse `sym universe list` output (or call the sym gateway read path) to get the
        live universe ids; rates discovery: read the rates country registry (`rates countries` /
        `sources`). Keep `GB` on the BoE-archive command, others on `load-world --country`.
- [ ] **Task 2 — Generic bucket op + config** (AC: #2, #3, #4, #6)
  - [ ] Add a `BucketConfig(Config)` with `subcategories: list[str] = []` and `as_of_date: str = ""` (plus
        optional `start_date`/`end_date` if a bucket needs an explicit window beyond single-day).
  - [ ] Factor a `run_cli(context, module, *args, timeout=…)` helper from the schedules' subprocess block
        (reuse `repo_root()`); add the single-`as_of_date`→`--start_date/--end_date` window translation.
  - [ ] One generic op body that: resolves the subcategory set (empty ⇒ discovered all; validate every
        explicit value against the discovered/declared set, else raise), loops attempt-all with per-subcat
        try/except + `[FAIL]` logging, and raises on a critical failure; emits the end-of-run summary.
- [ ] **Task 3 — Wire the nine jobs + register** (AC: #1, #7)
  - [ ] Build the nine `@job`s (one per bucket) over the generic op (parameterised by bucket name), each
        with a clear `description=` naming its subcategory dimension + the CLI it shells.
  - [ ] For `macro`: add the `--source` filter to the `python -m macro.ingest` entrypoint (or document the
        v1 single-subcategory fallback). For `universe`: add the `mode: monitor|refresh` config flag,
        default `monitor`.
  - [ ] Register all nine in `definitions.py` alongside the existing three jobs; leave existing jobs and
        STOPPED schedules untouched.
  - [ ] (Optional, note-only) Consider whether a bucket warrants its own STOPPED `ScheduleDefinition`
        (explicit `execution_timezone`); only add if there's a real cadence — otherwise leave triggering
        manual. Do NOT enable anything.
- [ ] **Task 4 — Tests** (AC: #8)
  - [ ] DB-/network-free unit tests per AC#8 (a–d); stub the CLI runner + discovery so the loop/config/
        window logic is exercised without side effects. Run with the existing `uv run pytest` for the
        lineage package.
- [ ] **Task 5 — Validate + document** (AC: #9)
  - [ ] `dagster definitions validate -m lineage.definitions`; launch `uv run dagster dev -m
        lineage.definitions -p 3333`, confirm the nine jobs appear and a no-config launch + a single-subcat
        launch both build. Capture output into the Dev Agent Record. `ruff` clean.

## Dev Notes

### Recommended design (config-driven jobs) — and the rejected alternative

- **Use a config-driven job per bucket** (a `list[str]` subcategory field, default empty ⇒ all, + an
  `as_of_date`). This matches the user's ask literally ("all by default, select one/multiple/any date"),
  matches the existing `EodConfig` idiom, and renders as an editable list in the Dagster launchpad. It is
  the minimal, house-consistent extension.
- **Explicitly NOT static Dagster partitions / MultiPartitions(date × subcategory).** Partitions are the
  "native" Dagster idiom for date×slice, but: (a) a partitioned run is one *cell*, so "run ALL subcategories
  in one launch by default" becomes a backfill of N runs — fights the requested ergonomics; (b) static
  partition sets can't track the dynamically-discovered universe/country lists without churn; (c) it's
  heavier than the deliberate trigger-only design. If per-cell run history / a backfill UI is wanted later,
  a partitioned variant can be added on top — but the default deliverable is the config-driven jobs.
  *(Open Design Q1 — decided this way; non-blocking, flagged for Andre.)*

### Critical vs non-critical (how the op decides red/green)

Mirror `sym eod`: an ingest hiccup for one subcategory (network/lock) is logged + skipped (run stays green,
detail lives in the captured `[FAIL]` lines); a critical failure raises. For these buckets, treat a
**validate/compute** failure as critical and an individual **ingest** subcategory as non-critical, so a
single blocked source doesn't redden the whole bucket — consistent with `rates_world_load` (which only
goes red when `rates validate` FAILs) and `sym_eod` (critical = fill/recompute).
[Source: packages/lineage/src/lineage/schedules.py:52-82, 144-174]

### Dependency ordering (note, not a blocker)

`calculations` (esp. `returns`=`sym recompute`) depends on `equity_prices` + `fx` + the calendar being
current; `index_returns` depends on `index_levels`. The buckets are independent jobs by design (targeted
re-runs), so this story does NOT enforce cross-bucket ordering — `sym eod` already encodes the full nightly
order. If a single "run everything in order" umbrella is desired, that's `sym_eod_job` (already exists) or a
thin follow-on op-graph; keep it out of this story unless Andre asks.

### Files to touch

- **NEW** `packages/lineage/src/lineage/buckets.py` — bucket spec + subcategory discovery + the nine jobs.
- **UPDATE** `packages/lineage/src/lineage/definitions.py` — import + register the nine jobs (and any new
  schedules). Today: `jobs=[sym_eod_job, rates_curve_job, rates_world_job]`,
  `schedules=[sym_eod_daily, rates_curve_daily, rates_world_daily]`. Preserve all three existing jobs +
  schedules; append the new jobs.
- **UPDATE** `packages/lineage/src/lineage/sym_run.py` (or `schedules.py`) — factor the shared
  `run_cli`/subprocess helper if not already reusable; keep `repo_root()` the single source.
- **NEW** tests under the lineage package's existing test dir (match its current DB-free style).
- Keep `schedules.py` ops (`sym_eod`, `rates_curve_load`, `rates_world_load`) as-is — they remain the
  coarse/scheduled entry points.

### Testing standards

- The lineage package's tests are **DB-free and network-free** (22+ today) and must stay that way — stub the
  CLI runner + the discovery callables. Do not spin a DB or hit a vendor in a unit test.
- `ruff` clean is the bar (the rates/sym packages enforce it; this package follows).

### Conventions to honor

- **Every schedule sets `execution_timezone` explicitly** and ships STOPPED ([[feedback_schedule_explicit_timezone]]).
- **`as_of_date` is the canonical name** for the business date everywhere — column, flag, param, var
  ([[feedback_as_of_date_canonical_name]]). Use it for the config field and reconcile the whole pass-through
  chain; never `asof`/`today`/`date`.
- **Execute with reasonable defaults, don't batch clarifying questions** ([[feedback_execute_dont_quiz]]).
- Dagster stays a **trigger + observer** — sym/rates own the steps; no business logic migrates into the op.

### Project Structure Notes

- All work is in `packages/lineage` (the Dagster code location) + its tests. No `apps/web`, no `services/api`,
  no new migrations, no schema change. Aligns with the per-package direction
  ([[project_qrp_structure_target]], [[data_manager_direction]] — Dagster adopt-don't-build).

### References

- [Source: packages/lineage/src/lineage/definitions.py — Definitions(jobs=…, schedules=…, in_process_executor)]
- [Source: packages/lineage/src/lineage/schedules.py — EodConfig/sym_eod, rates_curve_load, rates_world_load (the Config+op+job+STOPPED-schedule pattern to generalise; critical vs non-critical exit; tick-over-wall-clock date resolution)]
- [Source: packages/lineage/src/lineage/assets.py — _RUNNABLE_SYM: authoritative table→CLI inventory per bucket]
- [Source: packages/rates/src/rates/cli.py:182-183 — `rates curve load-world [--country XX]`; `rates curve load` (GB BoE archive)]
- [Source: packages/sym/src/sym/cli.py — `sym load --scope universe:<id> [--start_date --end_date]`, `sym fundamentals --all|--universe`, `sym recompute --start_date --end_date`, `sym benchmarks`, `sym classify`, `sym fx load`]
- [Source: docs/runbook.md §4–§8 — scope semantics, finisher sequence, `sym eod` step list + critical/non-critical design]
- Memories: [[data_manager_direction]], [[project_universe_reload_no_gaps]], [[feedback_schedule_explicit_timezone]], [[feedback_as_of_date_canonical_name]]

## Acceptance Criteria — Part B (Data Monitor › EOD page)

10. **New top-level "Data Monitor" area** with first page **EOD** at `/data-monitor/eod`. Register a
    `[[modules]] key="data-monitor" name="Data Monitor"` in `platform.toml` (its own rail entry, distinct
    from the market `monitor` boards — unlike `monitor`, this area DOES mount a backend router). Add a
    `DATA_MONITOR_SUBNAV` + `SUBNAV_PROVIDERS["data-monitor"]` in `apps/web/lib/nav.ts` and a
    `app/data-monitor/layout.tsx` tab strip mirroring `app/monitor/layout.tsx`, so it surfaces in the rail
    + submenu + command palette with no further shell edit (NFR-10 registry).
11. **One row per bucket** (the same nine, same order as Part A), each showing: the bucket name, its
    **dataset(s)** (e.g. `rates` → `rates.curve_point`; `equity_prices` → `sym.prices_raw`), the **actual
    latest business date** in the data, the **expected business date**, a **days-behind** count, and an
    **ok / stale / missing** status chip. Buckets with sub-breakdowns surface the worst-lagging
    subcategory (e.g. "rates: 15/16 current — CH 3d behind") rather than a single global max that hides a
    laggard.
12. **Expected vs actual is honest and per-market, never a naive global `max(date)`.** Reuse the existing
    freshness machinery: `classify()` (ok/stale/unknown) and the Overview's **broadly-complete coverage
    session** technique for the wide datasets (prices/returns) so one fresh sub-universe can't mask a stale
    rest (the documented max-masks-laggards trap, [[project_freshness_per_market]]). "Expected" is the
    latest trading session ≤ today for the dataset's market where a calendar is available (sym owns the
    calendar), falling back to the `STALE_AFTER_DAYS` day-count proxy that `freshness.py` already uses —
    and the page must SAY which basis it used (no fake precision).
13. **Latest Dagster run per bucket — best-effort, gracefully optional.** If the Dagster GraphQL endpoint
    is reachable (default `http://127.0.0.1:3333/graphql`, override `DAGSTER_GRAPHQL_URL`), show the bucket
    job's most-recent run: status (success/failure/started) + finished/started timestamp. If it is
    unreachable or returns nothing (e.g. `dagster dev` isn't running), the column degrades to "—" / "run
    info unavailable" — it NEVER errors the page and NEVER blocks the freshness rows. As a secondary
    already-in-DB signal, the page may also show the latest `pipeline_run_log` / `operate.job` row for the
    sym-backed buckets (these exist without Dagster running).
14. **One aggregating endpoint, read-only, resilient.** A single `GET /api/data-monitor/eod` returns the
    per-bucket payload (datasets, expected, actual, days_behind, status, coverage note, run info). It reads
    each package's DB read-only (sym + rates + macro + altdata) and NEVER writes. A failure reading one
    bucket's dataset (or a dead Dagster endpoint) degrades that field to `unknown`/`null` and still returns
    the rest — one source down must not 500 the whole page.
16. **Sym Overview is removed (superseded).** Delete `apps/web/app/sym/overview/page.tsx`, drop the
    "Overview" entry from `SYM_SUBNAV`, and remove `GET /api/sym/overview` + `DbSymGateway.overview()` +
    the `SymOverview`/`LastRun` models once EOD covers their content. **Migrate, don't lose:** the
    warehouse-summary counts (securities, universes, priced, latest session) move to a small header strip on
    the EOD page; freshness + last-run are now the per-bucket rows. **Keep `sym/freshness.py`**
    (`classify`, `STALE_AFTER_DAYS`, the coverage-session technique) — the EOD gateway reuses it. Retire or
    re-point `services/api/tests/test_sym_overview.py` (its `classify` cases move to the EOD test).
15. **Tests:** API unit tests that (a) the endpoint shape covers all nine buckets; (b) expected-vs-actual
    classification (ok vs stale vs missing) is correct given stubbed dataset dates; (c) a dead Dagster
    endpoint yields `null` run info, not an exception; (d) one bucket's dataset query raising degrades only
    that row. DB-free via stubbed connections/HTTP (mirrors the existing api test style). Web: a render
    test for the page if the vitest harness covers it (else CDP-verify per the local-tooling constraint
    [[feedback_minimize_dev_churn]]).

## Tasks / Subtasks — Part B (Data Monitor › EOD page)

- [ ] **Task 6 — Shared dataset metadata on the bucket taxonomy** (AC: #11, #14)
  - [ ] Extend `lineage/buckets.py` (the import-light single source) so each bucket carries its
        dataset descriptor(s): `(db, table, date_column)` + whether it's a "wide" dataset that needs the
        broadly-complete-coverage-session treatment. Keep it dagster-free so the API can import it.
- [ ] **Task 7 — EOD monitor gateway** (AC: #11, #12, #14)
  - [ ] New gateway (e.g. `services/api/src/qrp_api/modules/monitor/eod.py`) that, per bucket, opens the
        owning package's read-only connection and computes actual latest date + expected (calendar session
        where available, else day-count proxy) + `classify()` status + a coverage note. Reuse
        `sym/freshness.py` (`classify`, `STALE_AFTER_DAYS`) and the Overview coverage-session SQL; do not
        re-derive sym's calendar logic — read the latest session it already exposes.
  - [ ] Per-bucket try/except so one unreadable dataset degrades to `unknown`, never 500s the route.
- [ ] **Task 8 — Best-effort Dagster run lookup** (AC: #13)
  - [ ] A small helper that POSTs a GraphQL `runsOrError` query (filter by job/pipeline name) to
        `DAGSTER_GRAPHQL_URL` (default `http://127.0.0.1:3333/graphql`) with a SHORT timeout; map to
        `{status, started_at, finished_at}` per bucket. Any error/timeout → `None` (logged once, not raised).
  - [ ] Fallback: latest `pipeline_run_log` row (sym-backed buckets) so there's a signal even with Dagster
        down. Label the source so the operator knows where the run info came from.
- [ ] **Task 9 — API route + new area module** (AC: #10, #14)
  - [ ] New router (e.g. `services/api/src/qrp_api/modules/data_monitor/router.py`) exposing
        `GET /api/data-monitor/eod` → `EodMonitor` response model (list of `EodBucketRow`). Mount it in
        `main.py`. Add the `data-monitor` `[[modules]]` entry to `platform.toml`. Regenerate `api-types.ts`
        (or hand-add types consistently, per the running-server constraint).
- [ ] **Task 10 — Page + nav** (AC: #10, #11, #13)
  - [ ] `apps/web/app/data-monitor/eod/page.tsx` + `app/data-monitor/layout.tsx` (tab strip mirroring
        `app/monitor/layout.tsx`): a dense table (two-tier density [[feedback_responsive_density_two_tier]],
        date-axis-free) — bucket · datasets · expected · actual · days-behind · status chip · last run, with
        a small warehouse-summary header (the migrated Overview counts). Reuse the console status
        vocabulary/colours (ok/stale/unknown).
  - [ ] `DATA_MONITOR_SUBNAV = [{ href: "/data-monitor/eod", label: "EOD" }]` + register under
        `SUBNAV_PROVIDERS["data-monitor"]` in `nav.ts`.
- [ ] **Task 11 — Remove the sym Overview (superseded)** (AC: #16)
  - [ ] Delete `app/sym/overview/page.tsx`; drop the "Overview" item from `SYM_SUBNAV`; remove
        `GET /api/sym/overview` + `overview()` + `SymOverview`/`LastRun`. Keep `sym/freshness.py` (reused).
        Re-point/retire `test_sym_overview.py`. Confirm no other consumer of `/api/sym/overview` before
        deleting (grep `api-status.tsx`, `sym/page.tsx`).
- [ ] **Task 12 — Tests + verify** (AC: #15)
  - [ ] API tests per AC#15; ruff clean; restart API + CDP-verify `/data-monitor/eod` renders (real Chrome
        dump-dom) and `/sym/overview` is gone, given the web-tooling-not-runnable-locally constraint.

## Open Design Questions (defaults chosen — non-blocking)

1. **Config-driven jobs vs Dagster partitions?** → Decided: config-driven (above). Flagged for Andre; a
   partitioned variant can layer on later if per-cell run history is wanted.
2. **One job per bucket (9) vs one job with a bucket selector?** → Decided: nine jobs (the user said "jobs
   into big buckets"; cleaner in the Jobs list + lets a future schedule attach per bucket).
3. **Per-bucket schedules now?** → Decided: no (manual trigger only); the existing `sym_eod`/rates schedules
   already cover unattended nightly. Add per-bucket STOPPED schedules only if Andre wants a specific cadence.
4. **Single `as_of_date` → window width** for windowed buckets? → Default: single day for `equity_prices`/
   `fx`/`calculations:returns`; reuse the 12-day tail for `rates` (matches `rates_world_load`). Adjustable
   via optional `start_date`/`end_date`.

## Review Findings

Code review 2026-06-23 (bmad-code-review, 3 adversarial layers: Blind Hunter, Edge Case Hunter,
Acceptance Auditor) on commit 042ce9b. 10 patches applied, 3 deferred, 1 dismissed. No unresolved
High/Med. Re-verified: 44 lineage+EOD tests (13 new Part-A) + 169 api green, ruff clean.

### Patches applied
- [x] [Review][Patch] Fail-fast on unknown subcategory + empty plan no longer passes green [bucket_jobs.py `_run_bucket`] — validate explicit subcats against the discovered/declared set (raise listing valid values); an empty resolved plan now RAISES instead of a silent green run. (AC#2; blind+edge+auditor)
- [x] [Review][Patch] Catch `subprocess.TimeoutExpired` in `_run_cmd` → non-critical [bucket_jobs.py] — a hung non-critical ingest is logged `[FAIL]` and skipped (attempt-all integrity); a critical step still propagates. (edge)
- [x] [Review][Patch] Validate `as_of_date` once up front [bucket_jobs.py `_run_bucket`] — a malformed date gets a clear error, not a stack trace from a window builder. (edge)
- [x] [Review][Patch] EOD endpoint never-500 [eod.py `eod()`] — `latest_session` + `_summary` wrapped; a sym hiccup degrades to a renderable board (AC#14). (edge)
- [x] [Review][Patch] Clamp per-country `days_behind` ≥ 0 [eod.py `_grouped`] — a rates curve newer than the equity session no longer renders negative. (blind+edge)
- [x] [Review][Patch] Guard `_run_cmd` against an empty command tuple [bucket_jobs.py] — defensive, no IndexError. (edge)
- [x] [Review][Patch] Mark `calculations:returns` (recompute) critical [bucket_jobs.py `_calc_cmds`] — a recompute failure reddens the run (Dev Notes compute-vs-ingest rule). (auditor)
- [x] [Review][Patch] `calculations:returns` now date-windowed [bucket_jobs.py] — `recompute --start_date/--end_date` so a backfill targets `as_of_date` (AC#3). (auditor)
- [x] [Review][Patch] Honest deferred-selection log for single-source buckets (fx/macro/alt_data) [bucket_jobs.py] — a subcategory selection on a no-selector bucket is logged as NOT applied, not silently implied. (AC#2; auditor)
- [x] [Review][Patch] Added Part A bucket-job tests (AC#8) [packages/lineage/tests/test_bucket_jobs.py] — config default⇒all, unknown rejected, window translation, attempt-all isolation, empty-plan-fails. (auditor)

### Deferred
- [x] [Review][Defer] universe `mode: monitor|refresh` config flag — spec-optional; default `monitor` already correct. Deferred: a feature add, not a defect.
- [x] [Review][Defer] rates per-country *registry* discovery — the `rates` CLI owns the country list (`load-world` iterates; a bad `--country` errors). Acceptable until a cheap registry read is wanted.
- [x] [Review][Defer] regenerate `api-types.ts` (stale `SymOverview` entries) — web/openapi toolchain not runnable locally; no live consumer. Regen when the toolchain is available.

### Dismissed
- Dagster null-`startTime` ordering among QUEUED runs — harmless (`or 0`; a real run replaces it).

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
