# Story V1: Universe-member completeness contract (keystone)

Status: review

## Story

As Andre,
I want every current universe member proven to have full metadata, prices, and fundamentals,
so that a tracked security is never silently incomplete — and if it is, I see exactly what's missing.

## Acceptance Criteria

1. For every current member of any universe, assert metadata (name, symbology, MIC+currency, GICS), prices, and fundamentals.
2. Each incomplete member is persisted to `universe_member_completeness` (per-dimension flags, `missing[]`, severity, reason), refreshed each run.
3. Expected gaps (delisted/suspended, no-calendar MIC) → warn-with-reason; genuine omissions (missing metadata; priceable-but-unloaded) → fail.
4. Pure classifier DB-free tested; live sweep verified on the populated warehouse.

## Tasks / Subtasks

- [x] Task 1: `validation_logs` migration (`universe_member_completeness` + `validation_run_log`); deployed + verified
- [x] Task 2: shared `results.py` (`CheckResult`, pass/warn/fail, `from_items`)
- [x] Task 3: pure `classify_member` (metadata-fail > expected-warn > priceable-fail) + `MemberFlags`
- [x] Task 4: `evaluate_completeness` (presence sweep + durable upsert) + `incomplete_members`/`completeness_summary` for review
- [x] Task 5: DB-free tests (classify + result types) + live verification

## Dev Notes

- "Current member" = a universe_membership interval that is open (`valid_to IS NULL`). Presence is gathered in one query via EXISTS over names/symbology/gics_scd/prices_raw/fundamentals/calendar.
- Classification is pure and ordered: **missing metadata is always fail** (name/symbology come from resolution, GICS from `classify`); if only market data is missing, it's **warn** when delisted/suspended or the MIC has no calendar (no vendor data reachable), else **fail** (priceable but not loaded).
- The log is the durable "what's missing" record the operator asked for; `universe review` surfaces it (V7).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `validate/results.py`: `CheckResult` + `status_for`/`worst` (pass/warn/fail, bounded samples).
- `validate/completeness.py`: `MemberFlags`, pure `classify_member`, `evaluate_completeness` (durable upsert), `incomplete_members`, `completeness_summary`.
- Migration `validation_logs` deployed + verified (both Epic-V tables).
- **Live-verified on sp500:** 503 current members → 502 flagged incomplete (mostly missing `gics` — never classified for index members — and `fundamentals` — not yet loaded), 1 complete. Exactly the intended loose-end surfacing; rows persisted to `universe_member_completeness`.
- 9 DB-free tests; ruff clean.

### File List
- `migrations/deploy|revert|verify/validation_logs.sql` (new); `migrations/sqitch.plan`
- `src/sym/validate/__init__.py`, `results.py`, `completeness.py` (new)
- `tests/test_validate_completeness.py` (new)
- `_bmad-output/implementation-artifacts/V1-completeness-contract.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story V1: universe-member completeness contract (durable per-member log + pure classifier). Live-verified on sp500 (502/503 flagged: missing GICS/fundamentals). |
