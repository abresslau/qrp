# Spike: DuckDB federation over independent Postgres databases

**Status:** proposed (first step of the DB-topology migration — see
`sym/_bmad-output/planning-artifacts/sprint-change-proposal-2026-06-08.md`).
**Owner:** Andre · **Box:** ~half a day · **Destructive?** No — scratch DB only, `READ_ONLY`
attach to the live sym DB, scratch dropped at the end.

## Hypothesis to prove / kill

> DuckDB, embedded in the API, can `ATTACH READ_ONLY` to two independent Postgres databases and
> serve the real heat-map cross-package join with (a) native `catalog.schema.table` ergonomics,
> (b) interactive latency (target p95 < ~1 s, NFR-5) for a typical universe, and (c) filter
> pushdown so it doesn't drag whole tables — while physically refusing writes to sym.

If true → carve packages into their own DBs for real. If latency only fails on *heavy/full-history*
queries → that's the signal the **materialization tier** (Parquet snapshots) is needed for those,
not a kill. If pushdown is broken (pulls whole tables even when filtered) → reconsider FDW or
materialize-first.

## The representative query

The actual heat map (today, all in sym) joins `universe_member_resolution` → `securities` →
`fundamentals.market_cap_usd` → `fact_returns.pr` (by `window_id`) → `gics_scd.sector_name`, keyed
on `composite_figi`. The cross-package test is **that query + a `signal.score` leg that lives in a
separate database** (the thing the target topology must serve):

```sql
-- DuckDB session, two attached Postgres DBs: sym (hub) + sig (a carved-out signal DB)
SELECT  r.composite_figi,
        f.market_cap_usd,
        ret.pr            AS window_return,
        g.sector_name,
        sc.zscore         AS momentum_z          -- <- from a DIFFERENT database
FROM    sym.public.universe_member_resolution r
JOIN    sym.public.securities  s   ON s.composite_figi = r.composite_figi
LEFT JOIN sym.public.fundamentals  f  ON f.composite_figi = r.composite_figi
LEFT JOIN sym.public.gics_scd      g  ON g.composite_figi = r.composite_figi
LEFT JOIN sym.public.fact_returns  ret ON ret.composite_figi = r.composite_figi
                                      AND ret.window_id = ?           -- e.g. YTD's window_id
LEFT JOIN sig.signal.score         sc  ON sc.composite_figi = r.composite_figi
                                      AND sc.universe_id = r.universe_id
                                      AND sc.factor_key = 'mom_12_1'
WHERE   r.universe_id = 'sp500';
```

> Note: the production query uses per-figi `LATERAL` subqueries (latest-row picks). **Test both
> forms** — correlated `LATERAL` against the postgres scanner may degrade to per-row roundtrips;
> the flattened `LEFT JOIN` form above lets DuckDB pull columns once and hash-join locally. Which
> form the federation prefers is itself a finding.

## Setup (Python `duckdb` — mirrors how the API would embed it)

```bash
# scratch venv (don't touch the API's env)
uv venv .spike && .spike\Scripts\activate && uv pip install duckdb psycopg[binary]
```

```python
import duckdb, psycopg, os
DSN = "host=localhost port=5432 user=postgres password=%s" % os.environ["SYM_DB_PASSWORD"]

# 1. scratch DB simulating "signal is its own database"
adm = psycopg.connect(DSN + " dbname=sym", autocommit=True)
adm.execute("DROP DATABASE IF EXISTS signal_spike"); adm.execute("CREATE DATABASE signal_spike")

con = duckdb.connect()
con.execute("INSTALL postgres; LOAD postgres;")
# copy signal.score into the scratch DB via DuckDB (no pg_dump needed)
con.execute(f"ATTACH '{DSN} dbname=sym'          AS symw (TYPE postgres);")          # rw, setup only
con.execute(f"ATTACH '{DSN} dbname=signal_spike' AS sig  (TYPE postgres);")
con.execute("CREATE SCHEMA IF NOT EXISTS sig.signal;")
con.execute("CREATE TABLE sig.signal.score AS SELECT * FROM symw.signal.score;")
con.execute("DETACH symw;")

# 2. the real test: BOTH attached READ_ONLY
con.execute(f"ATTACH '{DSN} dbname=sym' AS sym (TYPE postgres, READ_ONLY);")
# sig re-attach read_only
con.execute("DETACH sig;"); con.execute(f"ATTACH '{DSN} dbname=signal_spike' AS sig (TYPE postgres, READ_ONLY);")
```

## What to run & measure

1. **Ergonomics** — the cross-DB query above returns rows; native 3-part names work. ✅/❌
2. **Correctness** — tie the federated result to the same join run directly in Postgres
   (psycopg) for `sp500`: row count + a checksum of `(figi, market_cap_usd, window_return)` match.
3. **Latency** — `timeit` 20 runs, report p50/p95, for `sp500` (~500) and `ibov` (~78), each in:
   (a) DuckDB-federated (flattened JOIN), (b) DuckDB-federated (LATERAL form), (c) the current
   single-DB psycopg query as the baseline. Cold vs warm.
4. **Pushdown** — `EXPLAIN` the federated query; confirm the `universe_id`/`window_id` filters
   reach the Postgres scan (not "pull whole `fact_returns`"). Sanity: rows fetched ≈ universe size,
   not table size.
5. **READ_ONLY boundary** — `con.execute("UPDATE sym.public.fundamentals SET market_cap_usd=0")`
   must **fail**. ✅/❌ (this is the physical read-only-role guarantee.)

## Decision gates

| Outcome | Meaning → action |
|---|---|
| Ergonomics ✅ + p95 < ~1 s + pushdown ✅ + RO blocks writes | **PASS** → carve packages into own DBs; DuckDB is the federation layer. |
| Works but heavy/full-history queries blow the budget | **BEND (expected)** → live-attach for filtered/interactive (heatmap/explorer); **materialize Parquet snapshots** for heavy paths. Record which query classes. |
| Pushdown broken (whole-table pulls) or LATERAL unusable | **RETHINK** → flatten the query, or fall back to FDW / materialize-first. |

## Deliverable

`db/spikes/duckdb-federation-findings.md` — the table of p50/p95 per form, the pushdown verdict,
the RO check, and a one-line recommendation **per QRP read surface** (live-attach vs materialized).
Then: `DROP DATABASE signal_spike;` and delete `.spike/`.

## Reproduction (committed runners)

Both read `SYM_DB_PASSWORD` from the env (no secrets in the scripts):

```bash
# the live Postgres-attach test (needs the DuckDB postgres extension / network):
SYM_DB_PASSWORD=... uv run --with duckdb --with "psycopg[binary]" python db/spikes/run_spike_live.py
# the env-adapted runner that produced the 2026-06-08 findings (no extension needed):
SYM_DB_PASSWORD=... uv run --with duckdb --with "psycopg[binary]" python db/spikes/run_spike_native.py
```

`run_spike_live.py` exits 3 with a clear message if `extensions.duckdb.org` is unreachable (the
2026-06-08 case) — then fall back to `run_spike_native.py`. Results → `duckdb-federation-findings.md`.

## Out of scope (follow-ons, not this spike)
- Where DuckDB runs in production (embedded in the API process vs a small query service) +
  concurrency model — decide after perf is known.
- The materialization refresh job + cadence.
- Carving real packages / meta-orchestration (the migration proper).
