# Story V6: Universe → returns research-readiness gate

Status: review

## Story

As Andre,
I want a gate that a universe is actually usable for research,
so that a partially-loaded universe can't masquerade as ready.

## Acceptance Criteria

1. Per universe, % of current members joining `fact_returns` ≥ threshold, else fail with missing itemized.
2. Missing distinguished by reason (unpriced / no calendar / priced-but-recompute-stale).
3. Pure coverage math DB-free tested; live-verified.

## Tasks / Subtasks

- [x] Task 1: pure `coverage_pct` + `_missing_reason`
- [x] Task 2: `check_universe_readiness(threshold=0.90)` per-universe gate with classified missing
- [x] Task 3: DB-free tests + live verification

## Dev Notes

- `universe_membership` is resolved-only, so "current members" = open intervals; covered = those joining `fact_returns`. Default gate 90% (configurable).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/readiness.py`: pure `coverage_pct` + `_missing_reason`; `check_universe_readiness` per-universe gate.
- **Live-verified: `pass`** — all 12 universes ≥ 90% of current members join `fact_returns`.
- 2 DB-free tests; ruff clean.

### File List
- `src/sym/validate/readiness.py` (new)
- `tests/test_validate_readiness.py` (new)
- `_bmad-output/implementation-artifacts/V6-readiness-gate.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V6: universe→returns readiness gate (classified missing). Live: 12/12 universes pass at 90%. 2 DB-free tests. |
