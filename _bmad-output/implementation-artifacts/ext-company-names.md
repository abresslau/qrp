# Enhancement: Company names (effective-dated, from OpenFIGI)

Status: review

> Not a planned epics story — a user-requested enhancement (2026-06-06). Adds a
> human-readable company name to the identity layer without weakening the
> FIGI-as-identity model.

## Goal

Store a reliable company name per security, **effective-dated** so a rename
(Facebook→Meta) is a new name row while the CompositeFIGI stays stable — the same
SCD discipline as `gics_scd`. Source is **OpenFIGI** (Bloomberg-sourced,
authoritative, and already returned during `resolve` — currently discarded).

## Acceptance Criteria

1. A `security_names` SCD table exists (composite_figi, name, source, valid_from/valid_to, audit), one name per instant (no-overlap EXCLUDE), FK to securities.
2. `resolve` captures the OpenFIGI `name` and writes it via an idempotent SCD upsert: unchanged → no-op; same-day correction → update in place; a later rename → close the prior row and insert the new one (never a zero-width period).
3. Re-running `resolve` backfills names for the already-resolved universe; a second run is a no-op.

## Tasks / Subtasks

- [x] Task 1: `security_names` migration (SCD shape, EXCLUDE no-overlap, trigger); revert/verify; sqitch.plan
- [x] Task 2: `src/sym/identity/names.py` — `write_name(conn, figi, name, *, source, as_of)` SCD upsert (same-day in-place / cross-day close, like gics); `current_name(conn, figi)` reader
- [x] Task 3: thread the name through resolution — `Resolution.name`, `classify` carries `FigiRecord.name`, `apply_resolutions` writes it; `ResolutionSummary.names_written`; `resolve` CLI summary shows names
- [x] Task 4: tests (`tests/test_names.py` SCD logic; figi test that classify carries the name)

## Dev Notes

- **Why not a flat column:** names drift (FB→Meta), so a flat `securities.name` would need a "which name as of when" SCD anyway. Effective-dated from the start, current-only data today — the same "cheap insurance" rationale as GICS (AR-11).
- **Why OpenFIGI:** authoritative (Bloomberg), complete coverage for everything we resolve, and free here — the name comes back on the same `/mapping` call resolution already makes. (financedatabase has prettier casing but is community/static with coverage gaps.)
- **SCD writer reuses the gics fix:** a same-day correction updates in place (closing would set `valid_to = valid_from`, violating the validity CHECK); a cross-day rename closes then inserts.
- Backfill = re-run `sym resolve` (idempotent); names populate for the existing 45.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `security_names` is SCD-shaped (EXCLUDE no-overlap on `(composite_figi, daterange)`), mirroring `gics_scd`. `write_name` reuses the same-day-in-place / cross-day-close logic (no zero-width periods); idempotent on an unchanged name.
- The name is captured from the OpenFIGI `/mapping` response already made during `resolve` (`FigiRecord.name`) — zero extra API calls — and written inside the per-figi resolution transaction.
- **Verified live:** deployed `security_names`; re-ran `resolve` → `45 assigned (0 new, 45 named)`; 45 current names stored (APPLE INC, TENCENT HOLDINGS LTD, SAMSUNG ELECTRONICS CO LTD, …). 105 tests pass, ruff clean.
- Names are Bloomberg-style uppercase (authoritative). A prettier-casing financedatabase fallback was deliberately deferred. A future rename (e.g. Facebook→Meta) will close the current row and insert a new one — covered by `test_rename_on_a_later_day_closes_then_inserts`.

### File List

- `migrations/deploy|revert|verify/security_names.sql` (new) — effective-dated name SCD.
- `migrations/sqitch.plan` (modified) — `security_names` change.
- `src/sym/identity/names.py` (new) — `write_name` SCD writer + `current_name`.
- `src/sym/identity/figi.py` (modified) — `Resolution.name`, `classify` carries it, `apply_resolutions` writes it, `names_written` count.
- `src/sym/cli.py` (modified) — `resolve` summary shows names.
- `tests/test_names.py` (new, 4 tests) + `tests/test_figi.py` (modified) — SCD + name-carry tests.
- `_bmad-output/implementation-artifacts/ext-company-names.md` (new) — this spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Added effective-dated company names from OpenFIGI: `security_names` SCD, `write_name`, captured during `resolve`. Backfilled 45 names live. 105 tests pass. Status → review. |
