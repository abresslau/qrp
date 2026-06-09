# lineage — QRP data lineage (Dagster)

A Dagster **code location** that models QRP's data DAG as software-defined assets, giving
**table-level lineage + documentation** across the QRP packages' databases. It adds a lineage/catalog
surface without changing any other package: sym still owns its tables, the other packages keep
their API/engine entrypoints. Dagster just describes — and optionally runs — the graph.

Chosen over Prefect/Airflow after a research-backed evaluation (see the brainstorming session
`_bmad-output/brainstorming/brainstorming-session-2026-06-08-230821.md` and the three
deep-research passes): Dagster delivers the asset catalog, automatic lineage graph, and an
agent-queryable GraphQL API **all in the free Apache-2.0 OSS tier**, runs natively on Windows,
and reuses QRP's existing Postgres.

## What's modeled

Every table across the platform is an asset, grouped by owning package
(`sym`, `macro`, `signals`, `backtest`, `optimiser`, `portfolios`, `altdata`, `analytics`,
`operate`). **31 nodes, 32 edges**, traced from the real codebase — no fabricated dependencies.
Each node documents its owning `database`, `table`, what `produced_by` it, and the external
`source`.

Two kinds of node (`src/lineage/assets.py`):

- **Runnable sym assets** — sym tables with a clean CLI command (`prices_raw`, `fact_returns`,
  `fx_rate`, `fundamentals`, `universe_membership`, ...). Materializing one runs the **exact same
  `sym` CLI** an operator would type (`src/lineage/sym_run.py`), so loads stay runnable by hand if
  Dagster is down.
- **External assets** — tables produced outside Dagster (API/engine-driven packages, config/manual
  inputs, code-backfilled sym tables, the `analytics` computed metrics). They appear in the lineage
  graph with full edges + docs, but Dagster does not execute them.

## Run it

```powershell
# from the repo root
$env:DAGSTER_HOME = "C:/Projects/qrp/.dagster_home"
uv run dagster dev -m lineage.definitions -h 127.0.0.1 -p 3333
```

Then open **http://127.0.0.1:3333** → **Assets → View global asset lineage** for the graph.

- **Instance store:** the `dagster` Postgres DB on the shared instance (config in
  `.dagster_home/dagster.yaml`), reusing the `PG*` env. No SQLite, so no "database is locked"
  contention.
- **Executor:** in-process (`definitions.py`) — robust on Windows (avoids the spawn/fork path).

## GraphQL (the agent surface)

The OSS webserver serves GraphQL at `http://127.0.0.1:3333/graphql`. Example — list every asset
and its upstream deps:

```graphql
query { assetNodes { assetKey { path } groupName dependencyKeys { path } } }
```

## Columns + field lineage

Every asset (30/31 — all but the computed `analytics/metrics`) carries its **real column schema**
(`dagster/column_schema`, pulled from the Sqitch migrations), so join keys like `composite_figi`
and `sym_id` are **visible on each asset** in the UI and queryable via GraphQL. Derived assets
also carry **`dagster/column_lineage`** describing field-level edges for the join keys and key
measures (e.g. `fact_returns.composite_figi ← prices_raw.composite_figi`, `fact_returns.pr ←
prices_raw.close`, `fact_index_returns.sym_id ← index_levels.sym_id`).

**Key-space note:** `composite_figi` (equity chain: securities → prices → returns → signals /
optimiser / portfolios / altdata) and `sym_id` (instrument chain: instrument → index_levels →
fact_index_returns) are **disjoint** — no table bridges them — so they trace through separate
sub-graphs.

### Seeing the field flow (free / OSS)

Column lineage lives as **`dagster/column_lineage` metadata on the real table assets** (the
idiomatic Dagster pattern — one asset per table). In OSS this is **visible per-asset and
queryable via GraphQL**, but Dagster does not render the interactive cross-asset *column* graph
(that view is Dagster+ only, which we deliberately do not use).

> An earlier experiment that promoted join keys to standalone "column assets" (`key_lineage.py`,
> groups `key_composite_figi` / `key_sym_id`) was **removed** — it conflated grains (a column is
> not a materializable data object) and was not idiomatic Dagster. For a single-picture field-flow
> view, generate a standalone Mermaid/Graphviz diagram from the lineage data instead of polluting
> the asset graph.

## OSS vs Dagster+ (what's free here)

Free in this OSS setup: assets, **automatic table-level lineage graph**, asset catalog,
**per-asset column schema**, **emitted column lineage** (stored + GraphQL-queryable), the web UI,
and the GraphQL API. **Paywalled (Dagster+, not used here):** the search-first Catalog Pro
experience and the **interactive cross-asset column-lineage graph** (click a field, watch it flow
table-to-table) + column-aware catalog search. So the column data is all here in OSS; only the
*visual field-flow graph* is the paid piece.

## Notes / follow-ups

- Windows: `dagster dev` logs a benign warning that compute-log capture is disabled
  (`PYTHONLEGACYWINDOWSSTDIO`) — does not affect lineage.
- Not yet wired into the QRP console/`platform.toml` (it's a standalone Dagster UI for now).
- The runnable sym assets intentionally use light commands (e.g. `delta`, `fx delta`); heavier
  modes (`backfill`) are available via the same `sym` CLI.
