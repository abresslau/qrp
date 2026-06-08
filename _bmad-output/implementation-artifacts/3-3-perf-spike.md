# Story 3.3: View-performance spike at scale (GATING)

Status: review

## Story

As an architect,
I want to confirm `v_prices_adjusted` + `fact_returns` recompute meet the SM-4 <10s cross-sectional bound at ~20M rows,
so that the view/materialization boundary is validated before certifying the returns engine.

## Acceptance Criteria

1. **Given** ~20M price rows (synthetic or loaded), **When** a cross-sectional returns query runs, **Then** it completes within SM-4's <10s bound.
2. **Given** a failure to meet the bound, **Then** the view/materialization boundary is revisited and the decision recorded before proceeding.
3. **Given** the workflow, **Then** this spike is a documented gate that must pass before the returns engine is certified (OI-1).

## Tasks / Subtasks

- [x] Task 1: isolated benchmark harness `benchmark/perf_spike.py` (bench schema, 20M unlogged rows, same view/indexes, dropped after)
- [x] Task 2: timed query patterns (cross-sectional snapshot; cross-sectional single-window return; full-view scan)
- [x] Task 3: gate decision recorded — **PASS**; materialization boundary validated; directive for 3.4

## Dev Notes

- **What the gate actually bounds (SM-4):** a *cross-sectional* query — "for one asof + window, all securities" — must be <10s. That's a few-thousand-row result. The full recompute (every asof × 18 windows) is a *batch* job, not the <10s path, which is exactly why `fact_returns` is a materialized loader-written table (AR-7) read by cross-sectional queries.
- **Hypothesis:** `v_prices_adjusted`'s per-row LATERAL into the tiny `corporate_actions` table is cheap when the query is *filtered* (one asof → ~4k rows → ~4k tiny index lookups), so cross-sectional reads pass; a *full* view scan (20M LATERALs) is slow — which validates materializing `fact_returns` rather than querying the view live for everything.
- **Isolation:** the spike runs in a `bench` schema with unlogged synthetic tables and drops it after — the real 339k-row warehouse is never touched.
- **Outcome of the gate (AC #3):** PASS → proceed to the `fact_returns` loader (3.4). FAIL → revisit the view/materialization boundary and record the decision here before continuing.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.3: View-performance spike at scale (GATING)]
- [Source: _bmad-output/planning-artifacts/epics.md#OI-1 — View-perf spike (GATING)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

**Result at 20,000,000 rows (4,000 securities × 5,000 sessions; PostgreSQL 18.4, local):**

| Query | Time | Verdict |
|---|---|---|
| cross-sectional snapshot (view, 1 asof, all securities) | **0.39s** | PASS |
| cross-sectional 1Y return (view self-join at base date) | **0.29s** | PASS |
| full-view scan (recompute-from-view, all 20M rows) | 529.93s (~8.8 min) | info |

- **GATE: PASS** — the SM-4 cross-sectional bound (<10s) is met with **>25× headroom** (0.39s). A filtered query touches ~4,000 rows → ~4,000 tiny LATERAL lookups into the small `corporate_actions` table → sub-second.
- **Materialization boundary VALIDATED (OI-1):** the full-view scan at ~530s proves you must **not** compute the whole returns matrix by scanning `v_prices_adjusted` live — confirming `fact_returns` as a materialized, loader-written table with incremental dirty-set refresh (AR-7), read by fast cross-sectional queries.
- **Directive for Story 3.4:** the per-row LATERAL view is for *filtered/cross-sectional reads*, not bulk recompute. The `fact_returns` initial build must compute adjusted prices **set-based** (e.g. a window/range join over the splits, or materialize the adjusted series once) rather than scanning the view row-by-row; incremental refresh then reads only the dirty slice via the view.
- Isolation held: the `bench` schema was created, measured, and dropped — the real 339k-row warehouse was untouched.

### File List

- `benchmark/perf_spike.py` (new) — the reproducible 20M-row spike harness.
- `_bmad-output/implementation-artifacts/3-3-perf-spike.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Ran Story 3.3 GATING spike at 20M rows: cross-sectional 0.39s (PASS, SM-4 <10s), full-view scan 530s. Gate PASS; materialization boundary validated (fact_returns must be materialized, not live-scanned); set-based bulk-adjust directive recorded for 3.4. Status → review. |
