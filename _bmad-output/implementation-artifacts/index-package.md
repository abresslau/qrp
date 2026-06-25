# Story: Extract `index` (benchmark levels · index returns · universe-benchmark link) into its own peer package WITH its own database

Status: review

<!-- Created via bmad-create-story 2026-06-25 (Andre: "remove also index from sym database and packages
and create a dedicated one index"). FOURTH extraction in the sym-decomposition program, the explicit
follow-up named in equity-package.md ("Index extraction is an explicit follow-up, out of scope here").
Same destination as fx/universe/equity: a full peer package with its own database under the
DB-per-package + DuckDB-federation topology (project_db_topology_direction), library-first
(project_qrp_structure_target, sym_is_peer_not_hub). Playbook proven 3x:
project_fx_extracted_own_db, project_equity_extracted_own_db, universe-package.md. -->

## ✅ NAMING DECISION — RESOLVED: `indices`

Andre chose **`indices`** (2026-06-25, AskUserQuestion) over the literal `index`, because `index` is a
SQL **reserved word** (a DB/schema named `index` would need double-quoting in DDL + search_path).
`indices` avoids that entirely, reads as a collection, matches the existing plural peers `rates`/
`signals`, and aligns with the already-standardised `/api/sym/indices` API surface (commit efea397).

**Substitution rule for the dev agent** — apply `indices` to the *package/DB/schema/sqitch-project
identifier ONLY*. Concretely:
- USE `indices`: `packages/indices/`, `src/indices/`, `import indices`, `from indices.db import connect`,
  the `indices` console script, the `indices` Postgres DB + named schema, the `%project=indices` sqitch
  project, the `deploy_all.py` REGISTRY key `"indices"`, the `config.package_dsn("indices")` key, and
  the new lineage const (call it `INDICES`).
- LEAVE UNCHANGED (these contain the substring "index" but are NOT the package name): the table names
  `index_levels`, `fact_index_returns`, `fact_index_extremes` (and `universe_benchmark`); the existing
  `INDICES` registry tuple in `levels.py`; the drop migration `index_extract.sql`; the topology set name
  (`INDEX_RELATIONS` is fine, or `INDICES_RELATIONS` — pick one); the `INDEX_FIGIS` map; the API routes
  `/api/sym/indices*`; MSCI vendor keys/verbs.
- The reserved-word quoting notes elsewhere in this story NO LONGER APPLY (no quoting needed).

## Story

As the QRP maintainer,
I want the benchmark/index subsystem — index level series, materialised index returns + 52-week
extremes, and the universe→benchmark link — extracted from `sym` into its own `index` peer package
**with its own database** (like fx/rates/commodities/universe/equity),
so that index/benchmark data is a fully independent bounded context, leaving `sym` as the **generic**
security-master + reference + classification + identity-bridge spine — without breaking the EOD
`indices` step, the MSCI pulls, the WEI board, the Indices page, the `universe_benchmark` joins, or the
data-monitor / lineage wiring.

## Scope decision — what is "index" (moves) vs what is "generic" (stays in sym)

**MOVE to the `index` DB (benchmark FACT + link data):**
- `index_levels` — immutable benchmark level series (keyed `sym_id`, `session_date`; `level > 0`;
  `source` ∈ yahoo|msci). [`packages/sym/migrations/deploy/index_levels.sql`,
  `index_levels_drop_variant.sql`]
- `fact_index_returns` — materialised index returns over the 18 windows (PK `sym_id, window_id,
  as_of_date`; FK `window_id → return_window`). [`fact_index_returns.sql`]
- `fact_index_extremes` — 52-week trailing high/low per index (PK `sym_id, as_of_date`; no gate).
  [`fact_index_extremes.sql`]
- `universe_benchmark` — links a universe to its benchmark index series (PK `universe_id, sym_id`;
  `role` ∈ price_return|total_return|net_total_return; one primary per universe).
  [`universe_benchmark.sql`]
- **Seed** a small copy of `return_window` into the index DB (28 static rows) to keep the
  `fact_index_returns.window_id` FK same-DB — exactly the equity precedent (equity seeded its own
  `return_window` copy for `fact_returns`).

**MOVE to the `index` package (Python — the index engine):** the whole `packages/sym/src/sym/indices/`
tree → `packages/index/src/index/`:
- `levels.py` — `Index` dataclass + `INDICES` registry (~25 headline indices: S&P family, Nasdaq, Dow,
  Russell, European, Nikkei, IBOVESPA, MSCI World NR, VIX), `YahooIndexLevelSource`, `load_index_levels`,
  region/country/category resolution, `index_xrefs`.
- `returns.py` — `recompute_index_returns` (materialise returns + extremes), `index_return_rows`,
  `alpha`, `index_return`. **Already imports `equity.returns.{windows,extremes}`** — see Knot 3.
- `msci.py` — MSCI file import + direct-pull (`load_msci_file`, `load_msci_pull`, `pull_all_msci`,
  variant-encoded xrefs PR/NR/GR).
- `figis.py` — canonical OpenFIGI attach (`attach_index_figis`, `INDEX_FIGIS`).
- `links.py` — universe↔index linking (`link_universe_indices`, `universe_with_index`, `primary_index`,
  `universe_indices`). Reads the universe DB (roster) + index levels.
- `__init__.py`.
- Plus the index fidelity/reconcile check: `packages/sym/src/sym/validate/index_levels.py`
  (`check_index_level_fidelity`) → `packages/index/src/index/validate/` (or `index/reconcile.py`).

**STAYS in sym (GENERIC — identity · reference · classification · bridge):**
- Identity bridge: `instrument`, `instrument_xref` — the `sym_id` cross-asset spine. Index facts are
  keyed on `sym_id`, so the index package reads identity cross-DB from sym (see Knot 2). **This is the
  key difference from equity** (which keyed on `composite_figi`): index stays bridged to the generic
  `sym_id` spine, which is exactly why it stayed in sym through the equity extraction.
- Reference: `return_window` (MASTER stays in sym — it is still read by the sym API
  `return_windows()` heat-map selector [`modules/sym/gateway.py:361`], the portfolio gateway window-id
  resolver [`portfolio/gateway.py:365`], and referenced by analytics. The index DB gets its own seeded
  copy; **do NOT drop sym's**), `currency`, `exchange`, `trading_calendar`.
- Classification, fundamentals, universe membership (its own DB already), validation/monitoring.

## Acceptance criteria

1. **New `index` peer package + database.** `packages/index/` with `pyproject.toml` (name=index,
   console_scripts `index=index.cli:main`, deps psycopg/pandas/yfinance + **`equity`** for the returns
   math + the workspace), `src/index/{db.py, cli.py, __init__.py, …}`, and `db/` sqitch project
   (sqitch.conf %project=index, sqitch.plan, deploy/revert/verify). Schema is the named `index` schema
   (matches fx/universe/equity's named-schema convention) with a DB-level `search_path` so bare names
   resolve on every connection. Registered in `tools/deploy_all.py` REGISTRY, the workspace
   `pyproject.toml`, and `services/api/pyproject.toml` deps. **Deploys + verifies via Docker sqitch**
   (`tools/deploy_all.py --only index`). [Reserved-word quoting per the NAMING DECISION above.]
2. **Schema created + data migrated, non-destructively.** The 4 tables exist in the index DB with the
   same columns/keys (cross-DB FKs to `instrument`/`universe` become SOFT references — no cross-DB FK,
   matching the fx/equity playbook); `return_window` seeded (28 rows). `tools/migrate_index_data.py`
   streaming binary COPY copies `index_levels`, `fact_index_returns`, `fact_index_extremes`,
   `universe_benchmark` sym→index (small data — ~25 indices; FK-safe order), idempotent (skip-if-equal),
   per-table commit, row-count assert. Live row counts match sym pre-drop.
3. **Index objects DROPPED from sym (fail-loud).** A `packages/sym/migrations/deploy/index_extract.sql`
   drops `index_levels`, `fact_index_returns`, `fact_index_extremes`, `universe_benchmark` (FK-safe
   order) + revert + verify. Stale sym verify scripts for the moved objects no-op to `SELECT 1;` (the
   equity_extract precedent). `return_window` is NOT dropped. After the drop, all suites + live verify
   pass — any missed reader surfaces as an error, not silent stale data.
4. **One-way dependency, no cycle.** The `index` package imports nothing from `sym`; it reads sym
   identity (`instrument`, `instrument_xref`) and the universe roster cross-DB over **injected
   read-only connections** (the equity `sym_conn` pattern, NOT a Resolver — there is no inbound FK from
   sym into index, so no true cycle). `index → equity` (returns math) is the existing one-way import,
   preserved. sym depends on `index` (the EOD `indices` step opens an index connection).
5. **No operational cross-DB joins.** Every place that JOINed index tables to `instrument`/
   `instrument_xref`/`universe` is split into roster-fetch (keys from one DB) + a scoped read on the
   other DB + a Python merge. Specifically the API gateway index methods (Knot 1) and `links.py`.
6. **API surface preserved.** The `/api/sym/indices*` routes are UNCHANGED (preserve the WEI console
   page + Indices page; minimise blast radius — the equity precedent, where equity prices are still
   served through the sym gateway over an `equity_conn`). The sym gateway gains an `_index()` connection
   opener and repoints its index SQL there; `index_board`/`index_board_live`/`indices`/`index_levels`/
   `index_reconcile` keep their response shapes. WEI page + Indices page render identically (CDP-verify).
7. **EOD + CLI + lineage rewired.** The `indices` step in `sym/eod.py` opens an index connection (+
   sym_conn + u_conn) and calls the index package. A new `index` CLI exposes the verbs (`index
   levels`/`load`, `index msci-import`, `index msci-pull`, `index reconcile`, the universe-index
   snapshot). `lineage/bucket_jobs.py` + `schedules.py` job commands for the `index_levels` bucket are
   repointed from `sym indices`/`sym msci-pull` to the `index` CLI; the Dagster "launch" from the
   data-monitor board still works.
8. **lineage + data-monitor + topology repointed.** `lineage/buckets.py` `index_levels` Dataset moves
   from `SYM` to a new `INDEX` const (table `index.index_levels`); `assets.py`, `generate.py` `_MODELED`,
   and the derived FK/column lineage for `index_levels`/`fact_index_returns` repoint to the index
   package. `data_monitor/eod.py` reads `index_levels` over an index connection (the equity precedent).
   `sym_contract.py`: remove `fact_index_returns` from `SYM_READ_SURFACE` and `index_levels`/
   `universe_benchmark`/`fact_index_extremes` from `SYM_INTERNAL_RELATIONS`; add a new `INDEX_RELATIONS`
   vocabulary set in `test_topology_discipline.py` (mirroring `EQUITY_RELATIONS`/`UNIVERSE_RELATIONS`)
   and add `packages/index/db` to the gate's project list. `return_window` stays on the sym surface.
9. **Green.** Full suites green (sym, index [new], equity, backtest, signals, optimiser, api, lineage),
   `ruff` clean, `tools/deploy_all.py --status` shows index deployed + every DB up to date, and a live
   end-to-end check passes (EOD `indices` step writes to the index DB; `/api/sym/indices/board` +
   `/api/sym/indices/{id}/levels` return data; WEI + Indices pages render via headless Chrome).

## Architecture — the knots (cross-DB seams to get right)

**Knot 1 — the API gateway index reads (the largest piece).**
`services/api/src/qrp_api/modules/sym/gateway.py` serves five index methods that today JOIN
`index_levels`/`fact_index_returns` to `instrument` + `instrument_xref` (for name/region/country/
currency/msci_code/variant) and, for the board, compute YTD/sparkline/52w from the level series:
`indices()`, `index_levels(sym_id)`, `index_board(as_of_date)`, `index_board_live(now)`,
`index_reconcile()`. After the move these become cross-DB:
- Fetch the level/return rows + `sym_id`s from the **index** DB.
- Fetch the instrument metadata (name, currency, xrefs, region/country) for those `sym_id`s from
  **sym** (`instrument` + `instrument_xref`), keyed by the `sym_id` roster.
- Merge in Python (no cross-DB JOIN). Preserve the board's ranked-CTE last/prior-session logic + the
  ~1900-day sparkline window read (those stay single-DB on the index side).
Mirror exactly how the gateway already reads equity prices over `_equity()` — add `_index()` and an
`index_conn` ctor param. This is the highest-risk, most test-covered surface
(`test_indices_route.py`); keep response shapes byte-identical.

**Knot 2 — identity is `sym_id`, read cross-DB from sym.** Index facts FK `sym_id → instrument`. After
extraction that becomes a SOFT reference (no cross-DB FK). The index package needs a read-only
`sym_conn` to: create/resolve instrument identity on load (`load_index_levels`/`load_msci_*` ensure an
`instrument` row + `instrument_xref` for each index), and to read instrument meta for the board. Thread
`(index_conn, sym_conn)` through the engine entry points; `instrument`/`instrument_xref` writes during
load stay on the sym connection (identity is sym-owned). Confirm whether `load_index_levels` *writes*
instrument rows (it does — "ensures instrument identity") → those writes target sym, the level writes
target index. This is the one place the index loader writes to sym (identity only).

**Knot 3 — `index → equity` import is fine, keep it.** `index/returns.py` imports
`equity.returns.windows` (`WINDOWS`, `base_date`, `canonical_return`, `end_date`, `period_years`) and
`equity.returns.extremes` (`compute_extreme_rows`). This is pure return math, one-way (index depends on
equity), no cycle. Add `equity` to the index package deps. Do NOT duplicate the window math.

**Knot 4 — `universe_benchmark` is doubly cross-DB.** It links `universe_id` (universe DB) + `sym_id`
(instrument in sym). Moving it into the index DB makes both FKs soft references. `links.py`
`link_universe_indices(conn, u_conn)` already reads the universe DB; after the move it writes
`universe_benchmark` to the index DB while reading the universe roster cross-DB + resolving `sym_id`
from sym. `universe_with_index` joins constituents (universe DB) + primary index level (index DB) →
keep as roster-fetch + Python merge.

**Knot 5 — `return_window` stays master in sym.** Index gets a seeded copy for the FK; sym keeps its
own (still read by the sym API + portfolio + analytics). 28 static rows, never drift — duplicate, do
not move. (Identical to equity.)

## Tasks / Subtasks (the 7-phase extraction playbook)

- [x] **P0 — Resolve the naming decision** (`index` vs recommended `indices`); fix the token. (AC: 1)
- [x] **P1 — Scaffold the package + DB** (AC: 1)
  - [x] `packages/index/` pyproject (deps psycopg/pandas/yfinance/equity + workspace), `src/index/`
        skeleton, `db.py` (`connect()` pinning search_path; `sym_connect()` read-only helper).
  - [x] sqitch project (`db/sqitch.conf` %project, `sqitch.plan`, deploy/revert/verify for
        `index_schema` + `seed_reference` [return_window 28 rows] + `index_namespace` [named schema +
        DB search_path]). Schema mirrors the 4 tables; cross-DB FKs dropped → soft refs.
  - [x] Register in `tools/deploy_all.py` REGISTRY, workspace pyproject, services/api deps.
  - [x] `deploy_all.py --only index` → deployed + verified.
- [x] **P2 — Move the Python engine** (AC: 4, 7)
  - [x] `git mv packages/sym/src/sym/indices packages/index/src/index/` (+ the indices test files);
        move `sym/validate/index_levels.py`. Make the package sym-import-free.
  - [x] Thread `(index_conn, sym_conn[, u_conn])` through `load_index_levels`, `recompute_index_returns`,
        `link_universe_indices`, `load_msci_*`, `attach_index_figis`, `check_index_level_fidelity`.
  - [x] New `index` CLI (`index/cli.py`) with the verbs; keep equity import for returns math.
- [x] **P3 — Migrate the data** (AC: 2)
  - [x] `tools/migrate_index_data.py` (binary COPY, idempotent, per-table commit, row-count assert;
        seed return_window first; FK-safe order: index_levels → fact_index_returns/extremes;
        universe_benchmark independent). Run it; verify counts == sym.
- [x] **P4 — Rewire sym + external consumers** (AC: 5, 6, 7, 8)
  - [x] `sym/eod.py` `indices` step → open index_conn (+ sym_conn + u_conn), call the index package.
  - [x] `sym/cli.py` — remove the moved index subcommands (or thin-dispatch); EOD no longer imports
        `sym.indices`.
  - [x] API gateway (Knot 1): add `_index()` + `index_conn`; split the 5 index methods into
        roster-fetch + Python merge; keep response shapes. Routes UNCHANGED.
  - [x] lineage: `INDEX` const + repoint `index_levels`/`fact_index_returns` Datasets/assets/lineage;
        `bucket_jobs.py`/`schedules.py` commands → `index` CLI.
  - [x] `data_monitor/eod.py`: read `index_levels` over an index connection.
- [x] **P5 — Drop from sym (fail-loud)** (AC: 3)
  - [x] `sym/migrations/{deploy,revert,verify}/index_extract.sql` (drop the 4 tables, FK-safe; NOT
        return_window). No-op stale verify scripts for moved objects. Deploy via Docker sqitch.
- [x] **P6 — Topology + contract** (AC: 8)
  - [x] `sym_contract.py`: remove the 4 index relations from the sym sets (keep return_window).
  - [x] `test_topology_discipline.py`: add `INDEX_RELATIONS`, add `packages/index/db` to PROJECT list,
        extend the known-vocabulary union.
- [x] **P7 — Verify everything** (AC: 9)
  - [x] Full suites + ruff + `deploy_all --status`; live EOD `indices` run → index DB; API + WEI +
        Indices pages via headless Chrome; update any api fakes for the new cross-DB query shapes.

## Dev Notes

- **Branch:** `feat/index-package` off `main` (matches the per-extraction branch convention; large,
  merge after `/code-review` — do NOT merge unreviewed, per house practice).
- **Reuse the playbook, don't reinvent:** the fx/universe/equity extractions are the template. Read
  `equity-package.md`, `packages/sym/migrations/deploy/equity_extract.sql`, and
  `tools/migrate_equity_data.py` before starting — the COPY streaming, the per-table commit, the
  no-OVERRIDING-on-COPY note, the named-schema + DB search_path, the `_equity()` gateway opener, the
  `sym_conn` injection, the fail-loud drop, and the topology-set patterns all transfer directly.
- **Data is small** (~25 indices × dates + ~18 windows): the migration is seconds, not the 30M-row
  equity slog. No `count(DISTINCT)` perf traps here, but keep the board's existing sparkline-window read
  bounded as it is today.
- **`as_of_date` canonical:** `fact_index_returns`/`fact_index_extremes` already use `as_of_date` —
  preserve it; do not introduce `asof` (the equity review caught a constraint-name regression — name any
  new constraint `*_as_of_date_*`). [feedback_as_of_date_canonical_name]
- **Reserved word:** if staying with `index`, quote `"index"` only in DDL/search_path; everywhere else
  bare table names resolve via search_path. (Strongly prefer `indices`.)
- **psycopg durability/autocommit, Docker-sqitch deploy, schedules explicit-tz** — same house rules as
  every prior package (the schedule for the index bucket must set `execution_timezone`).
  [feedback_schedule_explicit_timezone, reference_sqitch_deploy_docker]
- **Files to touch** (from the index-footprint map):
  - NEW: `packages/index/**`, `tools/migrate_index_data.py`,
    `sym/migrations/{deploy,revert,verify}/index_extract.sql`.
  - MOVE: `sym/indices/**`, `sym/validate/index_levels.py` (+ tests `test_indices.py`,
    `test_index_figis.py`, `test_index_reconcile.py`).
  - UPDATE: `sym/eod.py`, `sym/cli.py`, `services/api/.../modules/sym/{gateway.py,router.py}` (gateway
    only — routes unchanged), `services/api/.../sym_contract.py`,
    `services/api/.../modules/data_monitor/eod.py`, `packages/lineage/src/lineage/{buckets.py,assets.py,
    generate.py,derived_lineage.py,bucket_jobs.py,schedules.py}`,
    `services/api/tests/test_topology_discipline.py`, `tools/deploy_all.py`, workspace +
    services/api `pyproject.toml`, and the api test fakes for the new cross-DB shapes
    (`test_indices_route.py`, `test_twr_weight_history.py`).
  - DO NOT TOUCH (preserve): `apps/web/app/sym/wei/page.tsx` + the Indices page (routes unchanged);
    `sym.return_window`; the MSCI vendor keys/verbs.

### Project Structure Notes

- Aligns with the DB-per-package + DuckDB-federation topology and the proven extraction playbook
  (4th instance). One-way dep inversion via injected read-only `sym_conn` (no Resolver — no inbound FK
  from sym → index, unlike universe). `index → equity` is an existing one-way import; keep it.
- Variance vs equity: identity key is `sym_id` (not `composite_figi`), and the index loader *writes*
  instrument identity rows to sym (Knot 2) — the only sym write from the index package.

### References

- [Source: _bmad-output/implementation-artifacts/equity-package.md] — the template + the explicit
  "index extraction is a follow-up" scoping note.
- [Source: packages/sym/migrations/deploy/equity_extract.sql], [Source: tools/migrate_equity_data.py] —
  drop + migrate patterns.
- [Source: packages/sym/src/sym/indices/*] — the engine being moved (levels/returns/msci/figis/links).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — the 5 index methods to split (Knot 1).
- [Source: services/api/src/qrp_api/sym_contract.py:25,33,55-58] — current index relations to move.
- [Source: services/api/tests/test_topology_discipline.py] — `EQUITY_RELATIONS`/`UNIVERSE_RELATIONS`
  precedent for the new `INDEX_RELATIONS` set + PROJECT list.
- [Source: packages/lineage/src/lineage/buckets.py] — `index_levels` bucket (SYM → INDEX).
- Memory: project_db_topology_direction, project_equity_extracted_own_db, project_fx_extracted_own_db,
  feedback_sym_is_peer_not_hub, feedback_as_of_date_canonical_name, feedback_schedule_explicit_timezone.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (bmad-dev-story), 2026-06-25. Branch `feat/indices-package` off main.

### Debug Log References

- **Name resolved to `indices`** (not `index` — SQL reserved word). All identifiers
  (package/DB/schema/sqitch project) match; table names (index_levels, fact_index_returns, …),
  routes (/api/sym/indices), and the lineage `INDICES` const kept their existing forms.
- **env churn**: a prior failed `uv sync` (blocked by a running uvicorn/dagster holding their .exe
  shims) had removed editable workspace members. Resolved by killing the stale stack + the correct
  command for this virtual-root workspace: **`uv sync --all-packages`** (plain `uv sync` installs
  only the root's deps and removes members). Recorded for next time.
- **INTRANS write-path bug (fixed)**: `connect()` ran `SET search_path` on a non-autocommit conn →
  INTRANS; the write-engine functions set `conn.autocommit = True` first → raised. Fixed by opening
  with `autocommit=True`. **The fake-conn tests did not catch it; the live recompute did.** The
  equity/universe/fx `connect()` share the identical pattern — pre-existing, flagged for follow-up.

### Completion Notes List

All ACs met. Executed the proven 7-phase extraction playbook (4th, after fx/universe/equity):

- **P1** new `indices` package + own `indices` DB (named schema + DB search_path; sqitch
  indices_schema + seed_reference; 4 tables, sym_id/universe_id soft refs, window_id same-DB FK;
  registered in deploy_all + workspace). Deployed+verified.
- **P2** moved `sym/indices/{levels,returns,msci,figis,links}` → the package; sym-import-free via a
  local `indices/identity.py` (generic instrument-identity helpers operating on an injected
  `sym_conn`); threaded `(indices_conn, sym_conn[, u_conn])` through every entry point; new `indices`
  CLI. reconcile/fidelity stays in sym as a validate consumer.
- **P3** `tools/migrate_indices_data.py` — binary COPY of 4 tables (225,815 / 4,189,976 / 7,345 / 12);
  counts match sym.
- **P4** rewired sym eod/cli, the API sym gateway (5 index methods → roster-fetch + Python merge via a
  lazy `_indices()`; routes UNCHANGED), the validate reconcile consumer, lineage (INDICES const +
  index_levels/fact_index_returns assets), data_monitor `_index_breakdown`. Updated api test fakes.
- **P5** `sym:index_extract` dropped the 4 tables from sym (fail-loud; return_window + instrument
  stay). Fixed the earlier extract verifies (`sqitch verify` re-runs them) that asserted
  fact_index_returns/universe_benchmark present. Deployed+verified; data intact in indices.
- **P6** `sym_contract.py` reclassified the index relations off the sym surface; `INDEX_RELATIONS`
  added to the topology gate. qrp_readonly grant clean (8/8).
- **P7** verified: **930 tests green** (indices 36 + sym 493 + equity + backtest + signals + optimiser
  + lineage 40 + api 175), ruff clean, all 14 DBs up to date, live cross-DB gateway reads
  (indices 29 instruments / board 26 rows / levels), live recompute write (27 series / 756 rows),
  and the WEI (`/monitor/wei`) + Indices (`/sym/indices`) console pages render real data (headless
  Chrome). Restarted the dev stack (API :8001 + console :3001).

**Deviations from the literal story (all serve AC#2/#4 + behavior preservation):**
1. Named `indices`, not `index` (reserved-word; Andre's AskUserQuestion choice).
2. The reconcile/fidelity check STAYS in sym as a validate consumer (it produces sym's `CheckResult`
   for the validate runner) — the fx precedent; it reads the indices DB cross-DB.
3. The sym index CLI subcommands were KEPT (rewired to open the indices conn) rather than removed, so
   the lineage `index_levels` job commands (`sym indices`/`sym msci-pull`) need no change; the new
   `indices` CLI is the standalone entry point.
4. `indices` NOT added to the topology gate's PROJECT_SCHEMAS/ALL_PACKAGE_SCHEMAS (matches the
   universe/equity precedent — extracted peers get a *_RELATIONS vocabulary set instead).
5. `return_window` master stays in sym (read by the sym API/portfolio/analytics); indices seeds its
   own copy (equity precedent).

**Follow-up (pre-existing, out of scope):** equity/universe/fx `connect()` have the same INTRANS
autocommit bug — their orchestrated write steps (equity recompute, fx fill) would fail live; worth a
one-line fix each (`autocommit=True`).

### File List

NEW: `packages/indices/**` (pyproject, src/indices/{__init__,db,cli,identity,levels,returns,msci,
figis,links}.py, db/{sqitch.conf,sqitch.plan,deploy,revert,verify}, tests/*), `tools/migrate_indices_data.py`,
`packages/sym/migrations/{deploy,revert,verify}/index_extract.sql`.
MOVED (from sym/indices): the 5 engine modules + 5 test files.
UPDATED: `pyproject.toml`, `tools/deploy_all.py`, `packages/sym/pyproject.toml`,
`packages/sym/src/sym/{eod.py,cli.py,validate/index_levels.py}`,
`packages/sym/migrations/sqitch.plan` + the no-op'd index verify scripts + equity_extract/
universe_extract verifies, `services/api/src/qrp_api/modules/sym/gateway.py`,
`services/api/src/qrp_api/sym_contract.py`, `services/api/src/qrp_api/modules/data_monitor/eod.py`,
`packages/lineage/src/lineage/{buckets.py,assets.py}`,
`services/api/tests/{test_indices_route.py,test_data_monitor_eod.py}`,
`services/api/tests/test_topology_discipline.py`, `uv.lock`.

### Change Log

- 2026-06-25: index/benchmark subsystem extracted from sym into the `indices` peer package + database
  (P1–P7). Branch `feat/indices-package`; 7 commits; NOT yet merged (awaiting code-review).
