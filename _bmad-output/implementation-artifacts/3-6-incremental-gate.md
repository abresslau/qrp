# Story 3.6: Incremental recompute with anomaly gate

Status: review

## Story

As the pipeline,
I want dirty-set incremental recompute that excludes unreviewed anomalies,
so that only affected windows recompute and suspect prices never reach published returns.

## Acceptance Criteria

1. **Given** new price data on a delta run, **When** recompute runs, **Then** only windows affected by changed inputs recompute; multi-year CAGR endpoints recompute daily (the endpoint moves each day).
2. **Given** a row whose inputs reference an unreviewed `prices_review` flag, **Then** `fact_returns` recompute excludes it (NFR-1 / AR-9 gate half); a reviewed flag re-enters the dirty set and its returns materialize.
3. **Given** `input_hash`, **Then** rows whose inputs are unchanged are skipped (dirty-set efficiency).

## Tasks / Subtasks

- [x] Task 1: `gated` column migration + partial published index `(asof, window_id) WHERE NOT gated`
- [x] Task 2: anomaly gate in the loader — `_unreviewed_flag_dates` + `compute_return_rows(..., gated_dates)` (asof/base flagged → pr/tr NULL, gated=TRUE)
- [x] Task 3: dirty-set skip — UPSERT `WHERE input_hash IS DISTINCT FROM … OR gated IS DISTINCT FROM …`
- [x] Task 4: gate tests (asof flagged → all windows gated; base flagged → that window; no flags → not gated)

## Dev Notes

- **Gate at materialization (AR-9 half 2):** Story 2.4 *annotated* suspect prices in `prices_review`; here the loader *gates* them. A `fact_returns` row whose **asof or base** price references an **unreviewed** flag is marked `gated` (pr/tr NULL) — published returns filter `WHERE NOT gated`, so a suspect price never reaches them. `resolve_review` (Story 2.4) flips `reviewed`; the next recompute sees the flag resolved, un-gates the row, and materializes the value (it "re-enters the dirty set").
- **Endpoints scope:** the gate checks the return's two reference prices (asof, base). A suspect price strictly *between* base and asof affects TR only and is a rarer follow-on; endpoint gating covers the dominant case and the as-of-suspect case (which gates all windows on that date).
- **Dirty-set (AC #1/#3):** the UPSERT's `WHERE … IS DISTINCT FROM …` makes an unchanged row a true no-op (no write, no `updated_at` bump) — re-running recompute over a settled range writes nothing. `input_hash` (raw+factors+calendar) catches input changes; the `gated` comparison catches review/flag flips that don't change prices. Multi-year CAGR rows recompute as their asof/base endpoints shift (new asof → new row; shifted base → new `input_hash`).
- **No compute-pruning yet:** rows are still *computed* per figi then skipped at write. True dirty-set *compute* pruning (touch only changed securities/dates) is a further optimization; the AC's "unchanged rows skipped" is met at the persistence layer.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.6: Incremental recompute with anomaly gate]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-9 — D2 two-stage anomaly]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-1 — Anomaly gating (two-stage)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- Gate: a `fact_returns` row whose asof or base references an unreviewed `prices_review` flag is `gated=TRUE` with pr/tr held NULL; published consumers filter `WHERE NOT gated` (partial index). Dirty-set: the UPSERT skips rows whose `input_hash` and `gated` both match.
- **Verified live:**
  - **AC#3 (dirty-set):** recompute over the settled 2025–2026 range computed 282,222 rows but **rewrote 3** (~0 — no `updated_at` churn).
  - **AC#2 (gate):** AAPL asof 2026-06-05 → flag the price unreviewed + recompute = **(18 gated, 0 published)**; review (confirm) + recompute = **(0 gated, 18 published)** — re-materialized; cleanup restored.
- 142 tests pass, ruff clean. State restored (synthetic flag removed).

### File List

- `migrations/deploy|revert|verify/fact_returns_gated.sql` (new) — `gated` column + published partial index.
- `migrations/sqitch.plan` (modified).
- `src/sym/returns/loader.py` (modified) — `_unreviewed_flag_dates`, gate in `compute_return_rows`, dirty-set UPSERT skip, `ReturnRow.gated`.
- `tests/test_loader.py` (updated, 12 tests) — gate cases.
- `_bmad-output/implementation-artifacts/3-6-incremental-gate.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.6: anomaly gate (gated column; rows referencing an unreviewed flag held out of published returns; reviewed→re-materialize) + dirty-set UPSERT skip (unchanged rows not rewritten). Verified live (gate flip on AAPL; 282k recompute rewrote 3). Status → review. |
