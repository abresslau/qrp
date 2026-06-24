# Story: Data Monitor — compact tab-less board with per-bucket instrument counts + commodities

Status: done

<!-- Created via bmad-create-story 2026-06-24 (Andre, three asks in one):
  (1) "make the Data Monitor EOD more compact so I can see most jobs without scrolling";
  (2) "its also missing instrument count for other types like commodities, fx, rates curves…";
  (3) "remove the EOD tab just keep as Data Monitor without any tab".
This enhances the existing Data Monitor › EOD board built under `dagster-job-buckets` (PART B). No
epic decomposition — standalone story, tracked inline in sprint-status (the project convention). -->

## Story

As the operator of QRP,
I want the Data Monitor to show **all** pipeline buckets — including commodities — on **one compact,
tab-less screen** with a per-bucket **instrument/series count**,
so that I can see every dataset's freshness *and* how much it covers at a glance, without scrolling
or clicking through a single-item tab.

## Acceptance criteria

1. **Tab-less area.** The Data Monitor area has **no tab strip**. The freshness board renders directly
   at **`/data-monitor`**; the `/data-monitor/eod` sub-route is gone (or redirects to `/data-monitor`).
   The rail still opens the area (sidebar links `/data-monitor`). Page title reads **"Data Monitor"**
   (drop the "— EOD" suffix).
2. **Compact / no-scroll.** At a laptop viewport (verify **1440×900** and **1366×768**) the whole board
   — header + every bucket row + footer — fits with **no vertical page scroll**. The bucket table may
   still scroll **horizontally** (it has `min-w-[820px]`), as today. Apply the project's **two-tier
   density** (tight by default, roomier at `2xl:`) per `feedback_responsive_density_two_tier`.
3. **Per-bucket instrument count.** Every bucket row shows a count of distinct entities at its actual
   business date, with a unit label: fx → **pairs**, commodities → **commodities**, rates → **curves**
   (or series), equity_prices → **priced** (already present), index_levels → **indices**, fundamentals
   / alt_data / macro → **series** (or sources), calculations → see AC#6 perf rule. A bucket that
   can't be counted shows "—", never an error.
4. **Commodities bucket.** A new **commodities** bucket appears on the board, reading
   `commodities.price_daily` **read-only** via `package_dsn("commodities")`, classified against the
   expected business date, with its existing Dagster **`commodities`** job surfaced (last-run pill +
   "Dagster ↗" + a "▷ Run" launch chip that triggers the `commodities` job).
5. **No Dagster job-name collision.** Adding commodities to the bucket taxonomy must NOT create a
   second Dagster job named `commodities` (one already exists from `schedules.py`). See the
   **CRITICAL guardrail** below.
6. **No perf regression.** Instrument counts are computed **single-day-scoped** (`count(DISTINCT
   id) WHERE date_col = <actual_date>`), which is index-cheap. Do **NOT** introduce a full-table
   `count(DISTINCT)` — the `calculations` bucket deliberately avoids it (the 12 s / 28-window trap;
   see `freshness_per_market` memory + the comment in `buckets.py`). The `/api/data-monitor/eod`
   endpoint must still **never 500** — one unreadable dataset degrades that row to `unknown`.
7. **Tests + lint.** `services/api/tests/test_data_monitor_eod.py` extended (count present per bucket,
   commodities bucket present, count is single-day not full-scan, resilience preserved). Full api +
   lineage suite stays green; ruff clean.

## Developer context — READ THIS FIRST

This is a **brownfield enhancement** of a working feature. The board, gateway, and taxonomy already
exist and are interdependent. Below is the current state of every file you'll touch, what changes,
and what must NOT break.

### The shared taxonomy is the spine — `packages/lineage/src/lineage/buckets.py`
ONE definition feeds BOTH the EOD page (via the API gateway) AND the Dagster bucket jobs. Today it
defines **9 buckets**: `fx, equity_prices, index_levels, rates, fundamental, alt_data, macro,
universe, calculations`. `commodities` is **absent** (the commodities package was added to Dagster
this session, but never wired into this taxonomy).

`Dataset` already has the fields you need:
- `wide: bool` → uses the broadly-complete *coverage session* + emits an entity count ("N entities at
  DATE"). Only `equity_prices` sets it today.
- `id_column: str | None` → the entity key counted by the coverage session. **Currently only read for
  `wide` datasets.** Your count work generalises this to all buckets (single-day count).
- `group_column: str | None` → per-subgroup worst-lag (only `rates`, by `country`).

**Changes:**
- Add a `commodities` `Bucket` → `Dataset(commodities, "commodities.price_daily", "as_of_date",
  "commodities.price_daily", wide=True, id_column="commodity_code")`. `wide=True` gives it the
  coverage-session entity count for free (~22 commodities/day, cross-sectional). Define
  `COMMODITIES = "commodities"` next to the other package constants. Place it in rail order near the
  other price datasets (suggest right after `equity_prices` or `index_levels`).
- Give the count-able non-wide datasets an `id_column` so the gateway can count them single-day:
  `fx_rate` (the currency-pair identity — **inspect the `fx_rate` schema for the exact column(s)**;
  count distinct pairs at the latest `as_of_date`), `fundamentals` (`composite_figi`),
  `macro.observation` / `altdata.observation` (the series/source key — inspect each schema),
  `rates.curve_point` (a curve identity — note: a node-level `count(DISTINCT)` is large; prefer a
  cheap single-day distinct over the curve key, or reuse the existing per-country grouping for the
  count and label it "curves"/"countries"). Leave `calculations` count off OR single-day-only per AC#6.

> ⚠️ **CRITICAL guardrail (AC#5) — Dagster job-name collision.** `packages/lineage/src/lineage/
> bucket_jobs.py` builds `BUCKET_JOBS` = one `@job` per entry in `BUCKETS`, and `definitions.py`
> registers `jobs=[sym_eod_job, rates_curve_job, rates_world_job, commodities_job, *BUCKET_JOBS]`.
> `commodities_job` (from `schedules.py`, `@job(name="commodities")`) already exists. If you add a
> `commodities` bucket, `bucket_jobs.py` will try to mint a second job named `commodities` →
> **duplicate-job-name error at definitions load** (the original 9 were verified collision-free; this
> breaks that). **Resolution (recommended):** have `bucket_jobs.py` SKIP any bucket whose job name is
> already provided by `schedules.py` (filter `commodities` out of the generated `BUCKET_JOBS`), so the
> EOD taxonomy gains the bucket (for the page) without a duplicate Dagster job. Keep the existing
> `commodities_job` + `commodities_daily` schedule as the canonical commodities job. **Verify
> `uv run python -c "import lineage.definitions"` loads with no duplicate-name error after your change.**

### The gateway — `services/api/src/qrp_api/modules/data_monitor/eod.py` (`EodMonitorGateway`)
Current behaviour (preserve it):
- `_row(bucket)` reads the representative dataset on the owning DB read-only (commodities resolves via
  `package_dsn("commodities")` — confirmed generic, and the `commodities` DB is deployed). It sets
  `coverage` (the count string) ONLY via `_coverage_session` (wide) or `_grouped` (group_column);
  plain `_max_date` buckets get `coverage = None` → **no count shown**. That's the gap.
- It is wrapped per-row in `try/except` → one bad dataset = `unknown`, never 500. **Keep this.**
- `classify(...)` decides ok/stale; the `coverage` string is informational only.

**Changes:**
- Add a single-day instrument count for non-wide datasets that have an `id_column`:
  `count(DISTINCT id_column) WHERE date_column = <actual_date>` — **scoped to the one actual date**
  (cheap, index-friendly; the same single-day `n_latest` pattern `_coverage_session` already uses at
  lines ~83-88). Do NOT scan all dates.
- Surface the count in the bucket row. **Recommended:** add a typed field (e.g. `instrument_count:
  int | None` + `instrument_label: str | None`) rather than overloading the freeform `coverage`
  string — cleaner for the page to render compactly and to test. Wire it through the router model.
- `wide` buckets (equity_prices, commodities) already yield "N entities" via `_coverage_session` — map
  that into the same count field for consistency so every row reads uniformly.
- Keep `calculations` cheap: either omit its count or compute it single-day only (one `as_of_date`).

### The API route + model — `services/api/src/qrp_api/modules/data_monitor/router.py`
`GET /api/data-monitor/eod` (KEEP this path — it's the data endpoint; renaming it is needless churn and
would ripple through api-types). Add the new count field(s) to the response model. Re-generate
`apps/web/lib/api-types.ts` after (the API is running on :8001; `npx openapi-typescript@7
http://127.0.0.1:8001/openapi.json -o apps/web/lib/api-types.ts` — same tool used this session).

### The page + table — `apps/web/app/data-monitor/`
- **`eod/page.tsx`** (server component): move its content to **`page.tsx`** (the area index). Drop the
  "— EOD" from the `<h1>`. Update the API-unreachable hint and any `/data-monitor/eod` references. Then
  **delete the `eod/` route**. (The current `page.tsx` is just `redirect("/data-monitor/eod")` — replace
  it with the board.)
- **`layout.tsx`**: remove the tab strip (the `DATA_MONITOR_SUBNAV.map(...)` `<div>`). Keep the
  height/flex wrapper (`h-[calc(100dvh-2rem)]` + `overflow-y-auto`) so the board still sizes to the
  viewport — that wrapper is part of the no-scroll goal; don't delete it, just drop the tab row. If the
  layout becomes a pure passthrough you may inline it, but keeping the sizing wrapper is the safe move.
- **`components/eod-table.tsx`** (client): this is where the **compactness** lives. Today each bucket
  row is tall because the cell stacks: label → "by {subcategory}" → coverage/note → **a wrapping row of
  run chips** (`▷ Run` + one chip per `run_subcategories`). The run-chip row is the biggest height sink
  across 9-10 rows. **Levers (apply enough to hit AC#2):**
  - Move the per-subcategory run chips OUT of the always-visible row — reveal on row hover, or into the
    expanded breakdown, or behind a single "▷ Run ▾" menu. Keep a whole-bucket run reachable.
  - Tighten row padding (`py-2.5` → ~`py-1.5`) tight-by-default, restore at `2xl:`.
  - Collapse the stacked metalines (subcategory / coverage / note) into one compact line.
  - Render the new instrument count compactly (e.g. a muted "· 16 pairs" on the meta line, or a small
    right-aligned column). Update the `BucketRow` TS type for the new field.
  - Header `Stat` cards: already two-tier (`2xl:p-4`); consider a tighter default so the 4 stats + board
    fit. Don't remove the stats.

### What must keep working (regression guardrails)
- The endpoint **never 500s** (per-row try/except + the platform-level degrades-to-None in `eod()`).
- The **stale-only** filter, **expand/collapse** breakdowns, and **launch (▷ Run)** → `POST
  /api/data-monitor/launch` all still work after the table refactor.
- Per-country rates worst-lag, per-universe equity coverage, index + universe breakdowns unchanged.
- `dagster_runs_available=false` path (daemon down) still renders.
- Single source of truth preserved: page freshness still derives from `buckets.py` (no drift).

## Verification (toolchain caveat)
- The web toolchain (`tsc`/`eslint`/`vitest`/`next build`) is **not runnable locally** (incomplete
  `apps/web/node_modules`; reinstalling is churn-forbidden per `feedback_minimize_dev_churn`). Verify
  the page via **headless Chrome / CDP** (the sanctioned method): load `/data-monitor` at 1440×900 and
  1366×768, assert no vertical page scroll on the board and that all buckets (incl. commodities) render
  with counts. Reuse a single CDP instance and kill it by command-line match when done
  (`feedback_headless_chrome_cleanup`). The dev server is on **:3001** this session (`:3000` taken by an
  unrelated Docker container); the API is on **:8001**.
- Backend: extend + run `services/api/tests/test_data_monitor_eod.py` (`uv run --package qrp-api pytest`
  or the project's api test command); `ruff check` the touched py. Confirm `import lineage.definitions`
  loads (no duplicate job).
- This is layout-correctness + new data, so CDP IS warranted (not a trivial CSS tweak —
  `feedback_scale_verification_to_change`).

## Out of scope / deferred
- Renaming the `/api/data-monitor/eod` endpoint (keep it).
- Multi-dataset-per-bucket (v1 uses one representative dataset per bucket).
- A historical/timeseries freshness view; this stays a single live snapshot (reload to refresh).

## Files (summary)
- `packages/lineage/src/lineage/buckets.py` — +commodities bucket, +`COMMODITIES`, +`id_column`s.
- `packages/lineage/src/lineage/bucket_jobs.py` — exclude `commodities` from generated `BUCKET_JOBS`
  (collision guard).
- `services/api/src/qrp_api/modules/data_monitor/eod.py` — single-day instrument count for all buckets.
- `services/api/src/qrp_api/modules/data_monitor/router.py` — +count field(s) on the model.
- `apps/web/app/data-monitor/page.tsx` — becomes the board (was a redirect).
- `apps/web/app/data-monitor/eod/page.tsx` — removed (content moved to index).
- `apps/web/app/data-monitor/layout.tsx` — drop the tab strip, keep the sizing wrapper.
- `apps/web/lib/nav.ts` — `DATA_MONITOR_SUBNAV = []` (no sub-tabs); check the subnav registry entry.
- `apps/web/components/eod-table.tsx` — compaction + render the count + `BucketRow` field.
- `apps/web/lib/api-types.ts` — regenerate against the live API after the model change.
- `services/api/tests/test_data_monitor_eod.py` — extend.

## Dev Agent Record

**Implemented 2026-06-24 (bmad-dev-story).** All 7 ACs met.

### Backend (taxonomy + counts + commodities)
- `lineage/buckets.py`: added `COMMODITIES` constant + a `commodities` bucket (`commodities.price_daily`,
  `wide`, `id_column="commodity_code"`, `count_label="commodities"`); added `count_label` to `Dataset`
  and `id_column`/`count_label` to fx (`quote_currency`/pairs), equity (names), index_levels
  (`sym_id`/indices), fundamental (`composite_figi`/names), alt_data (`composite_figi`/series), macro
  (`series_id`/series); rates gets `count_label="curves"` (composite-key count, no single id).
- `lineage/bucket_jobs.py`: `_EXTERNAL_JOB_BUCKETS = {"commodities"}` excludes it from generated
  `BUCKET_JOBS` (AC#5 — the dedicated `commodities` job in `schedules.py` owns the name; verified
  `definitions.py` loads with no duplicate, BUCKET_JOBS = 9, bucket_keys = 10).
- `data_monitor/eod.py`: new `_instrument_count` — a **trailing-window** (`>= max-90d`) `count(DISTINCT
  id)` (composite key for rates). Windowed not single-day because lagged/slow series (per-country
  curves, monthly macro) don't all print on the latest date — single-day read "1 curve"; windowed
  reads the real 36. Bounded + date-indexed (cheaper than the coverage GROUP BY); `calculations` +
  `universe` carry no id_column → no count (the fact_returns full-distinct perf trap / event-log).
  Added `instrument_count`/`instrument_label` to the row; endpoint still never-500s (per-row try/except).
- `data_monitor/router.py`: `EodBucketRow` gains `instrument_count`/`instrument_label`.

### Frontend (tab-less + compact)
- Moved the board to the area index `app/data-monitor/page.tsx` (was a redirect); **deleted**
  `app/data-monitor/eod/`; title "Data Monitor" (no "— EOD").
- `app/data-monitor/layout.tsx`: removed the tab strip, kept the viewport-sizing + overflow wrapper.
- `lib/nav.ts`: `DATA_MONITOR_SUBNAV = []` (no sub-tabs).
- `components/eod-table.tsx`: `BucketRow` += count fields; render the count inline on the label line
  (`· 28 pairs`, coverage string as its title); merged the stacked meta lines into one and inlined the
  run chips (reclaims a row per bucket); two-tier density (`py-1` base, `2xl:py-2`).

### Verification
- **Backend:** 48 tests (13 data_monitor incl. 4 new: windowed-distinct guard, rates composite count,
  no-count buckets, commodities-bucket-not-a-generated-job + 35 lineage); full api+lineage suite 208
  green; ruff clean; `import lineage.definitions` OK.
- **API restarted** → live `GET /api/data-monitor/eod` returns 10 buckets with counts (fx 28 pairs,
  commodities 22, rates 36 curves, macro 64 series, …); `api-types.ts` regenerated (carries the new
  fields). Launch chip for commodities resolves to the real `commodities` Dagster job.
- **CDP (headless Chrome, dedicated instance, cleaned up):** at **1440×900** and **1366×768** the board
  shows all 10 buckets with `needsScroll=false` (scrollHeight==clientHeight); no `/data-monitor/eod`
  tab (only `/data-monitor`); commodities row + `pairs`/`curves` counts present. Web tsc/eslint not
  runnable locally (the standing `node_modules` caveat) — page verified via CDP (sanctioned method).

### File List
- `packages/lineage/src/lineage/buckets.py` (M)
- `packages/lineage/src/lineage/bucket_jobs.py` (M)
- `services/api/src/qrp_api/modules/data_monitor/eod.py` (M)
- `services/api/src/qrp_api/modules/data_monitor/router.py` (M)
- `services/api/tests/test_data_monitor_eod.py` (M — +4 tests)
- `apps/web/app/data-monitor/page.tsx` (M — redirect → board)
- `apps/web/app/data-monitor/eod/page.tsx` (DELETED)
- `apps/web/app/data-monitor/layout.tsx` (M — tab strip removed)
- `apps/web/lib/nav.ts` (M — DATA_MONITOR_SUBNAV = [])
- `apps/web/components/eod-table.tsx` (M — count + compaction)
- `apps/web/lib/api-types.ts` (M — regenerated)

### Change Log
- 2026-06-24: Data Monitor de-tabbed (board at /data-monitor) + per-bucket trailing-window instrument
  counts + new commodities bucket (job-collision-guarded) + two-tier compaction (fits 1366×768
  no-scroll). Status → review.

## Senior Developer Review (AI) — 2026-06-24

**Outcome: Approve (after 3 patches).** Three adversarial layers (Blind / Edge / Acceptance Auditor)
on the 784-line, 10-file diff (generated api-types.ts excluded). Auditor: **AC1–AC7 all met**; the
documented single-day→trailing-90-day deviation holds AC6's intent on every property (bounded,
index-cheap, no full-table distinct, calc/universe carry no count, never-500). **Triage: 0 decision ·
3 patch (applied) · 1 defer · 3 dismiss.** No High survived.

Patches applied:
- **[Med] Dead link** — `apps/web/app/sym/page.tsx:131` linked the deleted `/data-monitor/eod` →
  fixed to `/data-monitor` (the one real regression from removing the route; grep confirmed it was
  the only stale link).
- **[Med] False API contract** — `router.py`/`buckets.py` comments described the count as "single-day
  / at the latest day" while the code is windowed → reworded to "recent trailing window".
- **[Low] Honesty caveats + null-label** — the compaction dropped the bucket `note`; restored
  `coverage`+`note` as a hover tooltip on the bucket label (inline re-broke the 1366×768 no-scroll —
  CDP-confirmed 785>736, reverted), covering count-less buckets too; fixed a dangling space when
  `instrument_label` is null.

Deferred (deferred-work.md): rates composite-count column names hardcoded in the gateway, decoupled
from the `Dataset`. Dismissed: SQL f-string interpolation (frozen `BUCKETS` constants, no injection),
`DATA_MONITOR_SUBNAV=[]` (sidebar gates on `sub.length`, palette iterates empty — both handled),
nav.ts whole-file CRLF churn (git normalizes; staged diff is 4/3).

Post-patch: ruff clean, 13 data_monitor tests green, CDP re-verified no-scroll @1440×900 & 1366×768.
Status → done.
