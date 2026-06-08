# Story U1.7: Seed the existing 50-name universe as the first custom-list universe

Status: review

## Story

As Andre,
I want the existing 50-name seed loaded as a custom-list universe end-to-end,
so that I have a real universe and fixtures/SM-6 keep working.

## Acceptance Criteria

1. A custom-list provider (the first concrete `UniverseProvider`, kind `custom_list`) emits join events from a list of identifiers (the seed: ticker+MIC tokens).
2. `universe add seed --kind custom_list --from benchmark/seed_universe.toml` then `universe refresh seed` appends join events, resolves members **reusing existing securities** (local lookup), and projects the resolved names into `universe_membership` — with unresolved seed delistings retained-and-flagged.
3. `members('seed', today)` returns the seed's current members, joinable to `fact_returns`; the existing returns/SM-6 machinery runs unchanged (NFR9).
4. `pit_valid_from('seed')` is set appropriately. Live verification against the populated DB.

## Tasks / Subtasks

- [x] Task 1: custom-list provider (`providers/custom_list.py`) — first concrete `UniverseProvider`; loads `seed_universe.toml`, emits one `join` per name (ticker:T@MIC, else isin:X) at the universe inception date; self-registers under `custom_list` (AC #1)
- [x] Task 2: refactor `resolve_universe_members(conn, universe_id, resolve_fn)` to take a resolver strategy; add `make_openfigi_resolve_fn` (existing path) + `make_local_resolve_fn` (security_symbology lookup — reuse existing securities) (AC #2)
- [x] Task 3: `refresh.py` orchestration — provider → append_changes → resolve (local) → rebuild_projection; CLI `universe refresh <id>` + `--from PATH` on `universe add` (AC #2, #4)
- [x] Task 4: DB-free tests (provider emits expected tokens from a fixture; local-resolver token parsing) + live verification (add+refresh seed; 45 resolved + 5 delistings retained; `members('seed', today)` joins fact_returns; rebuild) (AC #3, #4)

## Dev Notes

- **Custom-list provider (AC #1):** the first concrete `UniverseProvider` (kind `custom_list`). For the seed it loads `benchmark/seed_universe.toml` via `identity.universe.load_seed_universe` and emits one `join` `MembershipChange` per name with token `ticker:<T>@<MIC>` (preferred) or `isin:<ISIN>`, `effective_date = inception`. Self-registers via `register_provider`. (A generic list format is a later enhancement; the seed is the concrete instance here.)
- **Reuse existing securities (AC #2):** the seed's 44 names are already resolved in `securities`/`security_symbology` (Story 1.6), so resolution is a **local lookup** (`security_symbology` current ticker/isin → `composite_figi`), not a re-hit of OpenFIGI — deterministic, offline, and reusing prior work. Refactor `resolve_universe_members` to accept a `resolve_fn` strategy; `make_local_resolve_fn` does the local lookup, `make_openfigi_resolve_fn` wraps the U1.3 path (for U2 index providers bringing new names). The 5 seed delistings aren't in `securities` → resolved `unresolved`, retained (survivorship).
- **Inception date / pit (AC #4):** a custom list has no membership history, so all joins use a single inception date = `pit_valid_from` (set on `add`, default today). Re-running `refresh` re-emits joins at the same date → deduped by the event log (idempotent). `members('seed', today)` → the resolved set; querying before `pit_valid_from` is refused.
- **`refresh` flow:** look up the universe (kind+config) → `get_provider(kind, **config)` → `members()` → `append_changes` → `resolve_universe_members(local)` → `rebuild_projection`. One command makes a universe live end-to-end.
- **NFR9:** the seed becomes a *universe* but the underlying `securities`/prices/`fact_returns` are untouched, so returns + SM-6 run unchanged.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.7]
- [Source: src/sym/identity/universe.py — load_seed_universe / SeedSecurity]
- [Source: src/sym/universe/{registry,events,resolution,projection}.py — the U1.1–U1.6 spine]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `providers/custom_list.py`: the first concrete `UniverseProvider` (kind `custom_list`), self-registering; loads `seed_universe.toml` and emits one `join` per name (`ticker:T@MIC` preferred, else `isin:X`) at the inception date.
- Refactored `resolve_universe_members(conn, universe_id, resolve_fn)` to a pluggable strategy; `make_local_resolve_fn` resolves against `security_symbology` (reuse existing securities — offline, deterministic), `make_openfigi_resolve_fn` wraps the U1.3 OpenFIGI path (for U2 index providers bringing new names). `_parse_token` factored.
- `refresh.py` + CLI `universe refresh <id>` (and `--from PATH` on `add`): provider → `append_changes` → resolve → `rebuild_projection`; sets `pit_valid_from` to the inception on first refresh.
- **Verified live (end-to-end, persisted):** `universe add seed --from benchmark/seed_universe.toml` then `universe refresh seed` → appended 50 events, **45 resolved (local, no network), 5 delistings retained-unresolved**, projected 45 figis/intervals; `pit_valid_from=2026-06-07`; `members('seed', today)`=45, of which 44 join `fact_returns` (the 45th is Reliance/XNSE — resolved but no calendar/returns, still correctly a member). Returns/SM-6 unchanged (NFR9; 206 tests pass). The `seed` universe is left populated (it's the deliverable).
- 206 tests pass (+4 in `test_universe_custom_list.py`), ruff clean.

### File List

- `src/sym/universe/providers/__init__.py` (new) — registers built-in providers on import.
- `src/sym/universe/providers/custom_list.py` (new) — custom-list provider + `member_token`.
- `src/sym/universe/resolution.py` (modified) — `_parse_token`, `ResolveFn`, `make_local_resolve_fn`/`make_openfigi_resolve_fn`, `resolve_universe_members(conn, universe_id, resolve_fn)`.
- `src/sym/universe/refresh.py` (new) — `refresh_universe` orchestration.
- `src/sym/cli.py` (modified) — `universe refresh` + `--from` on `universe add`.
- `tests/test_universe_custom_list.py` (new, 4 tests).
- `_bmad-output/implementation-artifacts/U1-7-seed-custom-list.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U1.7: custom-list provider + local (reuse-securities) resolver + `refresh` orchestration + `universe refresh`/`--from` CLI. Seeded the 50-name universe end-to-end (45 resolved, 5 delistings retained; members join fact_returns). 206 tests pass, ruff clean. Completes Epic U1. Status → review. |
