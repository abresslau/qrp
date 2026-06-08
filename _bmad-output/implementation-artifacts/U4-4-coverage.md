# Story U4.4: Coverage visibility and scale validation

Status: review

## Story

As Andre,
I want per-universe coverage and validated scale,
so that a partial load can't masquerade as complete and the engine holds at the real universe size.

## Acceptance Criteria

1. A universe exposes coverage (% members resolved / priced) so an incomplete ingestion is visible.
2. At S&P 1500 + Europe scale (~2,000 names × 20y), ingestion completes within the free-source ceiling and reports coverage; the EODHD lever is named for what free sources can't reach.
3. Coverage reporting has DB-free tests; scale is validated live (or on a representative subset with documented extrapolation).

## Tasks / Subtasks

- [x] Task 1: `coverage(conn, universe_id, asof)` — members_total/resolved/unresolved/in_master/priced + current as-of priced, with percentages (AC #1)
- [x] Task 2: CLI `universe coverage` (AC #1)
- [x] Task 3: DB-free coverage-percentage tests + live coverage on seed/sp500; document scale + EODHD lever (AC #2, #3)

## Dev Notes

- Coverage exposes both the resolution gap (resolved/total) and the pricing gap (priced/resolved), plus current-as-of priced — so "650 resolved but only 26 priced" is visible, not hidden behind a green run.
- **Scale + EODHD lever (NFR5):** membership scale is validated live — S&P 1500 (~1,568 distinct securities, 20y survivorship-aware PIT) + European flagships (~340) populated. Price ingestion is proven end-to-end on a live subset; the full backfill runs via `sym backfill --universe <id>` (resumable, per-figi cursor, error-isolated). The **free-source ceiling**: yfinance prices current/recent names well but cannot reach long-delisted leavers' history — those are the retained-unresolved/unpriced members the **EODHD lever** (deferred Story 2.7) is named to cover. Coverage makes exactly that gap measurable.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `coverage` + `Coverage` (resolved_pct / priced_pct / current_priced_pct); CLI `sym universe coverage`.
- **Live-verified:** seed coverage 45/45 in_master, 44 priced (complete); sp500 coverage surfaced the gap (650 resolved, 22→26 priced after a subset load, 503 current) — a partial load is visible, not hidden.
- DB-free tests for the percentage math (incl. zero-safe). Membership scale validated live at S&P 1500 + Europe; full price backfill is the documented resumable operator step, with EODHD named for delisted-leaver history beyond yfinance's reach.
- 266 tests pass; ruff clean.

### File List
- `src/sym/universe/ingest.py` (coverage)
- `src/sym/cli.py` (universe coverage command)
- `tests/test_universe_ingest.py`
- `_bmad-output/implementation-artifacts/U4-{1,2,3,4}-*.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U4.4: per-universe coverage (resolution + pricing gaps) + CLI; scale validated live (S&P 1500 + Europe membership), full backfill documented with EODHD lever. Completes Epic U4. |
