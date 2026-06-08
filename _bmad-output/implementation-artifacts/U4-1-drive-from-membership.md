# Story U4.1: Drive ingestion from maintained membership

Status: review

## Story

As the pipeline,
I want `run_load` to read its security set from maintained universe membership,
so that ingestion tracks whatever universes are defined, not a hardcoded seed.

## Acceptance Criteria

1. `run_load --universe <id>` reads members active as-of the run (resolved) from `universe_membership` instead of the static seed.
2. The existing returns + SM-6 machinery runs unchanged over the resulting set (NFR9 — no regression).
3. DB-free tests cover member-selection; live-verified by running against the `seed` universe and matching prior behavior.

## Tasks / Subtasks

- [x] Task 1: `run_load` selection hooks (`securities`, `floor_for`, `end_cap_for`) — backward compatible (AC #1)
- [x] Task 2: bridge `ensure_universe_securities` — create `securities` rows for resolved members missing from the master (reuse `write_security`) so they're priceable (AC #1, #2)
- [x] Task 3: `universe_securities` selection + `run_universe_load`; CLI `--universe` on backfill/delta/dev (AC #1)
- [x] Task 4: DB-free selection-hook tests + live verification on seed + sp500 (AC #2, #3)

## Dev Notes

- The bridge reconstructs a one-off `SeedSecurity` from each member's frozen `(ticker, mic)` token + CompositeFIGI and reuses the tested `write_security` (currency/country from the exchange table). A token with no usable MIC or an unknown exchange is skipped + counted (coverage gap), never a crash.
- `run_load` gained three optional hooks so universe ingestion reuses the *same* tested pipeline (fetch/ingest/run-log/error-isolation) — no parallel engine. NFR9 holds because the returns engine already spans all securities.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `pipeline.run_load`: `securities` / `floor_for` / `end_cap_for` hooks (default behavior unchanged).
- `universe/ingest.py`: `ensure_universe_securities` (bridge), `universe_securities` (selection), `run_universe_load`.
- **Live-verified:** `run_universe_load('seed','dev')` drove from membership and matched prior behavior (3 attempted, all up-to-date → skipped, no regression). Bridge on sp500 created **628 securities** (in_master 22→650, 0 skipped). A 5-name sp500 dev load wrote 88 price rows, 4 newly priced, 0 errors.
- 266 tests pass; ruff clean.

### File List
- `src/sym/ingest/pipeline.py` (modified — selection hooks)
- `src/sym/universe/ingest.py` (new)
- `src/sym/cli.py` (modified — `--universe`/`--limit` on load commands)
- `tests/test_universe_ingest.py` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U4.1: universe-driven ingestion (selection hooks + bridge + run_universe_load). Live-verified on seed + sp500. |
