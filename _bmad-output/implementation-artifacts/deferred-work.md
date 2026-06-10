
## Deferred from: code review of sym universe layer, chunk 3 of project-wide review (2026-06-10)

Backlogged by decision (D1-D4, accepted recommendations):

- **D1 — U3-wire story (PRIORITY: the layer's headline safety promise):** route `run_monitor` through a maintained-membership snapshot diff (`diff_identifier_sets` + `maintained_tokens`, both written and tested) so snapshot sources (B3/ETF/criteria) can emit LEAVES; route surprising/poll-bounded discoveries through `stage_and_promote` (gating live, `MONITOR_GATED` assigned); give `run_accuracy_check` a CLI + schedule; expose `reverse_change` in the CLI. All three review layers found this independently; `universe-maintenance.md` now carries an honesty note until it lands. Mitigations applied in-review: monitor idempotency guard (no daily re-append), gating persistence rule fixed (last_seen), criteria universes monitorable.
- **D2 — snapshot-pin resolution watermark:** `members_pinned` watermarks events but not resolutions — a post-pin resolution changes a re-run. Needs `resolved_at` (schema). Caveat documented in `snapshot.py`.
- **D3 — provenance-aware `correct` events:** the projector treats `correct` as a context-free toggle (ignores `provenance.reverses`); an intervening change inverts its intent, and the dedupe key makes a same-date re-correction a silent no-op. Event-model redesign.
- **D4 — maintenance plans for the 12 populated index universes** (S&P 500/400/600 + 8 European): required by the standing populate-gate rule; only `ibov` is documented.

Deferred findings:

- FIGI-level accuracy comparison: the token-set gate is meaningless across token schemes (ticker-tokenised universe vs isin-tokenised ETF reference); compare resolved FIGIs instead. Docstring caveat added.
- Wikipedia revision-diff client (U2.3 AC2's "revision history" path): `revision_diff` is pure + tested but nothing fetches revisions.
- Monitor coverage for non-index kinds: `stale_monitors` defaults to `kinds=("index",)` — criteria universes can silently freeze out of the digest.
- ETF proxy provenance tagging (U2.2 AC3): `PROXY` marker is dead; events carry no proxy provenance jsonb.
- Criteria-universe evolution semantics: re-evaluation appends joins only — an evolving screen accumulates the union of snapshots (pairs with D1's leaver diff).
- FMP partial-fetch verification: no expected-vs-returned count check exists (docstring now says so honestly); a throttled partial list passes silently.

- Multi-flag review schema: audit (`sweep_divergence`) and ingest (`price_jump`/non-trading-day) flags share one `(figi, session_date)` slot and clobber each other while unreviewed; `pct_move` flips between signed and unsigned-relative semantics. Fix = one row per flag_type (schema change).
- Run-log row written up-front (`status='running'`, finalized on completion) so a process death mid-run leaves a visible record instead of silently missing FR-8 history. Pairs with the Operate heartbeat backlog item.
- Persistent FX-rejection table (FX NFR4's `prices_review` analog): plausibility rejections live only in the in-memory `FxLoadSummary.flagged` list — printed, never stored. After a genuine >50% move (peg break) the band also wedges until an operator notices; a durable review surface is the fix for both.
- `convert()` returns bare `None` — the legs' rich `FxResolution` status (stale vs no-data vs leg-spread) is discarded. Surface a reason (FX3b AC3's "+ flag").
- `sym audit` covers active securities only — a vendor's retroactive correction inside a recently-delisted name's trailing window is never detected.
- Data-level survivorship test (Story 3.7 AC3): compute returns for a known delisted figi through its delist date (needs DB-backed test infra; current guards are static source scans).
- Currency-redenomination history: `fx/restate.py` applies the security's CURRENT currency across all history (wrong across e.g. pre-euro changeovers). Needs an SCD currency table that doesn't exist yet.
- Read-side dirty-set for returns recompute (Story 3.6 efficiency intent): loader recomputes everything in range and skips only at the upsert.
- PR-vs-TR benchmark mixing: the `dax` link makes a TR index primary against PR member returns (amended B3 accepted variant-free storage; alpha consumers should get a variant-awareness pass under the index-maintenance plan).
- MSCI date-format ambiguity: `_DATE_FORMATS` tries day-first then month-first — `03/04/2025` parses day-first silently. Operator-controlled import; document the expected format or add a column/format hint.

## Deferred from: code review of QRP module layer, chunk 1 of project-wide review (2026-06-10)

Roadmap-depth FR gaps (spec'd, built to demo depth in the 2026-06-08 v1) + refactors that fold into the decided qrp/packages restructure:

- FR-15: portfolio returns are a latest-weights × latest-returns dot product — not time-weighted, no PnL (money), weights history never consumed time-series-wise [portfolios/gateway.py:197-264; analytics/gateway.py:85-139 applies latest weights retroactively].
- FR-20: macro observations carry `source` but no release/vintage date — restatements indistinguishable [macro/ingest.py:38-55].
- FR-22: optimiser takes no constraints input (hardcoded long-only sum=1), never consumes `signals.score`, and has no save-solution-as-Portfolio path [optimiser/engine.py:101-111, router.py:50-55].
- FR-17: analytics benchmark picker lists only `instrument.kind='index'` — a sym Universe cannot be the benchmark [analytics/gateway.py:68-83].
- Gateway encapsulation: backtest router reaches into `gw._sym`; several gateways type `sym_conn: ... | None` then dereference unconditionally [backtest/router.py:89; analytics/gateway.py:70]. Fold into the qrp structure-target refactor.
- DRY: eight byte-identical `db.py` helpers (already drifted once — see analytics `_OWN` bug); fold into the decided qrp/packages restructure rather than patching eight copies.

Backlogged by decision (review 2026-06-10, D2/D4/D6/D7 accepted recommendations):

- **Operate architecture story (D2):** reconcile subprocess-everything vs the recorded library-first ADR-1 (or record the reversal); add `heartbeat_at` + orphaned-run reconciliation; add `triggered_by` provenance + `run_log_id` correlation to `pipeline_run_log`; decide lock granularity (spec said per Operation, built per op+args); widen the op allowlist (fx/fill/eod/universe review|confirm) or record the narrowing; build the FR-6 run-history endpoint over `pipeline_run_log` (v1 spec item, missing entirely). Immediate wedge/lock dangers patched in-review (stable lock key, stale-job window, thread-death guard).
- **API hardening (D4):** same-origin/CSRF guard on actuation endpoints; move backtest/optimiser engine execution out of request handlers (into Operate). Accepted as-is for local single-operator v1; arg flag-injection patched in-review.
- **Error envelope rollout (D6):** spec'd `{error:{type,message,detail?}}` envelope + unified `ok|degraded|failed|stale` status vocabulary across all modules. Operate's dishonest 200s patched to 409/422 in-review.
- **analytics boundaries (D7):** remount under its own toggle-scoped prefix (currently appears under `/api/portfolios/...` even when the portfolios toggle is off); consume weights via the portfolios gateway instead of reading `portfolio_weight` directly; replace retroactive latest-weights application with effective-dated weighting (pairs with the FR-15 time-weighted-returns deferral). `_OWN` mislabel patched in-review.

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
