# Story QL.1: Lineage — Dagster foundation + auto-feeder

Status: in-progress

<!-- Brownfield capture: the foundation (Dagster lineage layer) was built ad-hoc in Claude Code
and is being formalized here. ACs/tasks are split into BUILT (satisfied) and REMAINING (open).
Validation optional: run validate-create-story before dev-story. -->

## Story

As the **QRP owner-operator**,
I want **every data load's lineage (what feeds what, across packages) captured and documented in a free, self-hosted tool**,
so that **I can trace any table back to its sources, hand it to a future monitoring agent, and not maintain the lineage by hand**.

## Context

QRP loads data through per-package Python loaders (psycopg) invoked via CLIs. There was no
lineage/catalog surface. After a brainstorm + 4 deep-research passes (see References), **Dagster
(free OSS, Apache-2.0)** was chosen as the lineage + catalog + GraphQL agent surface + eventual
orchestrator — over Airflow (Windows-unsupported, heavy) and Prefect (lineage UI is Cloud-only).
**Dagster+ is explicitly excluded** to keep the platform self-hosted with no subscription.

Foreign keys give only the *referential* graph (master tables) and never cross databases;
Dagster OSS auto-discovers nothing (renders declared deps only). The chosen automatic path is
**static SQL parsing (sqlglot) of the SQL the loaders already issue + Postgres `information_schema`
for schema** — a prototype is proven (see AC-7..9).

## Acceptance Criteria

### Built (satisfied)
1. **Dagster code location exists and runs free/OSS.** Given `packages/lineage` installed, when `uv run dagster dev -m lineage.definitions -p 3333` runs on Windows, then the UI serves (HTTP 200) and the daemon starts, with the instance store on the `dagster` Postgres DB (no SQLite lock issues) and the in-process executor.
2. **The full data DAG is modeled, idiomatically.** Given the code location loads, then there are **31 asset nodes (30 real tables + 1 computed `analytics/metrics`)** — one per real table, no column-as-asset hacks — grouped by owning package, with **no fabricated edges** (every dep traced from code).
3. **Runnable sym assets are decoupled.** Given a sym asset is materialized, when it runs, then it shells out to the identical `sym` CLI an operator would type (`sym_run.py`), so loads remain runnable by hand if Dagster is down.
4. **Column schema + lineage are attached.** Given any of the 30 table assets, then it carries `dagster/column_schema` (real columns from migrations) so `composite_figi`/`sym_id` are visible per-asset and GraphQL-queryable; derived assets carry `dagster/column_lineage` for join keys + key measures.
5. **GraphQL answers the asset/lineage graph.** Given the server is up, when `assetNodes { assetKey dependencyKeys metadataEntries }` is queried, then it returns the 31 nodes with correct cross-package edges (e.g. `signals.score ← sym.fact_returns`).
6. **The forced key-as-asset experiment is removed.** Given the final code, then `key_lineage.py` and the `key_composite_figi`/`key_sym_id` groups do not exist (non-idiomatic; removed).

### Built — prototype proven (auto-feeder)
7. **SQL capture works with zero loader changes.** Given `CapturingConnection` wraps a psycopg connection (`sql_capture.py`), when a loader runs, then every `execute`/`executemany` statement is recorded pass-through.
8. **Lineage is auto-derived from captured SQL.** Given captured statements + Postgres schema (`derive.pg_schema` from `information_schema`), when `derive.derive_edges` runs, then it produces table-level + cross-DB edges classified by basis (`sql` vs `run-correlation`), with `composite_figi`/`sym_id` flagged as pass-through keys.
9. **Proven on real code.** Given the real optimiser read functions are run through `CapturingConnection`, then `optimiser.weight ← {fact_returns, fundamentals, security_symbology, universe_membership}` is derived automatically (incl. inputs the hand-model missed), with `composite_figi` traced.

### Remaining (open)
10. **Auto-feeder wired into Dagster.** Given `derive.to_dagster_metadata`, when the lineage assets are built, then the table-level deps + key column lineage are **generated from captured/parsed SQL** rather than hand-declared, for at least the cross-package edges.
11. **sqlglot is a declared dependency.** Given `packages/lineage/pyproject.toml`, then `sqlglot` is listed (not just `uv run --with`), and `uv sync --all-packages` succeeds.
12. **FK referential layer is auto-derived.** Given Postgres FK introspection (filtered for the Sqitch registry tables), then intra-DB referential edges are generated automatically and merged with the SQL-derived derivation edges.
13. **Free field-flow visual.** Given the lineage data, then a standalone Mermaid/Graphviz field-flow diagram for `composite_figi`/`sym_id` is generated (outside the asset graph), since the interactive column-lineage view is Dagster+ only.

### Out of scope / explicit non-goals
- Column-level lineage of **computed measures** (weight, zscore, sharpe, pr) — not recoverable from SQL (values are numpy); table-level + key columns only.
- Dagster+ (any paid/cloud feature). Console/`platform.toml` integration and Dagster schedules are deferred to later QL stories.

## Tasks / Subtasks

- [x] Scaffold `packages/lineage` Dagster code location; add to uv workspace (AC: 1)
- [x] Model 31 table assets with deps from verified code trace (AC: 2)
- [x] Runnable sym assets via `sym_run.py` subprocess (AC: 3)
- [x] Attach `dagster/column_schema` + `dagster/column_lineage` (AC: 4)
- [x] Postgres instance store + in-process executor; verify UI + GraphQL (AC: 1, 5)
- [x] Remove `key_lineage.py` / key_* groups (AC: 6)
- [x] `sql_capture.py` CapturingConnection (AC: 7)
- [x] `derive.py` classify + correlate + `pg_schema` + `to_dagster_metadata` (AC: 8)
- [x] Prove on real optimiser code (AC: 9)
- [ ] Wire `derive` output into Dagster asset metadata, replacing hand-declared deps (AC: 10)
- [x] Add `sqlglot` to `pyproject.toml`; `uv sync --all-packages` (AC: 11)
- [ ] FK introspection module (filter Sqitch tables) → referential edges (AC: 12)
- [ ] Generate Mermaid field-flow diagram for composite_figi/sym_id (AC: 13)

### Review Findings

_Code review 2026-06-09 (Blind Hunter + Edge Case Hunter + Acceptance Auditor). 8 patch, 11 deferred, 5 dismissed._

**Patch (shipped defects — fix now):**
- [x] [Review][Patch] `fundamentals` schema stale vs migrations: `as_of`→`as_of_date`, `market_cap`→`market_cap_lcy`, missing `market_cap_usd` [assets.py:127-131] (AC4)
- [x] [Review][Patch] `fact_returns.asof` renamed to `as_of_date` (date_naming_convention.sql) [assets.py:110] (AC4)
- [x] [Review][Patch] `index_levels`/`fact_index_returns` `variant` column dropped (index_levels_drop_variant.sql) but still declared as PK [assets.py:106,114-115] (AC4)
- [x] [Review][Patch] `trading_calendar_version` `first_session`/`last_session`→`first_session_date`/`last_session_date` [assets.py:91] (AC4)
- [x] [Review][Patch] `optimiser/weight` deps missing `fundamentals` + `security_symbology` (real engine reads both) [assets.py:459-463] (AC2/AC9)
- [x] [Review][Patch] `altdata/wiki_map` upstream is `security_symbology` (ticker lookup), not `securities` [assets.py:472,265-266] (AC2)
- [x] [Review][Patch] add `sqlglot` to pyproject deps (derive.py crashes on import without it) [pyproject.toml] (AC11)
- [x] [Review][Patch] AC2 wording: 31 nodes = 30 tables + 1 computed (`analytics/metrics`), not "31 table assets" [this story] (AC2)

**Deferred (auto-feeder hardening → AC10 rollout; + future topology):**
- [x] [Review][Defer] derive_edges: run-correlation is cartesian / no per-run + order scoping → false edges to metadata targets [derive.py:116-124] — deferred to AC10
- [x] [Review][Defer] multi-connection captures never combine (read conn vs write conn have separate sinks) → zero edges unless merged per run [sql_capture.py] — deferred to AC10
- [x] [Review][Defer] CTE aliases mis-read as source tables (`shares`,`px`,`latest`) → phantom upstreams [derive.py:82] — deferred to AC10
- [x] [Review][Defer] pg_schema never wired into classify (schema= not passed) → `SELECT *`/unqualified keys dropped [derive.py:53] — deferred to AC10
- [x] [Review][Defer] `%s`→NULL blind replace corrupts string literals / named `%(name)s` placeholders [derive.py:45-47] — deferred to AC10
- [x] [Review][Defer] UPDATE/DELETE/MERGE unclassified; CTAS misclassified as read [derive.py:59-85] — deferred to AC10
- [x] [Review][Defer] to_dagster_metadata bare-name target collisions (run/weight/score/point across packages) [derive.py:141] — deferred to AC10
- [x] [Review][Defer] dedup ignores `keys` → non-deterministic key list on duplicate pairs [derive.py:127-131] — deferred to AC10
- [x] [Review][Defer] INSERT…SELECT computed-key passthrough dropped (key not in source_cols) [derive.py:110] — deferred to AC10
- [x] [Review][Defer] sql_capture runtime semantics: rolled-back statements retained, non-autocommit attr sets, row/cursor factories, named cursors, COPY, empty-executemany phantom write [sql_capture.py] — deferred to AC10
- [x] [Review][Defer] pg_schema collapses same table name across schemas (matters under DuckDB federation) [derive.py:39-41] — deferred (future topology)

## Dev Notes

### Architecture & constraints
- **Free OSS Dagster only** (Apache-2.0). No Dagster+, no cloud control plane. Verified column schema/lineage/GraphQL/UI are all in the free tier; the interactive *column* graph + Catalog-Pro search are the only Dagster+ features and are intentionally forgone.
- **Idiomatic: one asset per real table.** Do NOT model columns as assets (the removed `key_*` hack). Column lineage = metadata on table assets.
- **Lineage truth split:** FKs = referential (master tables, intra-DB only, never cross-DB); sqlglot-on-captured-SQL = derivation + cross-DB; Python-compute measures = not column-traceable. `composite_figi` (equity chain) and `sym_id` (instrument/index chain) are **disjoint** key-spaces (no bridge table).
- **DB topology:** Postgres-per-package on the shared instance (PG* env). Dagster instance store = the `dagster` DB. `derive.pg_schema` reads `information_schema`.

### Source tree (this story)
- `packages/lineage/src/lineage/assets.py` — 31 table assets + schema + column lineage
- `packages/lineage/src/lineage/definitions.py` — `Definitions` (in-process executor)
- `packages/lineage/src/lineage/sym_run.py` — runs `sym` CLI from an asset
- `packages/lineage/src/lineage/sql_capture.py` — CapturingConnection (auto-feeder)
- `packages/lineage/src/lineage/derive.py` — sqlglot derivation + `to_dagster_metadata`
- `packages/lineage/README.md` — run instructions, OSS limits
- `.dagster_home/dagster.yaml` — Postgres instance store (gitignored)
- `packages/lineage/pyproject.toml` — deps (dagster 1.13.8, dagster-webserver, dagster-postgres 0.29.8; sqlglot pending)

### How to run / verify
- `$env:DAGSTER_HOME="C:/Projects/qrp/.dagster_home"; uv run dagster dev -m lineage.definitions -h 127.0.0.1 -p 3333` → http://127.0.0.1:3333
- `uv run dagster definitions validate -m lineage.definitions` (asset graph integrity)
- GraphQL at `/graphql` — query `assetNodes`
- Auto-feeder prototype: `uv run --with sqlglot python` exercising `lineage.derive` on captured statements

### Testing standards
- Validate definitions load (no broken deps) as the primary gate.
- For `derive.py`: unit-test `classify`/`derive_edges` on representative SQL (INSERT…SELECT, INSERT…VALUES, cross-DB read) — assert edge `basis` + key flags. (No live DB needed; sqlglot is static.)

### Project Structure Notes
- New package `packages/lineage` follows the established per-package layout (pyproject + `src/<pkg>/`), added to `[tool.uv.workspace].members`. Not yet wired into `platform.toml`/console (deferred).

### References
- Brainstorm: `_bmad-output/brainstorming/brainstorming-session-2026-06-08-230821.md`
- Deep-research (Dagster OSS split, Windows, Prefect lineage, automatic lineage) — summarized in memory `project_data_manager_direction.md`
- Code: `packages/lineage/**`, real loader read/write traced in `packages/optimiser/src/optimiser/engine.py`

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Debug Log References
### Completion Notes List
- Foundation (AC 1–9) built + verified ad-hoc before formalization; remaining AC 10–13 open.
### File List
(see Source tree above)
