# Story 2.9: Durability and disaster recovery

Status: review

## Story

As a maintainer,
I want a backup/restore procedure that excludes recomputable data,
so that recovery is a deterministic rebuild rather than a full snapshot restore.

## Acceptance Criteria

1. **Given** `pg_dump`, **Then** it captures raw OHLCV + factors + identity + calendar and `--exclude-table` the recomputable `fact_returns`.
2. **Given** a recovery on a fresh PostgreSQL instance, **When** run, **Then** the sequence migrate → restore raw+factors+identity+calendar → `uv run sym recompute` reproduces `fact_returns` deterministically.
3. **Given** the 3-2-1 rule, **Then** a client-side-encrypted cloud copy is part of the documented procedure.

## Tasks / Subtasks

- [x] Task 1: backup tooling in `src/sym/dr.py` (AC: #1)
  - [x] `RECOMPUTABLE_TABLES = ('fact_returns',)`; `backup_args(output)` — custom-format, `--no-owner`, `--exclude-schema=sqitch`, `--exclude-table=public.fact_returns`
  - [x] `find_pg_dump()` (SYM_PG_BIN / PATH / PostgreSQL install dir) + `run_backup(conninfo, output)`
- [x] Task 2: `sym backup [--output]` CLI (AC: #1); `backups/` + `*.dump` gitignored
- [x] Task 3: DR runbook `docs/disaster-recovery.md` (AC: #2, #3)
  - [x] what's backed up vs excluded; the migrate → restore → recompute recovery sequence; 3-2-1 + client-side-encrypted cloud copy (age/gpg)
- [x] Task 4: tests in `tests/test_dr.py` (4 tests) — `backup_args` excludes `fact_returns`/`sqitch`, custom format, writes to output; `find_pg_dump` honours SYM_PG_BIN

## Dev Notes

- **Recomputable-excluded backup (AC #1):** `fact_returns` is a deterministic function of raw + factors + calendar (Epic 3, AR-7), so it's excluded — recovery rebuilds it, trading a minutes-long recompute for a much smaller, faster backup. The `--exclude-table` is future-proof: `fact_returns` doesn't exist until Epic 3, so it's a no-op today but correct the moment it lands.
- **Schema from migrations, data from dump:** the `sqitch` registry schema is excluded; on recovery, `sqitch deploy` rebuilds the schema, then the dump restores source data, then `sym recompute` rebuilds `fact_returns`. So the backup is the *source-of-truth data* (identity, names, classification, reference, calendar, raw prices, factors, review, progress, run log).
- **`recompute` is Epic 3** — this story delivers the backup + runbook; the deterministic rebuild step is documented and lands with the returns engine. That recomputability is exactly what makes excluding `fact_returns` safe (AR-14).
- **pg_dump location:** native PG client (`C:\Program Files\PostgreSQL\18\bin\pg_dump.exe`), not on PATH — `find_pg_dump` resolves it (overridable via `SYM_PG_BIN`).
- **3-2-1 + encryption (AC #3):** runbook prescribes 3 copies / 2 media / 1 offsite, with the offsite cloud copy **client-side encrypted** (e.g. `age`/`gpg`) before upload — the key never in the repo or the cloud.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.9: Durability and disaster recovery]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-14 — Durability/DR]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- Backup is a custom-format `pg_dump` of source-of-truth data, excluding the recomputable `fact_returns` (future-proof: no-op until Epic 3) and the `sqitch` registry (schema rebuilt by migrate).
- `find_pg_dump` resolves the native PG client (here `C:\Program Files\PostgreSQL\18\bin\pg_dump.exe`), overridable via `SYM_PG_BIN`.
- Runbook documents the full AR-14 recovery (migrate → `pg_restore --data-only` → `sym recompute`) and 3-2-1 with a client-side-encrypted (age/gpg) offsite copy. `recompute` lands in Epic 3.
- **Verified live:** `sym backup` → `backups/sym-20260606.dump` (9.1 MB); `pg_restore -l` shows all source tables (prices_raw, corporate_actions, securities, security_names, trading_calendar, gics_scd, prices_review, pipeline_run_log) and **no `sqitch` schema**. 117 tests pass, ruff clean.

### File List

- `src/sym/dr.py` (new) — `backup_args`, `find_pg_dump`, `run_backup`, `RECOMPUTABLE_TABLES`.
- `src/sym/cli.py` (modified) — `sym backup [--output]`.
- `docs/disaster-recovery.md` (new) — DR runbook (backup, 3-2-1, encryption, recovery).
- `tests/test_dr.py` (new, 4 tests).
- `.gitignore` (modified) — ignore `backups/`, `*.dump`, `*.dump.age`.
- `_bmad-output/implementation-artifacts/2-9-disaster-recovery.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.9: `sym backup` (source-of-truth pg_dump excluding recomputable `fact_returns` + `sqitch`), DR runbook (migrate→restore→recompute, 3-2-1 + client-side encryption). 4 tests; verified live (9.1 MB dump, correct contents). Status → review. |
