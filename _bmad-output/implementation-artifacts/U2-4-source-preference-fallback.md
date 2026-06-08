# Story U2.4: Per-index source preference and automatic fallback

Status: review

## Story

As the universe layer,
I want each index to declare an ordered source preference with automatic fallback,
so that the layer always uses the best available source and degrades rather than breaks.

## Acceptance Criteria

1. An index config naming an ordered preference (e.g. FMP→ETF→Wikipedia) → orchestrator tries preferred, falls back on failure.
2. A successful fetch records which source produced each event (provenance).
3. All configured sources failing → orchestrator raises loudly (per-index), never silently "no members".
4. DB-free tests cover preference ordering + fallback-on-failure with fake providers.

## Tasks / Subtasks

- [x] Task 1: `IndexProvider` (registered under `index`) — ordered `source_pref`, try-each-fallback, empty-result falls through, all-fail raises (AC #1, #3)
- [x] Task 2: provenance via the event `source` field (each archetype stamps its own source) (AC #2)
- [x] Task 3: wire `source_pref` column → provider config in `refresh_universe`; register index provider + sources in `providers/__init__` (AC #1)
- [x] Task 4: DB-free tests with fake sources (ordering, fallback, empty-fallthrough, all-fail, registry build) (AC #4)

## Dev Notes

- One provider under `index`; it never names a concrete index reader — it selects archetype sources by preference. `DEFAULT_SOURCE_PREF = (fmp, etf_holdings, wikipedia)` (API-first, NFR4); a universe overrides via its `source_pref` column.
- Provenance is per-event: `MembershipChange.source` already carries the archetype (`wikipedia`, `etf_holdings:<etf>`, `fmp`), so the log records which source produced each change.
- `refresh_universe` now reads the `source_pref` column and merges it into the provider config; `CustomListProvider` tolerates the extra kwarg.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `index_provider.py`: `IndexProvider` orchestrator — ordered preference, fallback-on-`IndexSourceError`/empty, loud all-fail; `_build_from_config` pops `index`/`source_pref`. Self-registers under `index` and imports the three sources so they register.
- `refresh.py`: reads `source_pref` column, merges into provider config. `custom_list.py`: `__init__(**_)` tolerance.
- 11 DB-free tests (ordering/fallback/empty/all-fail/registry); full suite **238 passed**, ruff clean.

### File List
- `src/sym/universe/providers/index_provider.py` (new)
- `src/sym/universe/providers/__init__.py` (modified — register index provider)
- `src/sym/universe/refresh.py` (modified — source_pref column → provider config)
- `src/sym/universe/providers/custom_list.py` (modified — **_ kwargs)
- `tests/test_universe_index_provider.py` (new)
- `_bmad-output/implementation-artifacts/U2-4-source-preference-fallback.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.4: IndexProvider with ordered source preference + automatic fallback, provenance via event source, source_pref column wiring. 11 DB-free tests; 238 pass. |
