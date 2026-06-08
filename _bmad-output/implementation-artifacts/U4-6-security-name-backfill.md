# Story U4.6: Company-name backfill for universe-sourced securities (fix)

Status: review

## Story

As Andre,
I want every security to carry its company name, not just the original 45 seed names,
so that the ~2,000 index-sourced securities are identifiable.

## Context / Bug

`security_names` held only 45 rows. Two paths create a `securities` row but only one names it:
- **Seed path** (`apply_resolutions`) writes the security *and* `write_name(...)` from OpenFIGI → 45 names.
- **Universe bridge** (`ensure_universe_securities`, U4.1) calls only `write_security`; the membership resolver (`make_openfigi_resolve_fn`) discarded OpenFIGI's `name`, so the ~2,000 index members were created unnamed.

## Acceptance Criteria

1. A backfill fills `security_names` for securities created without a name, sourcing the name from OpenFIGI by current ticker.
2. A name is written only when OpenFIGI resolves the ticker to the **same** CompositeFIGI the security holds (a recycled ticker never mislabels an existing security).
3. Idempotent + resumable; CLI `sym names`; full suite green.

## Tasks / Subtasks

- [x] Task 1: `unnamed_securities` + `backfill_names` (chunked, autocommit, figi-matched) in `identity/figi.py` (AC #1, #2, #3)
- [x] Task 2: CLI `sym names [--limit]` (AC #3)
- [x] Task 3: live backfill run to populate names; full suite green (AC #3)

## Dev Notes

- Reuses `plan_resolutions` + `write_name`; a name is written only on `ASSIGNED` with `composite_figi == the security's figi`, so a recycled/reused ticker that now resolves elsewhere is skipped (`skipped_mismatch`), never mislabeling. Ambiguous/no-match → `skipped_unresolved` (stays unnamed, retained).
- Idempotent + resumable (chunked, autocommit, only-unnamed selection): re-running fills names any later population adds, so `sym names` is the standard post-population step alongside `sym backfill`/`recompute`.
- Forward note: capturing the name at universe-resolution time would need a name column on `universe_member_resolution`; the figi-matched backfill avoids a schema change and handles both existing and future unnamed securities.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `identity/figi.py`: `NameBackfillSummary`, `unnamed_securities`, `backfill_names` (figi-matched, chunked, resumable).
- `cli.py`: `sym names [--limit]`.
- 279 tests pass; ruff clean. Live name backfill run to populate the ~2,000 unnamed index securities.

### File List
- `src/sym/identity/figi.py` (name backfill)
- `src/sym/cli.py` (`names` command)
- `_bmad-output/implementation-artifacts/U4-6-security-name-backfill.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Fixed missing company names for universe-sourced securities: figi-matched OpenFIGI name backfill + `sym names` CLI. Surfaced by the 45-names observation. |
