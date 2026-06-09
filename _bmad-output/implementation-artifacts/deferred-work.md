
## Deferred from: code review of 3.1-ext-return-window-expansion (2026-06-07)

- `base_date` assumes `asof` is a member of the calendar `sessions` list. Off-calendar price dates (known pre-1990 / vendor-phantom bars, already WARN-classified and inert to returns) make the SESSION-count and snap logic count from the insertion point — slightly off but harmless. Optional hardening: snap `asof` via `_last_on_or_before` before counting. Pre-existing (all base-date snapping shares this assumption).
- No test asserts the migration-seeded `return_window.kind` matches the `windows.py` spec. Low impact: `kind` is non-functional metadata (the engine computes from `windows.py` constants, never the DB column), so drift would be cosmetic. Could add a live consistency check.
- Migration revert scripts hardcode code-lists (`trailing_kind_prior_quarter`) and use `BETWEEN 21 AND 27` range deletes (`cumulative_multiyear_windows`) instead of structural inverses. Correct for the current window set; fragile if new windows are inserted in those id ranges later.
- Equity loader has no test for the since-inception day-one semantics (`SI`=0, `SI_ANN`=None on a single-session history); only the index side (`test_benchmark_returns`) covers it.
- No PQ (`period` kind) test against a sparse or real exchange calendar — current tests use dense weekday fixtures only.

## Deferred from: code review of QL-1-lineage-dagster-foundation (2026-06-09)

All deferred to the AC10 auto-feeder rollout (derive.py / sql_capture.py are a proven prototype; hardening belongs to productionization):

- derive_edges run-correlation is cartesian with no per-run or statement-order scoping → fabricates edges (every read→every VALUES write), incl. empty-key edges to metadata targets (solution/run/point) [derive.py:116-124].
- Multi-connection captures never combine: loaders read via one conn and write via another (e.g. optimiser sym_conn/opt_conn), each `CapturingConnection` has its own `.captured` → no cross-DB edge unless the lists are merged per run [sql_capture.py].
- CTE aliases counted as source tables via `find_all(exp.Table)` (`shares`,`px`,`latest`) → phantom upstream assets [derive.py:82].
- `pg_schema` output never passed as `schema=` to sqlglot → `SELECT *` / unqualified-join key tracing silently dropped (advertised capability unreachable) [derive.py:53].
- `%s`→`NULL` blind replace corrupts string literals containing `%s` and named `%(name)s` placeholders [derive.py:45-47].
- UPDATE/DELETE/MERGE not classified as writes; CTAS (`CREATE TABLE AS SELECT`) misclassified as a pure read [derive.py:59-85].
- `to_dagster_metadata` matches target by bare table name → collisions for generic names (run/weight/score/point) across packages [derive.py:141].
- Edge dedup key omits `keys` → non-deterministic key list when a table-pair recurs [derive.py:127-131].
- INSERT…SELECT computed-key passthrough dropped when the key isn't a literal source column [derive.py:110].
- sql_capture runtime semantics: statements from rolled-back txns retained; non-`autocommit` attribute sets land on the wrapper not the real conn; `row_factory`/`cursor_factory`/named cursors/COPY un-proxied; empty `executemany` records a phantom write [sql_capture.py].
- `pg_schema` collapses same table name across schemas — matters under the planned DuckDB federation [derive.py:39-41].

## Deferred from: code review of QL-2-auto-feeder-rollout (2026-06-09)

Low-reachability for current loaders (single-statement, no MERGE/CTAS/VIEW/string-placeholders) or future-topology — revisit in QL-3:

- CTAS branch also matches `CREATE VIEW … AS SELECT`; INSERT/CTAS where `tree.this` isn't a Schema/Table yields `target=None` → edge silently lost [derive.py:98-103].
- MERGE / `DELETE…USING` / `UPDATE…FROM` target extraction via `tree.find(exp.Table)` is AST-order-dependent — target/source could swap, inverting an edge [derive.py:105-107].
- `sqlglot.parse_one` keeps only the first statement of a semicolon-joined batch [derive.py:72].
- `_norm` rewrites `%%`/`%(name)s` even inside string literals (docstring "neutralize without corrupting" is overstated) [derive.py:50-55].
- `UPDATE…FROM` source tables are not seeded into `reads_before`, unlike INSERT…SELECT sources [derive.py:161-164].
- `_combined_schema` should key by (db, table) to remove the latent cross-DB same-name collapse (harmless today; matters under DuckDB federation) [generate.py:85-94].

## Deferred from: code review of QL-3-fk-referential-and-visual (2026-06-09)

- The whole lineage keyspace is **bare table name** (no DB qualification) — `_NAME_INDEX`, `FK_REFERENTIAL`, `edges()`, `key_tables` all collapse same-named tables across DBs. Harmless today (30 modeled names unique); a future cross-DB collision misattributes edges. Fix = key by (db, table). Pairs with the QL-2 `_combined_schema` deferral → DuckDB-federation era.
- `lineage/diagram.py` computes the output path via `Path(__file__).parents[2]`, assuming the `src/` layout — would write to the wrong place if the package is installed as a wheel.
- `analytics/metrics` (computed, schema-less) never appears in the Mermaid field-flow even though it has `composite_figi`-bearing deps — documented in the diagram caption; revisit if a computed-node view is wanted.
- `operate/job` asset carries `database="qrp"` but sits in group `operate` — cosmetic db-label mismatch; fold into the de-hub effort (#14).

## Deferred from: code review of B7-identity-key-bridge (2026-06-09)

- Add the cross-key bridge edge (securities.composite_figi → instrument_xref → instrument.sym_id) to the lineage DAG — the `instrument` asset only declares `securities` as a dep; the per-figi xref bridge is undocumented in the graph [lineage/assets.py].
- No warn/exempt tier for delisted/suspended securities in `equity_instrument_bridge` — any unmapped security is a hard FAIL with no graceful tier (other checks downgrade expected gaps to WARN). Steady-state consistent today (backfill maps all statuses); a single legacy unmapped delisted name would pin `sym validate` red [validate/instrument_bridge.py].
- CHAR(12)↔TEXT anti-join (`x.value = s.composite_figi`) is correct only because the figi `^[A-Z0-9]{12}$` CHECK forbids padding; no defensive `rtrim`/cast, and the dependency isn't noted. Latent false-negative/positive surface if the FIGI format is ever relaxed [validate/instrument_bridge.py:24].

## Deferred from: code review of 2-10-explicit-range-reload (2026-06-09)

- `reload_start`/`start` is not snapped to a trading session while `end` is (via `latest_session_for`). Benign today — `DELETE … BETWEEN` over non-session days removes nothing, and `expected_trading_days` only counts real sessions — but the asymmetry is a latent inconsistency. Optional: snap `reload_start` to the first session ≥ it [pipeline.py compute_window RELOAD branch].
