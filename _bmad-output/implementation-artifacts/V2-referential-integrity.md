# Story V2: Referential-integrity invariants (no orphans)

Status: review

## Story

As the operator,
I want the FK-less seams between layers continuously asserted,
so that an orphaned resolution/membership/price can never accumulate unseen.

## Acceptance Criteria

1. Every `composite_figi` in resolutions/membership/symbology/names/gics/prices/corp-actions/fundamentals/fact_returns exists in `securities`.
2. A resolved universe member with no securities row is a failure (bridge gap).
3. Pure set-diff DB-free tested; live sweep verified.

## Tasks / Subtasks

- [x] Task 1: pure `find_orphans(child, securities)` set-diff
- [x] Task 2: `check_referential_integrity` — anti-join per seam (9 seams) → `CheckResult`
- [x] Task 3: DB-free tests + live verification

## Dev Notes

- Nine seams checked via `NOT EXISTS securities` anti-joins; the resolution seam filters `resolution_status='resolved'` (an unresolved member legitimately has no securities row). Any orphan is a fail.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/integrity.py`: pure `find_orphans` + `check_referential_integrity` (9-seam anti-join sweep).
- **Live-verified:** `pass` — 0 orphaned `composite_figi` across all 9 seams.
- 4 DB-free tests; ruff clean.

### File List
- `src/sym/validate/integrity.py` (new)
- `tests/test_validate_integrity.py` (new)
- `_bmad-output/implementation-artifacts/V2-referential-integrity.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V2: referential-integrity no-orphan sweep across 9 FK-less seams. Live: 0 orphans. 4 DB-free tests. |
