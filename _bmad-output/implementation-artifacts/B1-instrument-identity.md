# Story B1: Universal internal instrument identity (sym_id)

Status: review

## Story

As the warehouse,
I want a stable internal `sym_id` spanning all instrument kinds with vendor ids as cross-references,
so that indexes (and future instrument types) have durable identity even when CompositeFIGI/Yahoo/MSCI don't all apply.

## Acceptance Criteria

1. `instrument` (sym_id PK, kind, name, currency, status) + `instrument_xref` (sym_id, source, value; UNIQUE(source,value)).
2. Additive: existing equity tables keep composite_figi; each security maps 1:1 to an instrument via a `composite_figi` xref.
3. `ensure_instrument` is find-or-create by xref (idempotent); `sym_id_for`/`xref_for`/`add_xref` resolve both ways.
4. DB-free tests + live equity backfill.

## Tasks / Subtasks

- [x] Task 1: `instrument` migration (instrument + instrument_xref; deployed + verified)
- [x] Task 2: `identity/instrument.py` — `ensure_instrument`, `sym_id_for`, `xref_for`, `add_xref`, `backfill_equity_instruments`
- [x] Task 3: DB-free tests (idempotent find-or-create) + live backfill

## Dev Notes

- `sym_id` = BIGINT identity (collision-free, never reused). `UNIQUE(source, value)` guarantees a vendor id maps to exactly one instrument. Additive over composite_figi (non-destructive; FK-broadening is a future option).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `instrument` migration deployed + verified.
- `identity/instrument.py`: find-or-create `ensure_instrument`, resolvers, `backfill_equity_instruments`.
- **Live:** backfilled **2,047 equity instruments** (one per security), 2,047 composite_figi xrefs; Apple composite_figi → sym_id 4.
- 3 DB-free tests; ruff clean.

### File List
- `migrations/deploy|revert|verify/instrument.sql` (new); `migrations/sqitch.plan`
- `src/sym/identity/instrument.py` (new)
- `tests/test_instrument.py` (new)
- `_bmad-output/implementation-artifacts/B1-instrument-identity.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story B1: universal sym_id instrument identity + xref, additive equity backfill (2,047 mapped). 3 DB-free tests. |
