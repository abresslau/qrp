# Story B2: Benchmark index level storage + Yahoo sourcing

Status: review

## Story

As Andre,
I want benchmark index level series stored under sym_id, level-only and variant-tagged,
so that I can later compare returns and compute alpha against them.

## Acceptance Criteria

1. `index_levels` (sym_id, session_date, variant PR/NTR/GTR, level, source), level-only, immutable, NOT prices_raw.
2. A benchmark registry maps each to a Yahoo symbol (and/or MSCI code) + variant; loader ensures instrument identity + upserts levels.
3. MSCI-only benchmarks get an instrument + `msci` xref but defer level loading (file import).
4. DB-free tests + live population.

## Tasks / Subtasks

- [x] Task 1: `index_levels` migration (variant CHECK, immutable; deployed + verified)
- [x] Task 2: `benchmarks/levels.py` — `Benchmark` registry (correct PR/NTR/GTR labels), `YahooIndexLevelSource`, `load_index_levels`
- [x] Task 3: CLI `sym benchmarks`; DB-free tests + live population

## Dev Notes

- Variants set explicitly (not all PR): `^SP500TR`/`^GDAXI`/`^BVSP` are total-return (GTR); MSCI World is Net (NTR). Mislabelling corrupts alpha.
- MSCI World has no reliable Yahoo symbol → instrument + `msci` xref created, levels deferred to a downloaded-file import.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `index_levels` migration deployed + verified.
- `benchmarks/levels.py`: registry, throttled `YahooIndexLevelSource`, `load_index_levels` (ensure instrument + immutable level upsert); `sym benchmarks` CLI.
- **Live-populated:** 12 instruments, **94,930 index levels** across 11 Yahoo benchmarks (S&P 500 PR+TR, Nasdaq, Dow, Russell 2000, EURO STOXX 50, FTSE 100, DAX, CAC 40, Nikkei, IBOVESPA); MSCI World deferred (msci xref). 0 gaps.
- 5 DB-free tests; ruff clean.

### File List
- `migrations/deploy|revert|verify/index_levels.sql` (new); `migrations/sqitch.plan`
- `src/sym/benchmarks/__init__.py`, `levels.py` (new)
- `src/sym/cli.py` (modified — `benchmarks` command)
- `tests/test_benchmarks.py` (new)
- `_bmad-output/implementation-artifacts/B2-index-levels.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story B2: index_levels store + Yahoo sourcing + registry. Live: 94,930 levels / 12 instruments. 5 DB-free tests. |
| 2026-06-07 | Simplified per operator: dropped the `variant` column — each published series (e.g. ^GSPC vs ^SP500TR) is its **own index instrument**, distinguished by name. `index_levels` PK is now (sym_id, session_date). |
