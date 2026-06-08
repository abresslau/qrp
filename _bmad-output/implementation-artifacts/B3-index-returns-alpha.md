# Story B3: Benchmark index returns + alpha

Status: review

## Story

As Andre,
I want benchmark index returns materialized and an alpha helper,
so that I can compare a security/universe return to a benchmark and compute excess return (alpha).

## Acceptance Criteria

1. `fact_index_returns` (sym_id, variant, window_id, as_of_date, ret) materialized from `index_levels` as level ratios over the 18 windows.
2. `alpha(asset_return, benchmark_return)` = excess; `benchmark_return(...)` resolves a benchmark's return for a (variant, window, date).
3. DB-free tests + live alpha verification.

## Tasks / Subtasks

- [x] Task 1: `fact_index_returns` migration (sym_id+variant keyed; deployed + verified)
- [x] Task 2: pure `index_return_rows` (reuse `returns.windows`; index's own level dates = sessions) + `recompute_index_returns`
- [x] Task 3: `alpha` + `benchmark_return` helpers; wire into `sym benchmarks`
- [x] Task 4: DB-free tests + live alpha demo

## Dev Notes

- Index returns are pure level ratios (no split/dividend math — variant already encodes the return treatment). The index's own level-date list is its session calendar (no `trading_calendar` dependency). Compare like-for-like variants (PR↔PR, TR↔TR) for clean alpha.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `fact_index_returns` migration deployed + verified.
- `benchmarks/returns.py`: pure `index_return_rows`, `recompute_index_returns`, `alpha`, `benchmark_return`; `sym benchmarks` now loads levels + recomputes index returns.
- **Live-verified:** 49,410 index-return rows / 11 series; alpha demo — Apple 10Y-ann 28.78% vs S&P 500 TR 15.33% → **alpha +13.45%** (asset − benchmark). (Demo mixes PR vs TR for illustration; match variants for production alpha.)
- 3 DB-free tests; full suite **324 pass**, ruff clean. Completes the Benchmark/sym_id epic (B1–B3).

### File List
- `migrations/deploy|revert|verify/fact_index_returns.sql` (new); `migrations/sqitch.plan`
- `src/sym/benchmarks/returns.py` (new)
- `src/sym/cli.py` (modified — benchmarks now recomputes index returns)
- `tests/test_benchmark_returns.py` (new)
- `_bmad-output/implementation-artifacts/B3-index-returns-alpha.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story B3: index returns (level ratios over 18 windows) + alpha helper. Live alpha verified (Apple +13.45% vs S&P 500 TR, 10Y). Completes Benchmark epic B1-B3. |
| 2026-06-07 | Dropped `variant` (separate-indexes simplification): `fact_index_returns` PK now (sym_id, window_id, as_of_date); `benchmark_return(sym_id, window_id, as_of_date)`. S&P 500 (^GSPC) and S&P 500 TR (^SP500TR) are distinct instruments — 10Y PR 13.40% vs TR 15.33%. |
