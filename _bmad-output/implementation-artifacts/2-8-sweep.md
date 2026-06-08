# Story 2.8: Immutability default and weekly re-fetch sweep

Status: review

## Story

As a maintainer,
I want immutable history with a weekly trailing-90-day re-fetch-and-compare sweep,
so that source-side retroactive corrections are detected without mutating history by default.

## Acceptance Criteria

1. **Given** default operation, **Then** stored history is immutable — no in-place overwrite path runs in normal backfill/delta.
2. **Given** `uv run sym sweep`, **When** it runs (weekly), **Then** it re-fetches the trailing 90 days, compares to stored raw, and reports divergences for review.
3. **Given** a detected source correction, **Then** it surfaces as a reviewable signal rather than a silent overwrite.

## Tasks / Subtasks

- [x] Task 1: immutability guard (AC: #1) — source-scan test asserts no `UPDATE prices_raw`
- [x] Task 2: divergence surface (AC: #3) — `prices_review.flag_type` extended with `sweep_divergence` (migration)
- [x] Task 3: `run_sweep` in `src/sym/ingest/pipeline.py` (AC: #2, #3) — `detect_divergences` + `run_sweep` (re-fetch trailing window, flag divergences, never overwrite, autocommit + error isolation, logs `mode='sweep'`)
- [x] Task 4: `sym sweep` CLI (AC: #2)
- [x] Task 5: tests in `tests/test_sweep.py` (6 tests, AC: #1–#3)

## Dev Notes

- **Immutability (AC #1) is already the design** (Story 2.3: `prices_raw` is `INSERT … ON CONFLICT DO NOTHING`; no UPDATE of price columns). This story makes it explicit and guards it with a source-scan test. `updated_at`'s trigger only fires on an UPDATE we never issue.
- **Why re-fetch matches stored raw:** the trailing 90 days are post-all-splits, and the adapter un-split-adjusts to *true raw*, so a faithful re-fetch reproduces the stored value exactly — any difference beyond a tiny tolerance is a genuine source-side retroactive correction, not noise.
- **Divergence as a reviewable signal (AC #3):** flagged in `prices_review` (`flag_type='sweep_divergence'`, idempotent UPSERT that never clobbers a human review), so it surfaces in DBeaver and the Epic 3 gate will hold that row's returns until reviewed — never a silent overwrite. Correcting/accepting is a review action.
- **Reuse:** `run_sweep` mirrors `run_load` (autocommit per-figi durability, error isolation, `read_active_with_cursor`, `fetch_with_retry`) and logs via the Story 2.6 `pipeline_run_log` with `mode='sweep'`.
- A confirmed correction would be applied by a deliberate, separate path (out of scope here); the sweep only *detects and reports*.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.8: Immutability default and weekly re-fetch sweep]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-10 — D1 immutability + sweep]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- Immutability was already the design (Story 2.3 `ON CONFLICT DO NOTHING`); now guarded by a source-scan test (no `UPDATE prices_raw`). `run_sweep` only reads + flags, never overwrites.
- Divergences surface as `prices_review` flags (`sweep_divergence`, idempotent UPSERT that never clobbers a human review), so the Epic 3 gate holds that row's returns until reviewed.
- `run_sweep` reuses the run-load machinery (autocommit per-figi, error isolation, `fetch_with_retry`) and logs via `pipeline_run_log` (`mode='sweep'`).
- **Verified live:** `sym sweep` → run #3 [success], checked=45, **divergences=0** — a faithful re-fetch reproduces stored true-raw exactly (no false positives; un-adjusted raw round-trips). Positive divergence path is unit-tested. 113 tests pass, ruff clean.

### File List

- `migrations/deploy|revert|verify/prices_review_sweep_flag.sql` (new) — allow `sweep_divergence`.
- `migrations/sqitch.plan` (modified).
- `src/sym/ingest/pipeline.py` (modified) — `detect_divergences`, `run_sweep`, sweep constants.
- `src/sym/cli.py` (modified) — `sym sweep`.
- `tests/test_sweep.py` (new, 6 tests).
- `_bmad-output/implementation-artifacts/2-8-sweep.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.8: immutability guard + weekly `sym sweep` (re-fetch trailing 90d, flag source-side corrections in `prices_review` without overwriting; logged as a run). 6 tests; verified live (0 divergences). Status → review. |
