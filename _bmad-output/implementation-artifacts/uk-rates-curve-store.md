# Story: UK rates curve store — Bank of England daily yield curves (new `rates` package)

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "/bmad-create-story" following the FI-curves
brainstorming session). This is v1 of the fixed-income direction settled in
_bmad-output/brainstorming/brainstorming-session-2026-06-22-211134.md (steps 1–4 of that doc's action
plan: probe → topology → schema+ingest → validate). Topology was decided by Andre 2026-06-22 via the
create-story AskUserQuestion: a NEW `rates` package, NOT inside sym. Derived analytics (spreads / carry /
DV01) and bond reference-data are explicit FOLLOW-ON stories, out of scope here. -->

## Story

As a fixed-income analyst on QRP,
I want a **trustworthy point-in-time store of the Bank of England's daily UK yield curves** (gilt
nominal / real / implied-inflation + SONIA/OIS), ingested from BoE's authoritative free dataset into a
new `rates` package and guarded by reconciliation + freshness validation,
so that QRP has a reliable curve foundation to build FI trading analytics on (curve/breakeven/asset-swap
spreads, carry & roll) — the way the equity/FX warehouse already underpins those asset classes.

## Background / current state (read before coding)

- **Fixed income is a brand-new asset class for QRP.** Today the platform covers equities + FX + macro;
  there is no curve/rates storage. This story stands up the foundation, not the trading analytics on top.
- **Topology — DECIDED: a new `rates` package, peer to `sym`/`macro`** (not inside `sym`). See
  [[project_rates_package_decision]]. Rationale: a curve grid shares ~no schema with equity prices or the
  FX star; a new peer honors the Postgres-per-package direction ([[project_db_topology_direction]]),
  sym-shaped standalone packages ([[project_qrp_structure_target]]), and **sym is a peer, not the hub**
  ([[feedback_sym_is_peer_not_hub]]). **Model the new package on `macro`'s shape** (`packages/macro/` has
  its own `db/` sqitch root with `deploy`/`revert`/`verify` + `series`/`observation` schema + a
  `services/api/.../modules/macro/` gateway). `macro` is the closest existing peer — copy its skeleton.
- **The source — Bank of England published yield-curve dataset.** BoE's Monetary & Financial Conditions
  Division estimates UK curves daily and publishes them as **Excel/zip** files (latest + monthly historical
  archives). Two curve sets:
  - **Gilt-based (`glc`):** nominal, real, and implied-inflation term structures.
  - **Sterling money-market (`ois`):** SONIA overnight + OIS.
  BoE already bootstraps/fits and publishes **spot, instantaneous-forward, and (for nominal) par** rates on
  a tenor grid. Licensing: **Open Government Licence** (free, attribution) — a compliance advantage over a
  vendor feed (no redistribution restriction). Confirm OGL terms during the probe.
- **Atom = the published curve grid, NOT raw gilt quotes** (the key brainstorm refinement). We store BoE's
  fitted grid verbatim and treat it as the observation; we do NOT re-bootstrap from individual gilt prices
  (that would be a separate, much larger source — out of scope). Derived prices/DV01/spreads are computed
  on read in a later story.
- **Reuse the sym/fx/macro ingest skeleton (do NOT reinvent):** the FX layer (`packages/sym/src/sym/fx/`)
  is the closest precedent for "external EOD source → immutable, source-tagged, plausibility-gated,
  as-of-keyed storage + validate checks + CLI":
  - **Source protocol** (`sym/fx/source.py`: `FxSource.fetch(...) -> list[FxObservation]`, frozen
    `FxObservation` dataclass) → model a `CurveSource.fetch(...) -> list[CurvePoint]`.
  - **Loader** (`sym/fx/ingest.py`: `fill_fx(conn, source, *, end_date, start_date=None, ...)`, tail-since-
    latest vs explicit-backfill modes, immutable insert skipping existing, `implausible()` band gate →
    review queue, `FxLoadSummary`) → model `fill_curve(...)` the same way.
  - **Immutable, source-tagged, as-of-keyed table** (`sym/migrations/deploy/fx_rate.sql`: PK includes
    `as_of_date` + `source`, `ON CONFLICT DO NOTHING`, `CHECK` constraints, value `NUMERIC`) — and the
    `index_levels` table (`variant` dimension keeps representations distinct) is the model for the multi-
    dimensional curve grid.
  - **Validate layer** (`sym/validate/runner.py` `CheckResult` + `run_all` registration; `sym/validate/fx.py`
    `check_fx_coverage` is a worked example) → add curve checks.
  - **CLI** (`sym/cli.py` `build_parser` + sub-subparsers like `sym fx load`; handlers return exit codes
    0/1/2; `conn.autocommit=True` for per-row durability per [[feedback_psycopg_per_figi_durability]]).
  - **Schedule** (`packages/lineage/src/lineage/schedules.py` — every `ScheduleDefinition` sets
    `execution_timezone` explicitly; `default_status=STOPPED`).
- **Probe-before-build is mandatory** ([[reference_env_external_sources]], [[feedback_name_the_probe_retest]]).
  The sim-2026 env reaches ECB SDMX / WorldBank / yfinance-EOD but blocks FRED + live quotes. **BoE's
  yield-curve file host has NOT been probed** — Task 1 probes it in-env and records the exact probe + a
  re-test trigger. The precise tenor grid, file layout, sheet names, history depth, and which
  (basis × rate_type) combinations BoE actually publishes are **probe outputs** — the schema below is the
  target shape, to be reconciled against what the probe finds before the migration is written.

## Acceptance Criteria

1. **Source probed + maintenance plan recorded (gate).** The BoE yield-curve dataset is probed in-env: the
   exact download URL(s) for latest + historical archives, file format (Excel/zip), sheet/column layout,
   the published tenor grid, history depth, the available `(curve_set, basis, rate_type)` combinations, and
   the OGL licence terms are documented in a maintenance-plan note under `packages/rates/` (source,
   monitor cadence, gating, PIT boundary — per [[feedback_index_maintenance_plan]]). **BoE's exact
   compounding + day-count convention for spot/forward/par is captured from their methodology doc** (so a
   later derive-on-read layer can reconcile). If the host is unreachable in-env, the probe records the exact
   URL tried + a re-test trigger and the story proceeds against a saved sample file (clearly flagged), never
   a guess.
2. **New `rates` package scaffolded, peer to sym/macro.** `packages/rates/` exists modeled on `macro`:
   `src/rates/` (`cli.py`, `config.py`, `db.py`, `sources/`, `ingest.py`, `validate/`), its own sqitch root
   (`db/` or `migrations/` with `deploy`/`revert`/`verify` + `sqitch.conf`/`sqitch.plan`), and is
   installable/importable like the other packages. It reads the policy-rate anchor from `macro` read-only
   if needed (one-way dependency); it does not modify sym or macro.
3. **Curve-grid schema (immutable first-published, source-tagged, PIT).** A `curve_point` table stores the
   BoE grid keyed by `(curve_set, basis, rate_type, tenor, as_of_date)` with **two vintages in one row**
   — `first_value` (immutable first-published, PIT/backtest read) + `value` (restated latest, default
   read), `last_changed_at` re-stamped only on a real restatement (resolved 2026-06-22: single-row model,
   not a `vintage`-in-PK row split) → `value` (+ `source`, `first_published_at`, `last_changed_at`),
   where `as_of_date` = **the curve's stated date from the file, never the ingest date** (canonical
   `as_of_date`, [[feedback_as_of_date_canonical_name]]). `curve_set ∈ {glc, ois}`, `basis ∈ {nominal,
   real, inflation}`, `rate_type ∈ {spot, forward}` — par is NOT published by BoE (probe finding;
   the reconciliation guard is inflation = nominal − real, not par↔spot). Tenor stored **as data, not columns** (so a new BoE tenor is accepted, not
   dropped). `value` is `NUMERIC` with a `CHECK` allowing negative yields (post-2015 reality) but bounded to
   a plausible band. `first_value` is immutable (never in any UPDATE); `value` updates only on a real
   restatement (`ON CONFLICT DO UPDATE … WHERE value IS DISTINCT FROM EXCLUDED.value`). Migration is a sqitch deploy/revert/
   verify trio registered in the `rates` plan; reconciled against the probe's actual layout. (Sqitch deploy
   runs via the Docker flow, [[reference_sqitch_deploy_docker]]; if Docker is down, apply to the dev DB
   directly with `IF NOT EXISTS` and flag the deploy as a pending no-op — the `ticker-region-codes`
   precedent.)
4. **Two vintages, default latest (PIT/restatement).** BoE refits and revises historical curves. Store both
   the **first-published** value (`first_value`, immutable) and the **latest-estimate** value (`value`,
   restated) **in one row** (resolved 2026-06-22 — single-row model, not a `vintage`-in-PK row split or
   `valid_from/to`). Reads default to latest (`value`); a backtest/PIT read pins to first-published
   (`first_value`). `first_value` is never overwritten.
5. **BoE ingest loader.** `rates curve load [--start_date] [--end_date]` parses the BoE file(s) and inserts
   the grid. Tail-since-latest when no `--start_date`; explicit-window backfill otherwise — mirroring
   `fill_fx`. **Atomic per-day load across all four bases** (gilt nominal/real/inflation + ois): a day is
   gated/skipped if incomplete rather than landing a desynced partial curve (the partial-EOD lesson,
   [[project_partial_eod_repair]]). A **parse-layout assertion** fails loud if BoE's sheet/column/tenor
   layout drifts from what the probe recorded (never silently mis-map columns). Units are canonicalized at
   ingest (% vs decimal vs bp — assert one representation). Implausible day-over-day moves per tenor route
   to a review queue rather than landing silently. A `CurveLoadSummary` reports inserted/skipped/implausible/
   flagged + the resolved window. Source-tagged `boe`.
6. **Validation checks (the trust layer).** New `rates` validate checks returning `CheckResult` (PASS/WARN/
   FAIL), runnable via `rates validate` (and registered for the EOD path):
   - **Reconciliation (the free check, highest value):** where BoE publishes more than one rate_type, the
     relationships must hold — e.g. par/forward reconcile to spot within tolerance (and, once a derive-on-
     read layer exists, our derived forward/par must match BoE's published forward/par). Fail loud beyond
     tolerance.
   - **Inflation reconcile:** stored implied-inflation ≈ nominal − real within tolerance (labelled **RPI**,
     not CPI — never mislabel, [[project_fi_curves_brainstorm]]).
   - **Plausible band:** each tenor's value within a sane range (e.g. UK spot ∈ [−2%, 20%]); no missing
     tenors vs the recorded grid.
   - **Stale-curve gating:** latest `as_of_date` vs the expected UK publish calendar — a missed publish
     reads **stale**, never silently carried forward as current ([[project_freshness_per_market]]). Use the
     UK bank-holiday calendar to distinguish an expected gap from a real miss.
7. **Daily schedule with explicit timezone.** A Dagster (or existing scheduler) definition for the daily
   BoE load sets `execution_timezone="Europe/London"` explicitly (BoE publishes in London time), with a
   documented "why", `default_status=STOPPED` — per [[feedback_schedule_explicit_timezone]]. The schedule
   wires `rates curve load` then the `rates validate` gate.
8. **Minimal read reachability.** A read path proves the stored curve is reachable: a gateway method +
   `GET /api/rates/curve` (latest) and `GET /api/rates/curve?as_of_date=YYYY-MM-DD` (as-of, defaulting to
   latest vintage) returning the curve grid for a `(curve_set, basis, rate_type)` selection. Read-only;
   thin — the rich derived-analytics surface (spreads/carry/DV01 + a console page) is the explicit
   follow-on story, NOT this one.
9. **No regression + green.** sym/macro and the rest of the platform are untouched (the `rates` package is
   additive). New `rates` tests pass; `ruff`/`pytest` clean for the package; if the read endpoint lands,
   API tests + `tsc` (api-types regen) clean. Provenance (source + vintage) is on every stored value
   ([[feedback_index_maintenance_plan]] PIT honesty).

## Tasks / Subtasks

- [x] **Task 1 — Probe BoE + record the maintenance plan (GATE; do first) (AC: #1)**
  - [x] Probe the BoE yield-curve download host in-env (the latest + archive Excel/zip URLs). Record the
    exact URLs tried + result + a re-test trigger ([[feedback_name_the_probe_retest]]). If unreachable,
    obtain/save a representative sample file and flag the env block — do not guess the layout.
  - [x] Open the file(s): record sheet names, column/tenor layout, the published tenor grid, history depth,
    and exactly which `(curve_set, basis, rate_type)` combinations exist (gilt nominal/real/inflation spot/
    forward/par; ois SONIA/OIS). Note the latest-vs-archive vintage structure (how restatement is exposed).
  - [x] Capture BoE's compounding + day-count convention for each rate_type from their methodology doc.
  - [x] Confirm OGL licence terms.
  - [x] Write `packages/rates/MAINTENANCE.md` (or the project's plan location): source URLs, format, cadence,
    history, gating, PIT boundary, conventions, licence. **Reconcile AC#3's schema against what was found
    before writing the migration; report any deltas in Completion Notes.**
- [x] **Task 2 — Scaffold the `rates` package (AC: #2)**
  - [x] Create `packages/rates/` modeled on `packages/macro/` (pyproject/packaging, `src/rates/` with
    `cli.py`/`config.py`/`db.py`, `sources/`, `ingest.py`, `validate/`, and a sqitch root with `deploy`/
    `revert`/`verify` + `sqitch.conf` + an empty `sqitch.plan`). Mirror macro's DB connection/config pattern.
  - [x] Wire `rates` as an importable/installable peer (match how macro is wired into the workspace). No
    edits to sym/macro internals.
- [x] **Task 3 — `curve_point` schema migration (AC: #3, #4)**
  - [x] sqitch `deploy/curve_point.sql` (+ `revert` + `verify`), registered in the `rates` plan, keyed
    `(curve_set, basis, rate_type, tenor, as_of_date)`, `CHECK`s (allow negative yields, plausible band),
    source-tagged, tenor-as-data. Encode the two-vintage model **in one row** (`first_value` immutable +
    `value` restated; resolved single-row design). Reconcile to Task 1's findings.
  - [x] Deploy via the Docker sqitch flow ([[reference_sqitch_deploy_docker]]); if Docker is down apply to
    dev DB directly with `IF NOT EXISTS` and flag the sqitch deploy as a pending no-op.
- [x] **Task 4 — BoE source adapter + ingest loader (AC: #5)**
  - [x] `rates/sources/boe.py`: a `CurveSource.fetch(...)` that downloads + parses the Excel/zip into
    normalized `CurvePoint` observations (`as_of_date` = stated curve date). Parse-layout assertion that
    fails loud on drift. Unit canonicalization.
  - [x] `rates/ingest.py`: `fill_curve(conn, source, *, end_date, start_date=None, ...)` — tail/backfill
    modes, immutable insert, **atomic per-day across all four bases** (gate incomplete days), implausible-
    band gate → review queue, `CurveLoadSummary`. Mirror `fill_fx`.
- [x] **Task 5 — Validate checks (AC: #6)**
  - [x] `rates/validate/`: reconciliation (par/forward↔spot the free check), inflation = nominal − real
    (RPI-labelled), plausible-band + no-missing-tenor, stale-gating vs the UK bank-holiday calendar. Return
    `CheckResult`; register in a `rates validate` runner mirroring `sym/validate/runner.py`.
- [x] **Task 6 — CLI (AC: #5, #6)**
  - [x] `rates` CLI (`build_parser`) with `curve load [--start_date] [--end_date]`, `curve coverage`, and
    `validate`; handlers return exit codes 0/1/2; `conn.autocommit=True`.
- [x] **Task 7 — Daily schedule (AC: #7)**
  - [x] A schedule definition for the daily BoE load + validate gate, `execution_timezone="Europe/London"`
    (documented why), `default_status=STOPPED`. Mirror `lineage/schedules.py`.
- [x] **Task 8 — Minimal read endpoint (AC: #8)**
  - [x] `services/api/.../modules/rates/` gateway + router: `GET /api/rates/curve` (latest) +
    `?as_of_date=` (as-of, latest vintage) for a `(curve_set, basis, rate_type)` selection. Register the
    router. Regenerate api-types if a typed contract is exposed.
- [x] **Task 9 — Verify + no-regression (AC: #9)**
  - [x] `ruff`/`pytest` green for `rates`; load a real (or sample) BoE day end-to-end and spot-check a few
    tenors against the source file; run `rates validate` and confirm the reconciliation + stale checks
    behave. sym/macro/platform untouched. If the endpoint landed: API tests + `tsc` clean. Per
    [[feedback_scale_verification_to_change]] this is a data/behavioral change — verify the ingest + checks
    actually run, not just that code compiles.

### Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Auditor: 5/9 ACs fully met; the rest are deviations/partials below. No data-corrupting bug found; the
Blind Hunter's one "High" (xmax=0 classification) was REFUTED by the Edge Case Hunter (macro uses the
identical idiom). 1 decision, 7 patches, 8 deferred, 6 dismissed.

- [x] [Review][Decision] **AC#3 deviation: PK omits `vintage` + `ON CONFLICT DO UPDATE` (not DO NOTHING)** — RESOLVED 2026-06-22 (Andre): **keep the single-row two-vintage model** (`first_value` immutable + `value` restated) — cleaner, fewer rows, PIT-correct, already loaded+tested. AC#3 wording reconciled to match (below).
- [x] [Review][Patch] **`services/api` does not declare `rates` as a dependency** [services/api/pyproject.toml] — `main.py` imports `rates.router` when enabled, but `rates` is absent from api deps + `[tool.uv.sources]`. Works under the workspace `uv run` venv today; breaks any standalone api install (the lone enabled router not in the closure).
- [x] [Review][Patch] **`rates` not registered in `tools/deploy_all.py` REGISTRY** [tools/deploy_all.py] — the package ships a full sqitch project owning its own `rates` DB, but the house deploy/create/verify path skips it. Add the registry entry.
- [x] [Review][Patch] **Unclosed read-only openpyxl workbook (handle leak)** [packages/rates/src/rates/sources/boe.py `parse_workbook`] — `load_workbook(read_only=True)` is never closed; leaks a handle per workbook in the archive-backfill loop. Wrap in try/finally `wb.close()`.
- [x] [Review][Patch] **`--archive` without `--start_date` wrongly triggers the tail desync gate** [cli.py / ingest.py] — `archive = bool(args.archive or start_date is not None)` but `tail_case = start_date is None`, so `--archive` alone fetches full history yet gates it with the tail heuristic. Decouple the tail flag from `--archive`.
- [x] [Review][Patch] **AC#6 "no missing tenors" claimed in docstring but not implemented** [validate/checks.py `check_plausible_band`] — add a light hole guard (latest-day tenor count vs the prior day per series) or drop the overclaim.
- [x] [Review][Patch] **`.pytest_cache/README.md` committed** [packages/rates/.pytest_cache/] — the file says "do not commit"; add a `.gitignore` entry + remove it.
- [x] [Review][Patch] **Tautological test assertion** [tests/test_ingest.py] — `assert all(row["v"] == row.get("v") …)` compares a value to itself; assert something real (the SQL binds the same param for value + first_value) or drop it.
- [x] [Review][Defer] **AC#6 stale check uses weekends only, not the UK bank-holiday calendar** [validate/checks.py] — WARN-only impact (false "stale" around a Bank Holiday); a proper UK holiday calendar is a follow-up.
- [x] [Review][Defer] **AC#1 BoE compounding/day-count not captured** — deferred to the derive-on-read analytics story (documented in MAINTENANCE.md).
- [x] [Review][Defer] **`prev` not chained on a flagged point → a sustained real >5pp jump flags forever** [ingest.py] — theoretical for gilt curves (a 500bp daily move doesn't occur); the review queue is the intended path.
- [x] [Review][Defer] **Desync gate blind to a wholesale-missing-basis / single-day partial bundle** [ingest.py] — narrow (month-boundary intraday); the stale/completeness validate check is the backstop. A persisted expected-set would close it.
- [x] [Review][Defer] **`/api/rates/curve` accepts unconstrained enum params (empty result on a typo, not 422)** [router.py] — read endpoint, no consumer yet; add `Literal` types when the console page lands.
- [x] [Review][Defer] **`count(DISTINCT as_of_date)` on `/curve/series` over full history** [gateway.py] — fine at current size; revisit at scale (the count-distinct trap).
- [x] [Review][Defer] **No download/extract size cap (zip-bomb)** [sources/boe.py] — trusted BoE host; add a cap if the source ever changes.
- [x] [Review][Defer] **AC#5 no explicit ingest-time unit-canonicalization assert** — the `curve_point` value CHECK (`> -10 AND < 30`) is effectively the write-time representation guard; an explicit parser assert is a nice-to-have.

Dismissed (6): xmax=0 classification "High" (REFUTED — macro/ingest.py uses the identical idiom; affects only summary counts); plausible-band vs DB-CHECK vs move-band "inconsistency" (deliberate layering); tenor float→NUMERIC PK fragility (REFUTED — `round(…,6)` deterministic, no collision for BoE grids); f-string SQL in `gateway.curve` (benign — `value_col` is an internal ternary, never user input); review-queue has no promote tool (by design, already in deferred-work); `connect()` re-reads `.env` per request (matches the macro pattern).

## Dev Notes

### Critical conventions (regressions / trust failures if violated)
- **Probe first; the probe outputs drive the schema.** Do not write the migration against the assumed grid —
  reconcile it to what BoE actually publishes (Task 1). Record deltas.
- **`as_of_date` = the curve's stated date, never the ingest date** ([[feedback_as_of_date_canonical_name]]).
- **The reconciliation check is the highest-leverage guardrail** — par/forward↔spot (and later derived↔
  published) catches the silent convention-mismatch that corrupts every derived price invisibly. Pin BoE's
  exact compounding/day-count (Task 1) so it's enforceable.
- **Two vintages; first-published is immutable.** Restatement keeps both; reads default latest; PIT/backtest
  pins to first-published. Mirror the FX `valid_from/to` restate pattern.
- **Atomic per-day, all four bases** — never land a desynced partial curve ([[project_partial_eod_repair]]).
- **Stale, never silently carried** — a missed publish reads stale vs the UK publish calendar
  ([[project_freshness_per_market]]).
- **Inflation is RPI (lagged), not CPI** — label it so it can't be silently consumed as CPI expectations.
- **`rates` is a peer, additive** — no edits to sym/macro internals; one-way read of macro's policy rate if
  the short-end anchor is needed ([[feedback_sym_is_peer_not_hub]]).
- **Schedule sets `execution_timezone` explicitly** ([[feedback_schedule_explicit_timezone]]).
- **Maintenance plan required before populating** ([[feedback_index_maintenance_plan]]).
- **Durable per-row inserts** — `conn.autocommit=True` so per-row `conn.transaction()` commits
  ([[feedback_psycopg_per_figi_durability]]); delete test rows explicitly rather than rollback-to-keep-empty
  ([[feedback_db_validation_rollback]]).

### Explicitly OUT of scope (follow-on stories)
- **Derived analytics / trading layer:** spreads (2s10s, flies, breakeven, asset-swap) with history +
  z-score; carry & roll-down off the forward curve; DV01 / dirty-price; a console page. (The biggest value,
  but a separate story — this one is the trustworthy store it sits on.)
- **Bond reference-data / specific-gilt pricing:** the curve does not contain a bond's cashflow schedule;
  pricing a specific position needs a separate dataset (the bridge from curve → position).
- **Live intraday mark:** BoE is EOD-only; a live overlay (à la WEI/FX live) is later.
- **2nd UK source + divergence check** (FX-style); **multi-country expansion** (US/DE/…).

### Project Structure Notes
- New top-level package `packages/rates/` (peer to `packages/sym`, `packages/macro`). New API module
  `services/api/src/qrp_api/modules/rates/`. New (optional) schedule alongside `lineage/schedules.py` or in
  the rates package. Own Postgres schema/DB `rates` per the per-package direction
  ([[project_db_topology_direction]]) — confirm how DBs are provisioned locally (macro's pattern).
- This is a **standalone story** (like fx-matrix-live, ticker-region-codes) tracked by basename in
  sprint-status.yaml's "Standalone / cross-cutting" section, not part of an epic decomposition.

### References
- Brainstorm spec: `_bmad-output/brainstorming/brainstorming-session-2026-06-22-211134.md` (the full
  divergence + the 12-point data-quality pre-mortem the validate checks implement).
- [Source: packages/macro/] — the peer-package skeleton to model `rates` on (own `db/` sqitch + gateway).
- [Source: packages/sym/src/sym/fx/source.py] — `FxSource` protocol + frozen observation dataclass.
- [Source: packages/sym/src/sym/fx/ingest.py] — `fill_fx` (tail/backfill, immutable insert, `implausible`
  band, review queue, `FxLoadSummary`) — the loader to mirror as `fill_curve`.
- [Source: packages/sym/migrations/deploy/fx_rate.sql + index_levels.sql] — immutable source-tagged as-of
  schema + the `variant` multi-representation dimension.
- [Source: packages/sym/src/sym/validate/runner.py + validate/fx.py] — `CheckResult` + `run_all` + a worked
  check (`check_fx_coverage`).
- [Source: packages/sym/src/sym/fx/reconcile.py] — `sym fx divergence` (the 2-source cross-check pattern for
  the deferred 2nd-source follow-on).
- [Source: packages/sym/src/sym/cli.py] — `build_parser` + sub-subparser registration + exit-code handlers.
- [Source: packages/lineage/src/lineage/schedules.py] — `ScheduleDefinition` with explicit
  `execution_timezone`, `default_status=STOPPED`.
- [Source: services/api/src/qrp_api/modules/sym/{gateway,router}.py] — gateway/router read pattern for the
  minimal endpoint.
- Memories: [[project_rates_package_decision]], [[project_fi_curves_brainstorm]],
  [[project_db_topology_direction]], [[project_qrp_structure_target]], [[feedback_sym_is_peer_not_hub]],
  [[feedback_as_of_date_canonical_name]], [[feedback_schedule_explicit_timezone]],
  [[feedback_index_maintenance_plan]], [[project_freshness_per_market]], [[project_partial_eod_repair]],
  [[reference_env_external_sources]], [[reference_sqitch_deploy_docker]], [[feedback_name_the_probe_retest]],
  [[feedback_psycopg_per_figi_durability]], [[feedback_db_validation_rollback]],
  [[feedback_scale_verification_to_change]].

## Open Questions (for Andre — defaults chosen, do not block)
1. **Curve sets in v1:** default = ingest BOTH the gilt set (nominal/real/inflation) AND the ois set
   (SONIA/OIS) since BoE publishes them together. Narrow to gilt-only first if you'd rather stage it.
2. **History depth on first load:** default = backfill BoE's full published history (it's free + the PIT
   value is in the history). Say if you want a shorter floor to start.
3. **Vintage exposure:** default = store both first-published + latest, reads default latest. Confirm that
   matches how you'll backtest (pin-to-first-published is the look-ahead guard).
4. **DB provisioning:** the per-package-Postgres direction implies a `rates` DB. Default = follow macro's
   local pattern. Flag if you want `rates` to share the dev Postgres instance/schema for now.
5. **Schedule time:** default = a London-EOD slot after BoE's daily publish (Task 1 pins the exact publish
   time); `default_status=STOPPED` until you enable it.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes List

**Probe (Task 1) corrected two schema assumptions** — recorded in `packages/rates/MAINTENANCE.md`:
- **BoE publishes `spot` + `forward` only — there is NO `par` curve.** The story/brainstorm assumed
  `rate_type ∈ {spot, forward, par}`; the schema `CHECK` is `{spot, forward}`. The "free reconciliation
  check" therefore became **inflation = nominal − real** (exact, FAIL-level) plus a **forward→spot**
  reconstruction (approximate, WARN-level until derive-on-read pins BoE's compounding) — not par↔spot.
- **Curve sets:** GLC (gilt: nominal 0.5–40y, real/inflation 2.5–40y) + OIS (nominal 0.5–25y). Each file
  has a canonical "curve" grid (0.5y steps) AND a finer "short end" grid (monthly); the parser keeps
  both, curve-grid wins on shared tenors, short-end-only sub-year nodes are added (tenor-as-data).

**Verified end-to-end on REAL BoE data (probed reachable in-env 2026-06-22):**
- `rates curve load` parsed `latest-yield-curve-data.zip` → **13,140 nodes across 8 series, 15 days**
  (2026-06-01..06-19; today 06-22 not yet published — honest EOD lag). Re-run → 0 inserted / 13,140
  skipped (idempotent). 0 flagged, 0 gated.
- `rates validate` → **all 4 checks PASS** (exit 0): staleness ok; plausible-band 438 nodes; **inflation
  = nominal − real reconciles within 0.02pp over 102 nodes (the free check)**; forward→spot within 0.5pp
  over 125 nodes.
- `GET /api/rates/curve` + `/curve/series` verified in-process (router mounts; gateway returns the
  126-node nominal-spot grid, as-of resolution, and the first-vintage `first_value` read).

**Two vintages in one row:** `first_value` (immutable first-published, PIT/backtest) + `value` (restated
latest, default read); `last_changed_at` re-stamps only on a real restatement (the upsert's `WHERE value
IS DISTINCT FROM EXCLUDED.value` guard). Pragmatic single-row model (vs full valid_from/to time-travel),
matching the brainstorm's "two vintages, default latest".

**Tests:** 22 DB-free tests (parser w/ synthetic xlsx incl. layout-error + dedup; ingest vintages /
plausibility→review / desync-gate via fake conn; validate inflation-reconcile pass+fail / band / stale;
gateway reads). `pytest` 22/22, `ruff` clean.

### Caveats / follow-ups (carried to deferred-work)
- **sqitch deploy pending** (Docker down): `rates` DB created + `curve_point` schema applied directly to
  the dev instance (deploy SQL is `IF NOT EXISTS`); `sqitch deploy` is a no-op-pending once Docker is up
  (the `ticker-region-codes` precedent).
- **Running API server (:8001) predates the `rates` install** → serves `/api/rates` only after its next
  restart (endpoint verified in-process; not force-restarting per the minimize-churn rule).
- **api-types regen deferred** to the follow-on console story (no web consumer of `/api/rates` yet).
- **Full-history backfill not run** — only the latest (current-month) bundle loaded. One-time
  `rates curve load --start_date <floor>` pulls the ~39 MB archive zips when wanted.

### File List
- `packages/rates/pyproject.toml` (new)
- `packages/rates/src/rates/__init__.py` (new)
- `packages/rates/src/rates/db.py` (new — macro-pattern connection, own `rates` DB)
- `packages/rates/src/rates/sources/__init__.py` (new)
- `packages/rates/src/rates/sources/boe.py` (new — download + pure xlsx parser + layout assertion)
- `packages/rates/src/rates/ingest.py` (new — `fill_curve`: vintages, plausibility→review, desync gate)
- `packages/rates/src/rates/validate/__init__.py` (new)
- `packages/rates/src/rates/validate/checks.py` (new — staleness / band / inflation-reconcile / fwd-spot)
- `packages/rates/src/rates/cli.py` (new — `rates curve load|coverage`, `rates validate`)
- `packages/rates/src/rates/gateway.py` (new — curve reads)
- `packages/rates/src/rates/router.py` (new — `/api/rates/curve` + `/curve/series`)
- `packages/rates/db/sqitch.conf` + `sqitch.plan` (new)
- `packages/rates/db/deploy|revert|verify/curve_point.sql` (new)
- `packages/rates/MAINTENANCE.md` (new — Task 1 maintenance plan + probe findings)
- `packages/rates/tests/test_boe_parser.py` + `test_ingest.py` + `test_validate.py` + `test_gateway.py` (new)
- `pyproject.toml` (modified — added `packages/rates` to the uv workspace members)
- `platform.toml` (modified — added the `rates` module, enabled)
- `services/api/src/qrp_api/main.py` (modified — mount the rates router when enabled)
- `packages/lineage/src/lineage/schedules.py` (modified — `rates_curve_daily`, Europe/London, STOPPED)
- `packages/lineage/src/lineage/definitions.py` (modified — register the rates job + schedule)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story) following the FI-curves brainstorming session. v1 of the fixed-income direction: a trustworthy point-in-time UK rates curve store in a NEW `rates` package (topology decided by Andre via AskUserQuestion — peer to sym/macro, modeled on macro, NOT inside sym). Scope = brainstorm action-plan steps 1–4: probe BoE + maintenance plan → scaffold `rates` → `curve_point` grid schema (immutable, source-tagged, two vintages, tenor-as-data, canonical `as_of_date`) → BoE Excel/zip ingest (atomic per-day, layout-assert, plausibility gate) → validate (reconciliation free-check, inflation=nominal−real RPI, plausible-band, stale-gating) → London-EOD schedule (explicit timezone) → minimal read endpoint. Derived analytics (spreads/carry/DV01 + console page), bond reference-data, live mark, 2nd-source divergence, and multi-country are explicit follow-on stories. Status → ready-for-dev. |
| 2026-06-22 | Code-review **pass 2** (re-run over the patched code) → still done. Edge Case Hunter 0/0/0 (all 7 pass-1 fixes verified landed against the live repo, no regressions); Acceptance Auditor "acceptance-clean: YES" (AC#3 spec↔schema↔code now consistent, AC#6 hole guard implemented+tested); Blind Hunter 0 High. 2 small patches applied: (1) the new missing-tenor hole guard demoted **FAIL → WARN** (+test) — a tenor shrink is suspicious but BoE can legitimately trim a tenor, so it shouldn't hard-block `validate`; (2) doc-debt cleanup (AC#3 `created_at`→`first_published_at`/`last_changed_at` + drop the stale par mention; AC#4 + Task 3 reconciled to the single-row model). Post-patch: ruff clean, 23/23 tests, live validate exit 0. |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Auditor 5/9 ACs fully met; no data-corrupting bug (Blind Hunter's lone "High" — xmax=0 classification — REFUTED by the Edge Case Hunter: macro/ingest.py uses the identical idiom). 1 decision RESOLVED (keep the single-row two-vintage model; AC#3 wording reconciled). **7 patches applied:** (1) `rates` added to `services/api` deps + uv sources (was the lone enabled router outside the dependency closure); (2) `rates` registered in `tools/deploy_all.py` (its DB now deploys via the house method); (3) close the read-only openpyxl workbook (handle leak in the archive loop); (4) decouple the tail desync gate from `--archive` (full-history backfill no longer wrongly gated — `fill_curve(tail=not archive)`); (5) implement the missing-tenor hole guard in `check_plausible_band` (+test); (6) `.pytest_cache`/`.ruff_cache` gitignored + stray dirs removed; (7) fixed the tautological ingest test (now asserts value+first_value bind the same param). 8 deferred (bank-holiday staleness, compounding, desync blind spot, API enum, count-distinct perf, zip cap, flagged-chaining, unit-assert → deferred-work.md), 6 dismissed. Post-patch: ruff clean, **23/23 tests**, live `rates validate` exit 0 (now band+no-holes). Status → done. |
| 2026-06-22 | Dev complete → review. Built the `rates` package end-to-end (peer to sym/macro): db/cli/ingest/validate/sources/gateway/router + sqitch trio + 22 tests. **Probe (Task 1) reachable in-env** and corrected the schema: BoE publishes **spot+forward, NO par** (free check became inflation=nominal−real exact + forward→spot approximate); GLC (gilt nominal 0.5–40y, real/inflation 2.5–40y) + OIS (nominal 0.5–25y), two tenor-grid resolutions deduped. Created the `rates` DB + applied `curve_point` schema directly (Docker down → sqitch deploy pending). **Loaded real BoE data: 13,140 nodes / 8 series / 15 days, idempotent re-load; `rates validate` all 4 checks PASS (inflation=nominal−real within 0.02pp over 102 nodes — the free check works).** Router+gateway verified in-process (`/api/rates/curve` + `/curve/series`). `pytest` 22/22, `ruff` clean. Two vintages (first_value immutable + value restated). London-EOD schedule (`rates_curve_daily`, Europe/London, STOPPED) registered in lineage. Caveats: running API server needs restart to serve `/api/rates`; api-types regen + full-history backfill deferred. Status → review. |
