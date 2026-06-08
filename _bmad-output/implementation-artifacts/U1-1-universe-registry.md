# Story U1.1: Universe registry & UniverseProvider abstraction

Status: review

## Story

As the pipeline,
I want a universe registry and a config-keyed `UniverseProvider` abstraction (mirroring AR-5),
so that universes are declared by config and new sources plug in without changing downstream code.

## Acceptance Criteria

1. A Sqitch migration adds a `universe` table (`universe_id`, `name`, `kind` ∈ {custom_list, index, criteria}, `config` jsonb, `pit_valid_from` date NULL, `source_pref` jsonb NULL, `created_at`, `updated_at`) wired to the shared `set_updated_at()` trigger (NFR6).
2. A `UniverseProvider` Protocol + `register_provider` registry (parallel to `src/sym/sources/registry.py`) lets a provider register under a kind/key and be resolved by config; an **unknown kind raises** rather than silently passing.
3. The CLI `universe add <id> --kind ...` and `universe list` persist and list a universe; an unknown kind is rejected.
4. A new provider registers **without modifying the registry** (the plug-in test).
5. DB-free unit tests cover the registry + store validation; the migration + CLI are verified live.

## Tasks / Subtasks

- [x] Task 1: `universe` table migration (deploy/revert/verify + sqitch.plan), `kind` CHECK, `set_updated_at` trigger (AC #1)
- [x] Task 2: `UniverseProvider` Protocol + config-keyed registry — `register_provider`/`get_provider`/`is_registered`/`registered_kinds`, unknown kind raises (AC #2, #4)
- [x] Task 3: universe store — `add_universe` (validate kind, persist) + `list_universes` (AC #1, #3)
- [x] Task 4: CLI `universe add` / `universe list` (AC #3)
- [x] Task 5: DB-free tests (registry + store validation + plug-in test) + live verification (deploy migration, add/list round-trip) (AC #5)

## Dev Notes

- **Mirror AR-5 exactly:** `src/sym/sources/registry.py` is the template — a module-level dict keyed by a string, `register_X` to add, `get_X` raising a typed error for an unknown key. Here the key is the universe **kind** (`custom_list | index | criteria`); concrete providers land in later stories (custom_list in U1.7, index in U2, criteria in U5), so U1.1 ships the abstraction + registry + a tested dummy provider only.
- **`UniverseProvider` Protocol** is the provider contract; keep it minimal (the membership-event shape firms up in U1.2). Define a small `MembershipChange` dataclass as the provider output type so the Protocol method is concrete and testable now.
- **Migration style:** follow `migrations/deploy/currency.sql` / `securities.sql` — `BEGIN; CREATE TABLE ...; CREATE TRIGGER ..._set_updated_at ...; COMMENT ...; COMMIT;`. `kind` CHECK mirrors `securities_status_chk`. Chain after `fact_returns_gated` in `sqitch.plan`, requiring `updated_at_trigger`. Deploy via the Docker sqitch image (no local sqitch) — `reference_sqitch_deploy_docker`.
- **`universe_id`** is a short stable slug the CLI takes positionally (e.g. `seed`, `sp500`); `name` defaults to the id unless `--name` given. `config`/`source_pref` are jsonb (psycopg3 adapts dict via `Jsonb`).
- **Validation:** `add_universe` validates `kind` against the literal kind set and raises `ValueError` *before* any DB write (clean error), independent of the DB CHECK backstop; argparse `--kind` uses `choices`.
- **Tests:** DB-free — registry register/get/unknown-raises + a dummy provider proves the plug-in test; `add_universe` raises on unknown kind without touching the DB. Live — deploy the migration, then `sym universe add` + `sym universe list` round-trip. New test file `tests/test_universe_registry.py` (the existing `tests/test_universe.py` covers the *seed loader* `sym.identity.universe`, a different module).

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.1]
- [Source: src/sym/sources/registry.py — AR-5 config-keyed registry pattern]
- [Source: migrations/deploy/currency.sql, securities.sql — migration + CHECK + trigger style]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `universe` registry table (id slug PK, name, kind CHECK ∈ {custom_list,index,criteria}, config/source_pref jsonb, pit_valid_from, created/updated + `set_updated_at` trigger) deployed via Docker sqitch and sqitch-verified.
- `UniverseProvider` Protocol (runtime-checkable) + config-keyed registry (`register_provider`/`get_provider`/`is_registered`/`registered_kinds`) mirroring `sources/registry.py` (AR-5); registering an invalid kind and getting an unregistered kind both raise `UnknownUniverseKindError`. `MembershipChange` dataclass defined as the provider output contract (firms up in U1.2).
- `add_universe` validates kind **before** any DB call (DB-free test asserts no DB touch on bad kind) and is idempotent (ON CONFLICT DO NOTHING); `list_universes` returns them ordered.
- CLI `universe add <id> --kind ... [--name --config --pit-from]` and `universe list`; `--kind` uses argparse `choices`.
- **Verified:** 159 tests pass (+6 new), ruff clean. Live: migration deployed; `add seed`/`add sp500`/`list` round-tripped; idempotent re-add reported "already exists"; unknown `--kind` rejected (exit 2). Demo rows cleaned up — `universe` left empty for U1.7/U2 to populate properly.

### File List

- `migrations/deploy|revert|verify/universe.sql` (new) — universe registry table.
- `migrations/sqitch.plan` (modified) — added `universe` change.
- `src/sym/universe/__init__.py` (new) — package.
- `src/sym/universe/registry.py` (new) — `UniverseProvider` Protocol, `MembershipChange`, config-keyed registry, kind constants, errors.
- `src/sym/universe/store.py` (new) — `add_universe` / `list_universes` + `Universe` dataclass.
- `src/sym/cli.py` (modified) — `universe add` / `universe list` commands + parser wiring.
- `tests/test_universe_registry.py` (new, 6 tests) — registry + plug-in test + store kind-validation.
- `_bmad-output/implementation-artifacts/U1-1-universe-registry.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story U1.1: `universe` registry table + `UniverseProvider` config-keyed registry (AR-5) + `add_universe`/`list_universes` + CLI `universe add`/`list`. 159 tests pass, ruff clean; migration deployed + verified live; CLI round-trip verified. Status → review. |
| 2026-06-06 | Addressed code-review findings: (bug) invalid `universe_id` now raises a clean typed `InvalidUniverseIdError` before the DB instead of an unhandled `CheckViolation` traceback — verified live (`add SP500` → clean error, exit 1); (cleanup) factored `validate_kind`/`validate_universe_id` helpers (de-duplicated the kind check across registry + store); (cleanup) restored cli.py lazy-import convention (`VALID_KINDS` imported inside `build_parser`). 164 tests pass (+5), ruff clean. Minor findings (stderr-on-no-op, positional `Universe(*row)`, config/source_pref None-asymmetry, verify-CHECK coverage) noted and deferred. |

## Code Review (AI)

**Outcome:** Changes Requested → addressed. One real bug + two cheap cleanups fixed; four minor/fragile-but-correct findings deferred.

- **[High — fixed]** Invalid `universe_id` (uppercase/empty/leading-dash/spaces) hit the DB `universe_id_format_chk` and raised an uncaught `psycopg.errors.CheckViolation` (not `OperationalError`) → raw traceback. Fixed: `validate_universe_id` raises `InvalidUniverseIdError` before the INSERT; the CLI catches `UniverseError` (base). Verified live.
- **[Low — fixed]** `cli.py` eager top-level `VALID_KINDS` import broke the file's lazy-import convention → moved into `build_parser`.
- **[Low — fixed]** Kind-validation duplicated verbatim across `register_provider` + `add_universe` → factored `validate_kind`.
- **[Low — deferred]** `_cmd_universe_add` prints "already exists" to stderr but returns 0; `Universe(*row)` positional coupling; `config`→`{}` vs `source_pref`→NULL asymmetry; `verify/universe.sql` doesn't assert the CHECK constraints (consistent with peer verify scripts). All low-impact; left as-is.
