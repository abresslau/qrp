# Story U1.5: As-of query API, multi-universe set ops, and pit_valid_from guardrail

Status: review

## Story

As a researcher,
I want to query members as-of any date and across universes, with a `pit_valid_from` honesty boundary,
so that I get a correct cross-section and never a silently back-projected one.

## Acceptance Criteria

1. `members(universe, as_of)` returns the CompositeFIGI set valid on that date, joinable to `fact_returns`.
2. `as_of < universe.pit_valid_from` → **refuse/flag** (never back-project today's members onto the past).
3. Set operations across universes work — overlap, difference ("in A not B"), union; a security may be a member of multiple universes simultaneously.
4. DB-free tests for the date/guardrail logic; the `fact_returns` join verified live.

## Tasks / Subtasks

- [x] Task 1: `PitBoundaryError` / `UnknownUniverseError` in registry; pure `assert_within_pit(as_of, pit_valid_from)` (AC #2)
- [x] Task 2: `query.py` — `members(conn, universe_id, as_of)` (pit guard + as-of interval select) + `members_overlap` / `members_in_a_not_b` / `members_union` composing it (AC #1, #3)
- [x] Task 3: CLI `universe members <id> [--asof DATE]` (AC #1)
- [x] Task 4: DB-free tests (assert_within_pit; members + set ops via a fake conn) + live verification (as-of select; pit refusal; fact_returns join) (AC #4)

## Dev Notes

- **No migration** — reads `universe_membership` + `universe.pit_valid_from`. As-of select: `valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)` (half-open `[from, to)`, consistent with the projection's daterange).
- **pit guardrail (AC #2):** `assert_within_pit(as_of, pit_valid_from)` raises `PitBoundaryError` when `pit_valid_from` is set and `as_of < pit_valid_from`. If `pit_valid_from` is NULL (not yet set) there is no known boundary → allow (documented). An unknown universe → `UnknownUniverseError`.
- **Set ops (AC #3):** thin composition of `members()` (`&`, `-`, `|`); each call enforces its own universe's pit boundary. Membership is many-to-many, so a FIGI in both universes is naturally in the overlap.
- **Testability:** `assert_within_pit` is pure → DB-free. `members`/set-ops are exercised DB-free via a fake conn returning canned pit + membership rows, and live-verified (incl. the `fact_returns` join, which is the payoff — the research cross-section).
- **Scope:** reproducible snapshots (`log-version`) are **U1.6**; this story is the live as-of read.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.5]
- [Source: src/sym/universe/projection.py — interval semantics ([from, to))]
- [Source: _bmad-output/planning-artifacts/briefs/brief-sym-2026-06-06/brief.md — as-of query API, pit_valid_from, multi-universe set ops]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `query.py`: `members(conn, universe_id, as_of)` enforces the pit boundary then selects the half-open `[valid_from, valid_to)` interval valid on `as_of`; `members_overlap` / `members_in_a_not_b` / `members_union` compose it (multi-universe many-to-many). `assert_within_pit` is pure (NULL pit = no boundary). `PitBoundaryError` / `UnknownUniverseError` added to registry.
- CLI `universe members <id> [--asof DATE]` (figis to stdout, count to stderr; `UniverseError` → clean exit 1).
- **No migration** (reads `universe_membership` + `universe.pit_valid_from`).
- **Verified live:** `members` returns the as-of FIGI set joinable to `fact_returns` (the cross-section query returned 36 rows = 2 FIGIs × 18 windows); overlap `{B}`, in-a-not-b `{A}`; a query at 2019 against a universe with `pit_valid_from=2020-01-01` raised `PitBoundaryError` (no back-projection). Temp data cleaned up.
- 198 tests pass (+9 in `test_universe_query.py`), ruff clean.

### File List

- `src/sym/universe/query.py` (new) — `assert_within_pit`, `members`, set-op helpers.
- `src/sym/universe/registry.py` (modified) — `PitBoundaryError`, `UnknownUniverseError`.
- `src/sym/cli.py` (modified) — `universe members` command + parser wiring.
- `tests/test_universe_query.py` (new, 9 tests) — guardrail + members/set-ops via fake conn.
- `_bmad-output/implementation-artifacts/U1-5-asof-query-api.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story U1.5: as-of `members()` query + pit_valid_from guardrail + multi-universe set ops + `universe members` CLI. 198 tests pass, ruff clean; live: as-of cross-section joins fact_returns, set ops correct, pre-pit query refused. Status → review. |
