# Disaster recovery

sym's durability strategy (AR-14) splits the database along the **source-of-truth /
recomputable** fault line. Only source-of-truth data is backed up; the derived
returns layer is rebuilt deterministically on recovery. This makes backups small
and fast and recovery a *reproducible build* rather than a full snapshot restore.

## What is backed up vs excluded

**Backed up (source of truth):**

- Identity: `securities`, `security_symbology`, `security_names`, `securities_review_queue`
- Classification: `gics_scd`
- Reference: `currency`, `exchange`, `trading_calendar`, `trading_calendar_version`
- Prices & factors: `prices_raw`, `corporate_actions`, `prices_review`
- Operational: `pipeline_backfill_progress`, `pipeline_run_log`

**Excluded:**

- `fact_returns` — **recomputable** (a deterministic function of raw + factors +
  calendar; rebuilt by `sym recompute`, Epic 3). `v_prices_adjusted` is a view (no data).
- The `sqitch` registry schema — the schema is rebuilt by `sqitch deploy` on recovery.

## Backup

```
uv run sym backup                       # -> backups/sym-YYYYMMDD.dump
uv run sym backup --output D:\sym.dump
```

This runs `pg_dump --format=custom --no-owner --exclude-schema=sqitch
--exclude-table=public.fact_returns`. `pg_dump` is located automatically (PATH, a
`PostgreSQL\*\bin` install, or the `SYM_PG_BIN` directory).

## 3-2-1 rule (AC #3)

Keep **3** copies on **2** different media with **1** offsite:

1. The live database (PostgreSQL).
2. A local backup file from `sym backup` (different disk if possible).
3. An **offsite cloud copy, client-side encrypted before upload** — the cloud
   never sees plaintext and the key never lives in the repo or the cloud:

   ```
   # encrypt with age (or gpg) using a key kept OUT of the repo
   age -r <recipient-public-key> -o sym-YYYYMMDD.dump.age backups/sym-YYYYMMDD.dump
   # then upload sym-YYYYMMDD.dump.age to the cloud bucket
   ```

   Decrypt on recovery with the corresponding private key (`age -d ...`).

## Recovery (AC #2)

On a fresh PostgreSQL 18 instance:

```
# 1. (decrypt the cloud copy if used)  age -d -i key.txt sym-YYYYMMDD.dump.age > sym.dump

# 2. migrate — rebuild the schema from version-controlled migrations
sqitch deploy db:pg://postgres@<host>:5432/sym

# 3. restore the source-of-truth DATA onto the migrated schema
pg_restore --data-only --disable-triggers -d "host=<host> dbname=sym user=postgres" sym.dump

# 4. recompute — deterministically rebuild fact_returns (Epic 3)
uv run sym recompute
```

The result is byte-for-byte the same derived data, because `fact_returns` is a pure
function of the restored raw inputs (each row stamped with its `input_hash`). This is
why excluding `fact_returns` from the backup is safe — and why the deterministic
`recompute` command is version-controlled alongside the migrations.

> `sym recompute` defaults to a ONE-YEAR lookback — a full-history rebuild after a
> restore needs an explicit range: `sym recompute --start_date 1990-01-01`. (Index
> returns: `fact_index_returns` is recomputable too but is deliberately kept IN the
> dump — small, conservative.)
