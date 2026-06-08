# Story U1.3: Membership resolution bridge (ISIN-first, as-of, frozen)

Status: review

## Story

As the pipeline,
I want each member resolved to a CompositeFIGI via the ISIN-first OpenFIGI resolver, as-of its membership date and frozen at first resolution,
so that identity is stable, recycled tickers can't corrupt history, and unresolved members are retained, not dropped.

## Acceptance Criteria

1. A migration adds `universe_member_resolution` (`universe_id` FK, `raw_identifier`, `composite_figi` NULL, `share_class_figi` NULL, `resolution_status` ∈ {resolved, unresolved, unpriced}, `detail`, `resolved_at`), PK `(universe_id, raw_identifier)`.
2. A resolvable member → `composite_figi` + status `resolved`, **frozen** (re-resolution is a no-op unless an explicit correction).
3. An unresolvable member → retained with status `unresolved` (never dropped); share-class ambiguity → flagged (reuse Story 1.6 `share_class_conflict`).
4. A recycled ticker → an already-frozen member keeps its original FIGI (the PK + ON CONFLICT DO NOTHING freezes it).
5. Reuses `src/sym/identity/figi.py` (ISIN-first/fallback). DB-free tests with a fake OpenFIGI client; live verification against OpenFIGI.

## Tasks / Subtasks

- [x] Task 1: `universe_member_resolution` migration (deploy/revert/verify + sqitch.plan) — PK `(universe_id, raw_identifier)`, FK→universe, status CHECK, figi format CHECK; no updated_at (frozen) (AC #1, #4)
- [x] Task 2: `RESOLUTION_STATUSES` constants in registry; `MemberResolution` outcome + `resolve_identifiers(client, exch_codes, raw_identifiers)` pure resolver reusing `plan_resolutions` (token → SeedSecurity → Resolution → MemberResolution) (AC #2, #3, #5)
- [x] Task 3: `resolve_universe_members(conn, client, universe_id)` — read exch_codes + unresolved member ids, resolve, write rows ON CONFLICT DO NOTHING (frozen) (AC #2, #3, #4)
- [x] Task 4: DB-free tests (token parse; outcome mapping; `resolve_identifiers` with a fake client incl. unresolved + ambiguous) + live verification (resolve a real member; re-run frozen; unresolvable retained) (AC #5)

## Dev Notes

- **Reuse the existing resolver fully (AC #5):** parse each member's `raw_identifier` token (`ticker:T@MIC` | `isin:XXX`, the `source_key` convention) into a one-off `SeedSecurity`, batch through `identity/figi.plan_resolutions(seeds, client, exch_codes)` — this gets the ISIN-first/fallback + home-listing narrowing + share-class-conflict detection for free. Map each `Resolution.outcome`: `ASSIGNED`→resolved (+composite/share_class_figi); `NO_FIGI_FOUND`→unresolved; `AMBIGUOUS_FIGI`/`SHARE_CLASS_CONFLICT`→unresolved with `detail` (retain-and-flag, never drop).
- **Frozen identity (AC #2/#4):** PK `(universe_id, raw_identifier)` + `INSERT ... ON CONFLICT DO NOTHING`; once a member is resolved its FIGI is fixed, so a later ticker recycle can't re-point it. `resolve_universe_members` only resolves members **not yet** in the table (the unresolved/new set), so it's cheap to re-run.
- **No FK on `composite_figi`:** a resolved member's FIGI need not yet exist in `securities` (ingestion is U4) — retain-and-flag means we record identity regardless. Format CHECK only (mirrors `securities_composite_figi_chk`). No `updated_at` — rows are frozen/immutable.
- **`unpriced`** is in the status domain for U4 (resolved but no prices yet); U1.3 writes only `resolved`/`unresolved`.
- **Testability:** `resolve_identifiers` is pure (client + exch_codes + ids → outcomes) → DB-free with the `_FakeClient` pattern from `tests/test_figi.py`; `resolve_universe_members`' SELECT/INSERT/freeze is verified live.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.3]
- [Source: src/sym/identity/figi.py — plan_resolutions (ISIN-first/fallback, narrowing, share-class conflict)]
- [Source: src/sym/identity/universe.py — SeedSecurity / ResolutionInput]
- [Source: src/sym/identity/lifecycle.py + securities migration — retain-and-flag / FIGI format CHECK]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `universe_member_resolution` deployed + verified: PK `(universe_id, raw_identifier)` (the freeze), FK→universe, status CHECK ∈ {resolved,unresolved,unpriced}, figi format CHECK, a `resolved ⇒ composite_figi NOT NULL` CHECK, idx on composite_figi. No `securities` FK (ingestion is U4) and no `updated_at` (frozen).
- `resolution.py` reuses `identity/figi.plan_resolutions` fully: a member token (`ticker:T@MIC`|`isin:XXX`) → one-off `SeedSecurity` → `plan_resolutions` (ISIN-first/fallback + narrowing + share-class detection) → `MemberResolution`. `resolve_universe_members` resolves only members **not yet** resolved and writes ON CONFLICT DO NOTHING (frozen); unresolvable members retained as `unresolved` with detail.
- **Bug caught by live verification** (not the DB-free tests): `_unresolved_identifiers` passed 2 params for a 1-placeholder correlated `NOT EXISTS` query → `ProgrammingError`. Fixed to a single param. (Exactly why DB queries get live-verified.)
- **Verified live (real OpenFIGI):** `ticker:AAPL@XNAS` → `BBG000B9XRY4` resolved; `ticker:BOGUSXYZ@XNYS` → unresolved, retained with `no_figi_found` detail (not dropped); re-run wrote 0 (frozen). Temp data cleaned up.
- 181 tests pass (+11 in `test_universe_resolution.py`), ruff clean.

### File List

- `migrations/deploy|revert|verify/universe_member_resolution.sql` (new) — frozen resolution table.
- `migrations/sqitch.plan` (modified) — added `universe_member_resolution` change.
- `src/sym/universe/registry.py` (modified) — `RESOLVED`/`UNRESOLVED`/`UNPRICED`/`RESOLUTION_STATUSES`, `InvalidMemberIdentifierError`.
- `src/sym/universe/resolution.py` (new) — token parse, `resolve_identifiers` (reuses `plan_resolutions`), `resolve_universe_members`.
- `tests/test_universe_resolution.py` (new, 11 tests) — token parse + outcome mapping + resolve_identifiers with a fake client.
- `_bmad-output/implementation-artifacts/U1-3-resolution-bridge.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story U1.3: frozen `universe_member_resolution` + `resolution.py` reusing the ISIN-first OpenFIGI resolver (`plan_resolutions`); unresolvable members retained-and-flagged. Live verification caught + fixed a 1-vs-2 placeholder bug in the unresolved-ids query. 181 tests pass, ruff clean; migration deployed + verified; real-OpenFIGI resolution + freeze verified live. Status → review. |
