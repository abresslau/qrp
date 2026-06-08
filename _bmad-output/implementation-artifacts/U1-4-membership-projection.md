# Story U1.4: Point-in-time membership projection

Status: review

## Story

As a researcher,
I want the event log projected to a point-in-time `universe_membership` interval table at the CompositeFIGI level,
so that I can ask who was a member on any date, survivorship-safe.

## Acceptance Criteria

1. A migration adds `universe_membership` (`universe_id` FK, `composite_figi`, `raw_identifier`, `valid_from`, `valid_to` NULL, `source`) with a btree_gist EXCLUDE no-overlap per `(universe_id, composite_figi)` and a `valid_to > valid_from` CHECK.
2. Given join/leave/correct events + resolutions, projection builds correct intervals **at the FIGI level**; a mid-membership ticker rename (two raw_identifiers, same FIGI) stays **ONE continuous interval** (not leave+rejoin).
3. A late/out-of-order corrective event → projection rebuilds **deterministically from the full ordered log** (not incremental).
4. A property test asserts `invert(project(log)) == log`; overlapping intervals are rejected by the EXCLUDE constraint.
5. DB-free projection unit tests + live verification on a small universe.

## Tasks / Subtasks

- [x] Task 1: `universe_membership` migration (deploy/revert/verify + sqitch.plan) — btree_gist EXCLUDE no-overlap, validity CHECK, figi CHECK, FK→universe (AC #1)
- [x] Task 2: pure `project_membership(events)` — group by composite_figi, order by `(effective_date, event_id)`, join/leave state machine + `correct` toggle, coalesce adjacent intervals (FIGI-level rename → one interval), drop zero-length (AC #2, #3)
- [x] Task 3: `rebuild_projection(conn, universe_id)` — read resolved events, project, full DELETE+INSERT in one txn (deterministic rebuild; EXCLUDE backstops overlaps) (AC #1, #3)
- [x] Task 4: DB-free tests (intervals, open-ended, rename-merge, correct-toggle, out-of-order determinism, zero-length, `invert(project)==log` round-trip) + live verification (rebuild a small universe; FIGI-level merge; no-overlap) (AC #4, #5)

## Dev Notes

- **FIGI-level projection (AC #2):** group events by `composite_figi` (joined to `universe_member_resolution`, resolved only — unresolved members are backlog, not in the interval table). Because two raw_identifiers (e.g. `ticker:FB@XNAS` then `ticker:META@XNAS`) resolve to the *same* FIGI, a rename appears as `leave(FB)@D` + `join(META)@D` → adjacent intervals `[…,D)` + `[D,…)` → **coalesced into one continuous interval**. Coalescing (merge where `prev.valid_to == next.valid_from`) is what delivers the "one interval" requirement.
- **State machine:** ordered by `(effective_date, event_id)`. `join`: open if closed; `leave`: close if open; `correct`: toggle (close if open, else open) — a corrective event undoes the member's current state at that date. Zero-length intervals (`valid_from == valid_to`, e.g. join+leave same day) are dropped (would violate the validity CHECK anyway).
- **Deterministic rebuild (AC #3):** `rebuild_projection` always re-derives from the **full ordered log** (DELETE the universe's rows, re-INSERT) — so a late event with an earlier `effective_date` simply re-sorts and yields the correct result; never incremental. One transaction; the EXCLUDE constraint is the loud backstop if the projector ever emits an overlap.
- **No `updated_at`:** the table is a rebuilt projection, not edited in place.
- **Migration:** mirror `security_symbology.sql` — `CREATE EXTENSION IF NOT EXISTS btree_gist;` + `EXCLUDE USING gist (universe_id WITH =, composite_figi WITH =, daterange(valid_from, valid_to, '[)') WITH &&)`.
- **Scope:** the *as-of query API*, `pit_valid_from` guardrail, multi-universe set ops are **U1.5**; U1.4 builds the table + rebuild and verifies via direct queries.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.4]
- [Source: migrations/deploy/security_symbology.sql — btree_gist EXCLUDE no-overlap pattern]
- [Source: _bmad-output/planning-artifacts/briefs/brief-sym-2026-06-06/addendum.md#B + FMEA §H (project at FIGI level, rebuild from full ordered log)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `universe_membership` deployed + verified: btree_gist EXCLUDE no-overlap per `(universe_id, composite_figi)` on `daterange(valid_from, valid_to, '[)')`, validity CHECK, figi CHECK, FK→universe, asof index. No `updated_at` (rebuilt projection).
- `projection.py`: pure `project_membership(events)` — groups by `composite_figi`, orders by `(effective_date, event_id)`, runs a join/leave state machine (`correct` toggles), **coalesces adjacent intervals** (the FIGI-level rename → one continuous interval), drops zero-length memberships. `rebuild_projection` re-derives from the full ordered log (DELETE+INSERT in one txn) — deterministic; the EXCLUDE is the loud backstop.
- **Verified live:** a simulated FB→META rename (leave@2022-10-28 + join@2022-10-28, same FIGI) projected to **one continuous interval `[2012-05-18, None)`** (AC #2); KO its own interval; as-of queries correct (2015 → FB-figi only; 2023 → both); idempotent rebuild; no EXCLUDE violation. Temp data cleaned up.
- 189 tests pass (+8 in `test_universe_projection.py`, incl. `invert(project)==log` round-trip + out-of-order determinism), ruff clean.

### File List

- `migrations/deploy|revert|verify/universe_membership.sql` (new) — projection table + EXCLUDE no-overlap.
- `migrations/sqitch.plan` (modified) — added `universe_membership` change.
- `src/sym/universe/projection.py` (new) — `MembershipEvent`/`Interval`, `project_membership`, `rebuild_projection`.
- `tests/test_universe_projection.py` (new, 8 tests) — pure projection cases.
- `_bmad-output/implementation-artifacts/U1-4-membership-projection.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story U1.4: point-in-time `universe_membership` projection (FIGI-level, coalescing renames into one interval) + deterministic `rebuild_projection` from the full ordered log + btree_gist no-overlap EXCLUDE. 189 tests pass, ruff clean; migration deployed + verified; rename-merge + as-of queries + idempotent rebuild verified live. Status → review. |
