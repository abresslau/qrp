# Story: Extract `equity` (prices · returns · corporate actions) into its own peer package WITH its own database

Status: review  <!-- P1-P7 ALL DONE on feat/equity-package; data migrated; moved tables dropped from
sym (AC#3 met); full suites + live end-to-end + SM-6 accuracy harness green. Branch NOT merged to
main — awaiting Andre's adversarial code-review (one-way dep / behavior preservation / cross-DB
roster-fetch + no-cross-DB-join / the drop). -->

<!-- Created via bmad-create-story 2026-06-25 (Andre: "create a separate package and db for equity so
everything price, returns and corporate actions are in this database. in sym it should stay things that
are generic"). THIRD and LARGEST extraction in the sym-decomposition program (after fx-package.md and
universe-package.md). Same destination: a full peer package like rates/commodities/macro/fx/universe with
its own `equity` database under the DB-per-package + DuckDB-federation topology (project_db_topology_
direction), library-first (project_qrp_structure_target, sym_is_peer_not_hub). Andre asleep; directive:
"execute the change, use your judgement, test everything after." Landed on a branch (feat/equity-package),
NOT merged to main (too large to merge unreviewed — code-review gate before merge per house practice). -->

## Story

As the QRP maintainer,
I want the equity market-data subsystem — raw prices, the returns engine, and corporate actions —
extracted from `sym` into its own `equity` peer package **with its own database** (like fx/rates/
commodities/universe),
so that equity price/return/corporate-action data is a fully independent bounded context, leaving `sym`
as the **generic** security-master + reference + classification spine — without breaking ingestion, the
returns engine, the EOD pipeline, or any downstream consumer (backtest/signals/optimiser/portfolios/
analytics/API).

## Scope decision — what is "equity" vs what is "generic" (stays in sym)

**MOVE to the `equity` DB (price · returns · corporate-action FACT data):**
`prices_raw`, `corporate_actions`, `price_gaps`, `prices_review`, `pipeline_backfill_progress`,
`v_prices_adjusted` (view), `fact_returns`, `fact_price_extremes`, `pipeline_run_log` (the price-load
run log). Plus **seed** two small reference tables into the equity DB to keep FKs intact same-DB:
`currency` (fx precedent — `prices_raw`/`corporate_actions` FK it) and `return_window` (the 28 static
window defs — `fact_returns` FKs it).

**MOVE to the `equity` package (Python — the price/returns/ingest engine):**
`sym/returns/` (windows · loader · extremes), `sym/ingest/` (pipeline · prices · anomaly),
`sym/sources/` (contract · yfinance_adapter · registry). These become sym-import-free (see Knot 1).

**STAYS in sym (GENERIC — identity · reference · classification · bridge · benchmark):**
- Identity: `securities`, `security_symbology`, `securities_review_queue`, `security_names`.
- Reference: `currency` (master; equity gets a seeded copy), `exchange`, `trading_calendar` +
  `trading_calendar_version`. (Calendar is reference data FK-ed to `exchange`; equity reads it cross-DB
  rather than owning it — see Knot 2.)
- Classification: `gics_scd`, `gics_source_opinion`.
- Identity bridge: `instrument`, `instrument_xref` (the `sym_id` cross-asset spine — generic).
- Fundamentals: `fundamentals` (+ `sym/universe/fundamentals.py`, `sym/marketcap.py`) — sym fundamentals
  data; becomes a sym-side **consumer** that reads equity prices cross-DB (mirrors fx's market_cap path).
- **Index/benchmark facts STAY in sym (deliberate scoping):** `index_levels`, `fact_index_returns`,
  `fact_index_extremes`, `universe_benchmark`, `return_window` (master). These are keyed on the
  **`sym_id` identity bridge** (NOT `composite_figi`) and are benchmark plumbing tightly coupled to
  `universe_benchmark` — i.e. generic cross-asset spine, not single-name equity pricing. Keeping them in
  sym avoids a large blast radius (WEI board / indices page / `universe_benchmark` joins / the `sym_id`
  bridge). `return_window` is duplicated (master in sym for the index facts, seeded copy in equity for
  `fact_returns`) — it is 28 rows of static reference data, never drifts. **Index extraction is an
  explicit follow-up, out of scope here.**
- Validation/monitoring: `universe_member_completeness`, `validation_run_log`.

## Acceptance criteria

1. `packages/equity/` is a workspace member with its **own `equity` database**: `db.py` → `equity` DB;
   a Sqitch `db/{deploy,revert,verify}` trio + plan for the moved objects (incl. seeded `currency` +
   `return_window`); registered in `tools/deploy_all.py`; `deploy_all --status` clean; `uv sync
   --all-packages` succeeds. The DB is created + deployed via the house Docker-sqitch method.
2. **`equity` imports nothing from `sym` at module load** (guard test/grep). One-way **`sym` depends on
   `equity`** (sym's cli/eod/indices/marketcap/fundamentals call into equity), never the reverse.
   equity's reads of sym tables (`securities`/`security_symbology`/`trading_calendar`) are done through
   an **injected/explicit sym connection**, not a `sym` import (Knot 1).
3. The equity objects live in the **`equity` database**, not sym — no moved table/view remains in the
   sym DB. No data lost (COPY the existing rows sym→equity, counts verified). Invariants preserved:
   `fact_returns` `input_hash` dirty-set reproducibility, `prices_raw` immutability + anomaly gating,
   per-figi atomic ingestion, survivorship (delisted flow through).
4. **The cross-DB FK knots are resolved cleanly:** `currency` + `return_window` **seeded** in the equity
   DB (FKs stay intact same-DB, reference-data duplication — fx precedent). `composite_figi` FKs to
   `securities` become **soft references** (drop FK; `composite_figi` is a stable string that crosses
   the boundary fine). No cross-DB FK anywhere.
5. **No big cross-DB join anywhere.** Every consumer that joins prices/returns to sym identity fetches a
   small roster/key set and filters locally (roster-fetch, universe precedent). The two single-query
   cross-DB joins in the API gateway (`universe_coverage`, `heatmap`) are split into per-DB reads +
   Python merge on `composite_figi`.
6. **Every existing behavior preserved, verified end-to-end:**
   - `sym load` / `--overwrite` ingests prices into the equity DB (resolver reads `securities`/symbology
     from sym; calendar from sym; per-figi atomic write to equity); `sym audit`/sweep unchanged.
   - `sym recompute` materializes `fact_returns` into the equity DB (reads `v_prices_adjusted` from
     equity + `securities`/calendar from sym); `input_hash` dirty-set still skips unchanged rows.
   - the EOD pipeline (`sym eod`) — fill → recompute → indices → fundamentals → market_cap — runs across
     both DBs with the same nightly outcome; `pipeline_run_log` written to equity.
   - backtest / signals / optimiser get identical returns (fetch `fact_returns`/`fundamentals` — returns
     from equity, fundamentals from sym — both scoped by the pre-fetched roster).
   - the API security explorer / security-detail / universe coverage / heat-map read prices + returns
     from the equity DB (roster-fetch, no cross-DB join); `sym validate` price/returns/readiness checks
     pass cross-DB.
   - the Data Monitor `equity_prices` + `calculations` buckets read the equity DB (another package DB);
     the lineage `prices_raw`/`fact_returns` assets + column lineage still resolve.
7. Suites green (sym, equity, api+lineage, backtest, signals, optimiser), ruff clean, `lineage.
   definitions` loads.

## Developer context — READ THIS FIRST

Largest extraction yet: ~13.5M `prices_raw` + ~15.9M `fact_returns` rows, and the returns/ingest engine
is the heart of sym. Two knots; both are solved by the fx+universe playbook (one-way dep + roster/ref
fetch), NOT a new mechanism.

### 🚦 Knot 1 — make `equity` sym-import-free (one-way `sym → equity`)
The Explore map (2026-06-25) found **no true circular dependency** — the coupling is asymmetric:
- **equity → sym** is one code import (`returns/loader.py`: `from sym.calendar.snapshot import
  current_calendar_version`) + SQL reads of `securities`/`security_symbology`/`trading_calendar`.
- **sym → equity**: `sym.indices.returns` imports `returns.windows`/`extremes` (pure math);
  `sym.cli`/`sym.eod` orchestrate load/recompute; `sym.marketcap`/`fundamentals` read prices.

Resolution (no Resolver-protocol ceremony needed, unlike universe): **inline** the one calendar import
(`current_calendar_version` is a 1-line `SELECT calendar_version FROM trading_calendar_version WHERE
mic=%s AND is_current`) so equity imports nothing from sym; equity engine functions take an **injected
read-only `sym_conn`** for identity/calendar reads alongside their `equity_conn` (exactly fx's
`restate(sym_conn, fx_conn)` pattern). Then `sym → equity` is one-way and clean (sym.indices/eod/cli
import equity; that is fine).

### 🚦 Knot 2 — the cross-DB reads (roster/ref-fetch, not federation)
equity ops need sym data: the ingest **symbol resolver** reads `securities`/`security_symbology`; the
returns **loader** + ingest read `trading_calendar` sessions per mic. These are small (active roster ≈
few thousand rows; a calendar is a few thousand dates) — **fetch via the injected sym_conn, filter
locally**. The `currency` + `return_window` reference tables are **seeded into the equity DB** (fx
precedent) so the FK stays same-DB; `composite_figi` FKs to `securities` drop to soft references.
Downstream consumers that read `fact_returns`/`prices_raw` already scope by a pre-fetched
`composite_figi` roster (backtest/signals/optimiser/data_monitor) — repoint those reads to the equity
DB. The two API gateway single-query joins (`universe_coverage`, `heatmap`) split into per-DB reads +
Python merge.

### Dependency directions (target)
- equity: imports nothing from sym; reads sym tables only via an injected `sym_conn`. Writes only the
  equity DB.
- sym: `indices.returns` imports `equity.returns.{windows,extremes}` (pure); `cli`/`eod` open an equity
  conn and pass `(equity_conn, sym_conn)` to equity ops; `marketcap`/`fundamentals` read equity prices
  cross-DB. One-way `sym → equity`.
- consumers (backtest/signals/optimiser/api/lineage): open the equity DB (full creds, like they open
  `universe` now — `qrp_readonly` is sym-only) for prices/returns; keep reading sym for identity/fundamentals.

### Invariants you must not break
- `fact_returns` `input_hash = hash(raw_slice + factor_set + calendar_version)` dirty-set incremental
  recompute (AR-7); survivorship (delisted flow through — AR-8); two-stage anomaly gate (unreviewed
  `prices_review` rows excluded from `fact_returns`).
- `prices_raw` immutability + per-figi atomic batch (rows + cursor + status one txn); no silent gap-fill
  (`price_gaps`); factor provenance (corporate_actions explicit, never reverse-engineered).
- as_of_date canonical naming; DB-per-package (no cross-DB FK); Sqitch via Docker; schedules explicit tz.
- `universe_reload_no_gaps` (universe drives ingestion — now into the equity DB).

## Suggested phasing (mirrors fx)
1. **Scaffold** `packages/equity/` + create+deploy the `equity` DB (Sqitch trio; seed currency +
   return_window; deploy_all registry; workspace + deps).
2. **Move the engine** (returns/ingest/sources) → equity; inline the calendar query; functions take
   `(equity_conn, sym_conn)`; equity imports nothing from sym; schema-qualify SQL.
3. **Rewire sym orchestration/consumers** (cli, eod, marketcap, fundamentals, indices import path) to
   open an equity conn + pass it.
4. **Rewire external consumers** cross-DB (backtest/signals/optimiser, api gateway/data_monitor,
   lineage buckets/assets, sym_contract surface, provision_readonly).
5. **Migrate data** (COPY the moved tables sym→equity; seed currency + return_window; counts verified).
6. **Verify** the AC#6 matrix + suites + deploy_all + import-guard + lineage.
7. **Drop** the equity objects from the sym DB (LAST, after verify) via a sym `equity_extract` migration.

## Out of scope / Deferred
- **Index/benchmark extraction** (`index_levels`/`fact_index_returns`/`fact_index_extremes`/
  `universe_benchmark`) — they ride the `sym_id` bridge; a separate later story.
- DuckDB federation as the operational read mechanism (roster/ref-fetch here).
- Moving the API price/returns endpoints to their own `equity` router (cosmetic; logic moves, HTTP
  surface stays in the sym module for now). Renaming the `equity_prices`/`calculations` buckets.
- Full `sym load`/`recompute` CLI removal — keep `sym` as the orchestration entry (mirrors `sym fx`).

## Dev Agent Record

### Key decisions / deviations (recorded during dev, 2026-06-25)
1. **equity DB uses a dedicated `equity` schema** (the per-package named-schema convention, matching
   fx.*/universe.*). Initially built in `public` to minimise churn on the verbatim-moved engine, then
   corrected on Andre's call (2026-06-25) via the `equity_namespace` migration: in-place
   `ALTER … SET SCHEMA equity` (catalog-only, no data re-copy) for all objects + a DB-level
   `ALTER DATABASE equity SET search_path TO equity, public` so the engine's + every consumer's
   UNQUALIFIED reads resolve on every connection path (more robust than universe's import-only pin,
   since equity is read over several connect paths). `equity/db.py` pins it too.
2. **No circular dep to invert** (unlike universe): the only `equity → sym` code import was
   `returns/loader.py`'s `current_calendar_version` — inlined as a 1-line query reading the injected
   sym_conn. equity is now sym-import-free (guard clean); engine entry points take `(equity_conn,
   sym_conn)` (fx's restate pattern). One-way `sym → equity`.
3. **Index facts stay in sym** (deliberate scope): index_levels/fact_index_returns/fact_index_extremes/
   universe_benchmark ride the `sym_id` bridge; `return_window` is duplicated (master in sym for the
   index facts, seeded copy in equity for fact_returns) — 28 static rows.
4. **Latent universe-extraction bug fixed in passing**: `optimiser._select_names` did a
   `securities × universe_membership` single-query join on the sym conn — broken since the universe
   extraction dropped universe_membership from sym. Rewritten as roster-fetch (universe + sym caps).
5. **API gateway single-query cross-DB joins split** (universe_coverage, heatmap, securities
   gap-filters + enrichment) into per-DB reads + Python merge on composite_figi. Single-figi reads
   (security_detail/prices) + the data_monitor + analytics/portfolios just route the moved-table
   reads to an injected/lazy equity connection. live_heatmap is sym-only (live quotes).

### Phase status (2026-06-25)
- [x] **P1 — Scaffold + equity DB** (commit): package + own `equity` DB, Sqitch trio (equity_schema +
  seed_reference: currency + return_window), deploy_all registry, workspace + sym dep. Created+deployed.
- [x] **P2 — Move the engine** (commit): returns/ingest/sources → equity; inlined calendar query;
  `(equity_conn, sym_conn)` threading; 112 equity tests green; sym-import-free.
- [x] **P3 — Rewire sym orchestration/consumers** (commit): cli/eod/universe-ingest/fundamentals/
  marketcap/restate/validate cross-DB; 529 sym tests green.
- [x] **P4a/b/c — Rewire external consumers** (commits): backtest/signals/optimiser/lineage (39/14/21
  green); analytics/portfolios gateways; api sym gateway (all 5 join methods) + router + data_monitor +
  sym_contract. Syntax/import-clean.
- [x] **P5 — Migrate data** (commit): all 8 tables COPY'd sym→equity (prices_raw 13.5M, fact_returns
  15.9M, corporate_actions 128k, price_gaps, prices_review, backfill_progress, run_log, extremes);
  counts verified == sym; run_id identity advanced. (Streaming binary COPY; the first in-memory-buffer
  attempt was too slow — switched to chunk-by-chunk streaming.)
- [x] **P6 — Verify** (commit): every api test fixture updated for the cross-DB query shapes; full
  suites green (equity 112, sym 529, backtest 39, signals 14, optimiser 21, api 175); deploy_all
  --status clean; lineage.definitions loads. LIVE end-to-end (real DBs, no fakes): all api gateway
  cross-DB methods + backtest + analytics + portfolio returns + sym validate PASS.
- [x] **P7 — Drop from sym** (commit): sym:equity_extract migration dropped the 9 objects (deployed +
  verified via Docker sqitch; faithful revert; 12 stale create-verify scripts no-op'd). AC#3 met. The
  drop surfaced + I fixed **two fail-loud misses** the live verify hadn't exercised: validate/fx.py
  check_fx_coverage (priced set now roster-fetched from equity) and test_accuracy / the SM-6 gate (now
  reads fact_returns from equity — runs + passes). Post-drop: moved tables absent from sym, all suites +
  live verify + SM-6 accuracy harness green; the 2 validate fails are PRE-EXISTING data gaps (13
  incomplete / 9 unpriced), not regressions.

### Completion Notes
Equity is now a full peer package with its own `equity` database; one-way `sym → equity` (import-guard
clean — equity imports nothing from sym). All ACs met. The single-query cross-DB joins in the API
gateway (universe_coverage / heatmap / securities gap+enrichment / attention) + analytics' live-pivot
were split into per-DB reads + Python merge on composite_figi (no cross-DB join anywhere). Index facts
(index_levels/fact_index_returns/fact_index_extremes/universe_benchmark) + return_window + fundamentals
deliberately STAY in sym (sym_id-bridge / benchmark plumbing). ~30M rows migrated; sym's copies dropped.
Index extraction is the documented follow-up.

## Change Log
- 2026-06-25: Story created + implemented across 7 phases on feat/equity-package (commits): P1 scaffold +
  equity DB; P2 move engine (sym-import-free, (equity_conn, sym_conn) threading); P3 rewire sym
  orchestration/consumers + validate cross-DB; P4a/b/c rewire backtest/signals/optimiser/lineage +
  analytics/portfolios + api gateway/data_monitor/operate/contract; P5 migrate data; P6 verify (suites +
  live); P7 drop from sym + fix two fail-loud misses. All ACs met; green; live-verified. Status → review.
