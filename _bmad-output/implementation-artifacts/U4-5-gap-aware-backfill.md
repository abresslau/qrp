# Story U4.5: Gap-aware full-history backfill (fix)

Status: review

## Story

As the pipeline,
I want backfill to fill a security's history down to the requested floor even when the forward cursor is current,
so that every name — especially index members first loaded from their membership-join date, and ticker-changed names — has its full price history since inception, not just from when it was first tracked.

## Context / Bug

Surfaced by a live test: **Square → Block (ticker SQ→XYZ)** had prices only from 2025-07-23, not its 2015 IPO. Two compounding causes:
1. Universe backfill floored each member at its **membership `valid_from`** (e.g. the rename/join date), not its inception.
2. `compute_window` skipped any name whose **forward cursor** was at the latest session — so a name loaded from a late start looked "complete" while its history *below* the earliest stored bar was never fetched.

## Acceptance Criteria

1. Backfill fetches `[floor, end]` whenever a name has not yet been backfilled down to the floor, regardless of the forward cursor; immutable ingestion fills only the missing earlier bars.
2. A name already backfilled to `<= floor` and current is skipped (no perpetual re-fetch — distinguishes "2004 is the IPO" from "2004 is an unfilled gap").
3. Universe backfill uses the full-history floor for prices (membership PIT boundary unaffected).
4. The SM-6 accuracy harness resolves benchmark names by ticker **+ exchange** (robust to the cross-exchange ticker collisions universe population introduces, e.g. MC = LVMH@XPAR vs Moelis@XNYS).
5. Tests cover the gap-aware window logic; full suite green.

## Tasks / Subtasks

- [x] Task 1: `pipeline_backfill_progress.floor_reached` migration (deployed + verified) — records the deepest floor a backfill covered (AC #2)
- [x] Task 2: gap-aware `compute_window` (skip only when `floor_reached <= floor` AND current) + `floor_reached_for`/`record_floor_reached` (AC #1, #2)
- [x] Task 3: `run_universe_load` uses the deep full-history floor (not `member_from`); leaver end-caps retained (AC #3)
- [x] Task 4: SM-6 harness resolves benchmark by ticker+MIC from the Yahoo-symbol suffix (AC #4)
- [x] Task 5: tests (gap-aware cases, harness disambiguation) + full re-backfill population (AC #5)

## Dev Notes

- `floor_reached` is the deepest floor a *successful* backfill requested. Skip iff `floor_reached <= floor AND cursor >= end`. Existing rows are NULL → the next backfill re-fetches all (the one-time fix), after which `floor_reached` makes future backfills efficient. Immutable ingestion (ON CONFLICT DO NOTHING) means re-fetching inserts only genuinely-missing earlier bars.
- Price history is **factual and independent of the membership window**; `pit_valid_from` still governs *membership* queries only. This reinterprets U4.2's member-window floor for prices (membership-window backfill was the wrong lever for price completeness).
- The accuracy-harness fix is a robustness fix, not a tolerance change: the benchmark set is unchanged, names are just pinned to their exchange so a populated multi-exchange master can't shadow a benchmark name (LVMH was being shadowed by Moelis on the bare ticker `MC`).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- Migration `backfill_floor_reached` deployed + verified.
- `pipeline.py`: gap-aware `compute_window(floor_reached=...)`, `floor_reached_for`, `record_floor_reached` (set after each successful backfill load).
- `ingest.py`: `run_universe_load` uses the deep `DEFAULT_FLOOR` (or `--history-floor`) for prices, keeps leaver end-caps.
- `test_accuracy.py`: `_resolve_benchmark_figi` (ticker + Yahoo-suffix→MIC) — fixed the LVMH/Moelis collision; SM-6 green again (remaining TR gaps are the expected CA-heavy definitional ones under the 2500bps ceiling).
- 279 tests pass; ruff clean. Comprehensive re-backfill run to populate full history for all securities.

### File List
- `migrations/deploy|revert|verify/backfill_floor_reached.sql` (new); `migrations/sqitch.plan`
- `src/sym/ingest/pipeline.py` (gap-aware backfill + floor watermark)
- `src/sym/universe/ingest.py` (deep price floor)
- `tests/test_universe_ingest.py`, `tests/test_pipeline.py`, `tests/test_accuracy.py`
- `_bmad-output/implementation-artifacts/U4-5-gap-aware-backfill.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Fixed gap-aware full-history backfill (floor_reached watermark) + universe deep price floor + SM-6 harness exchange-disambiguation. Surfaced by the SQ→XYZ since-inception test. 279 tests pass. |
