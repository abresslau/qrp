# Story V3: Symbology & name completeness/uniqueness

Status: review

## Story

As the operator,
I want identity columns proven complete and unambiguous,
so that resolution, naming, and the SM-6 harness can't be silently shadowed.

## Acceptance Criteria

1. Every active security has ≥1 current ticker symbology + exactly one current name.
2. No current `(symbol_type, symbol_value, mic)` maps to >1 composite_figi; cross-exchange same-ticker is NOT a collision.
3. DB-free tests on pure detectors; live-verified.

## Tasks / Subtasks

- [x] Task 1: pure `find_missing` + `find_collisions` (MIC-keyed, so cross-exchange tickers don't collide)
- [x] Task 2: `check_identity_completeness` (active needs current ticker + exactly one current name) + `check_ticker_collisions`
- [x] Task 3: DB-free tests (incl. the LVMH/Moelis cross-exchange case) + live verification

## Dev Notes

- The collision key includes MIC, so `MC@XPAR` (LVMH) vs `MC@XNYS` (Moelis) coexist — only the *same* key mapping to two FIGIs is a collision (the bug the SM-6 harness hit).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/symbology.py`: pure `find_missing`/`find_collisions`; `check_identity_completeness`, `check_ticker_collisions`.
- **Live-verified:** both `pass` — 2047 active securities all have current ticker + single current name; 0 true collisions across 2092 current symbology rows.
- 5 DB-free tests (incl. cross-exchange MC, ISIN collision); ruff clean.

### File List
- `src/sym/validate/symbology.py` (new)
- `tests/test_validate_symbology.py` (new)
- `_bmad-output/implementation-artifacts/V3-symbology-uniqueness.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V3: symbology/name completeness + MIC-keyed uniqueness. Live: both pass. 5 DB-free tests. |
