# Story B5: Link index universes to their benchmark level series

Status: review

## Story

As Andre,
I want each equity-index universe linked to its benchmark index level series,
so that I can put together the point-in-time constituents AND the index return/level at any date.

## Acceptance Criteria

1. `universe_benchmark` (universe_id, sym_id, role, is_primary) links a universe to one or more benchmark instruments; ≤1 primary per universe.
2. The benchmark registry covers all index universes (S&P 1500, European flagships, EURO STOXX 50).
3. Seeding links the existing universes; a query returns constituents + the primary benchmark level as-of a date.
4. DB-free tests + live verification.

## Tasks / Subtasks

- [x] Task 1: `universe_benchmark` migration (role CHECK, partial-unique primary; deployed + verified)
- [x] Task 2: expand benchmark registry (S&P 400 ^MID, S&P 600 ^SP600, IBEX ^IBEX, FTSE MIB FTSEMIB.MI, AEX ^AEX, SMI ^SSMI)
- [x] Task 3: `benchmarks/links.py` — `UNIVERSE_BENCHMARKS` map, `link_universe_benchmarks`, `universe_benchmarks`, `primary_benchmark`, `universe_with_benchmark`
- [x] Task 4: wire linking into `sym benchmarks`; `sym universe benchmark` view; DB-free tests + live verify

## Dev Notes

- A universe links to its price-return AND total-return benchmark (separate instruments); one primary. Membership keeps its `pit_valid_from` honesty boundary (pre-pit queries refused), while benchmark *levels* are factual back to vendor availability — so `universe_with_benchmark` joins them only within the trustworthy membership window, and the level series can be read directly before it.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `universe_benchmark` migration deployed + verified.
- Registry expanded to 18 benchmarks; `links.py` with mapping + seeder + query helpers; `sym benchmarks` now loads levels + recomputes returns + links universes; `sym universe benchmark <id> --asof` view.
- **Live-verified:** 18 instruments, 6 new index series loaded (0 gaps), **12 universe→benchmark links** (sp500 → S&P 500 PR + TR). `sp500` as-of 2026-06-05 → 503 constituents + S&P 500 level 7383.74; sp400 → 285 + 3693.56; sp600 → 324 + 1672.89. European (build-forward pit) correctly refuse pre-pit membership while levels remain available.
- 4 DB-free tests; full suite **331 pass**, ruff clean.

### File List
- `migrations/deploy|revert|verify/universe_benchmark.sql` (new); `migrations/sqitch.plan`
- `src/sym/benchmarks/levels.py` (registry expansion); `src/sym/benchmarks/links.py` (new)
- `src/sym/cli.py` (benchmarks links + `universe benchmark` view)
- `tests/test_universe_benchmark_link.py` (new)
- `_bmad-output/implementation-artifacts/B5-universe-benchmark-link.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story B5: universe↔benchmark link + registry expansion + constituents/benchmark as-of query. Live: 12 links, S&P 1500 + European benchmarks loaded. 4 DB-free tests. |
