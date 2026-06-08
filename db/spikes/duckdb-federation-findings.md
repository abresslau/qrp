# Findings: DuckDB federation spike (2026-06-08)

Ran `duckdb-federation-spike.md` against the live sym warehouse. **Non-destructive** (scratch
artifacts only, dropped). Verdict: **PASS on what's testable here; one item env-blocked + deferred.**

## Environment block (important)

DuckDB's **`postgres_scanner` extension is unavailable in this env** — `extensions.duckdb.org`
returns **HTTP 503** (same class of restriction as FRED / live-quotes in this simulated-2026
environment). So the **live Postgres-attach** path (`ATTACH ... (TYPE postgres)`, reading straight
from each package's live PG with filter pushdown) **could not be exercised here.**

Adapted to prove the part that is both testable *and* most decision-relevant: DuckDB
cross-**database** `ATTACH` + native 3-part-name joins + `READ_ONLY`, on **real sym data**
materialized into two DuckDB-native databases (sym hub + a separate signal db). That is exactly
the **materialized / heavy-path** federation mode; only live-PG pushdown is deferred.

## Results (real data: sp500, factor `vol_1y`, latest window)

| Check | Result |
|---|---|
| Native cross-**database** 3-part join (`sym.main.* + sig.main.*`) | ✅ 651 rows; **502 carry a z-score from the separate signal DB** |
| Correctness tie-out (signal from separate db vs same data) | ✅ PASS (checksum match) |
| Latency — materialized federation, 50 runs | ✅ **p50 3.6 ms / p95 4.0 ms** (vs the ~1 s NFR-5 budget) |
| `READ_ONLY` boundary (write to a read-only attached db) | ✅ PASS (`INSERT` refused) |
| Live Postgres-attach pushdown / latency | ⛔ ENV-BLOCKED → deferred |

## Interpretation against the decision gates

- **Cross-database join MODEL + Snowflake-style ergonomics + read-only enforcement: PROVEN.**
  DuckDB joins across independent databases with native `catalog.schema.table` names, and a
  read-only attach physically refuses writes. This is the core of the chosen topology — confirmed.
- **Materialized federation path is fast (sub-4 ms): strongly validates the materialization tier**
  as the heavy/hot-path mode (regenerable Parquet/DuckDB snapshots). The "BEND" branch of the
  spike — *materialize heavy paths* — is not just viable, it's trivially performant at this scale.
- **The one open question is the LIVE Postgres-attach path** (read each package's live PG directly,
  pushdown of universe/window filters). It is **unverified** here purely due to the extension block,
  not a design failure. It must be re-run in a network-enabled environment before committing to
  live-attach for any interactive surface.

## Recommendation per read surface (provisional — pending the live-attach re-run)

- **Heavy / full-history (e.g. backtests):** **materialized DuckDB/Parquet snapshots.** Proven fast;
  no dependence on live-attach. Adopt regardless.
- **Interactive filtered (heat map, explorer):** provisionally **live-attach** *if* the deferred
  pushdown test shows filters reach Postgres; **else** a per-EOD-refreshed materialized snapshot
  (also sub-4 ms here). **Decide after the live-attach re-run.**

## Net

The topology direction is **de-risked enough to proceed** with the materialized-federation design.
The cross-DB join model, ergonomics, and read-only guarantee are confirmed on real data; the
materialized path is fast. **Deferred (env-blocked): live Postgres-attach pushdown/latency** — re-run
the original `duckdb-federation-spike.md` (Stages 1–2, `TYPE postgres`) in an environment where
`extensions.duckdb.org` is reachable, then finalize the live-vs-materialized choice per surface.

### Notes for the real implementation
- The spike keyed members off `universe_member_resolution` (all ever-resolved → 651); the real
  heat map should use the **current projection** (`universe_membership` where `valid_to IS NULL`).
- Latency numbers are on materialized (in-DuckDB) data; live-PG-attach numbers are the missing piece.
