# Story: Extract `fx` into its own peer package WITH its own database

Status: done

<!-- Created via bmad-create-story 2026-06-24 (Andre: "I want to do that also for fx, so factor that
in" — sibling to universe-package.md). Same destination as universe: a full peer package like
rates/commodities/macro/altdata with its own `fx` database under the DB-per-package + DuckDB-federation
topology (project_db_topology_direction), library-first (project_qrp_structure_target,
sym_is_peer_not_hub). BUT fx is the SIMPLER of the two extractions: the Explore map (2026-06-24) found
**no inbound FKs** to `fx_rate` and **fx is read-only from sym** (restate.py reads prices/securities/
fact_returns, never writes). So — unlike universe — there is NO circular write-dependency and NO
dependency-inversion knot. fx's only hard parts are (a) the `fx_rate → currency` FK across a DB
boundary, and (b) routing the thin read-resolvers (`fx_rate()`, `convert()`) + the one set-based
market-cap join at the fx DB. Read Dev Notes before touching anything. Sibling story: universe-package.md. -->

## Story

As the QRP maintainer,
I want the FX (USD-base foreign-exchange rates) subsystem extracted from `sym` into its own `fx` peer
package **with its own database** (like rates/commodities),
so that FX is a fully independent bounded context under the DB-per-package topology — without breaking
currency conversion, the EOD `market_cap_usd` recompute, or the API FX matrix.

## Scope

- **NEW `packages/fx/`** peer package — own `pyproject.toml`, `src/fx/`, workspace member, **own `fx`
  Postgres database** (own `db.py` resolving the `fx` DB via PG* env, own `db/` Sqitch project
  registered in `tools/deploy_all.py`), library-first. Models rates/commodities.
- **Move the FX domain** out of sym: the 10 `sym/fx/*` modules (model, source, convention, resolve,
  convert, ingest, review, reconcile, restate, `__init__`) + `sym/validate/fx.py` → the package; the
  `sym fx` CLI → `fx` CLI (`fx load`/`review`/`coverage`/`divergence`/`convert`/`px`/`returns`/`mcap`
  — house verbs, project_loader_vocabulary; `load` already the verb, feedback minimize churn).
- **Move the FX tables/views/function to the `fx` database** (migrations move from sym's Sqitch project
  to the fx package's) — see the per-object call-outs in Dev Notes (the `currency` reference table is
  the one knot).
- **Route every sym→fx read at the fx DB** via the package read API — the thin resolvers (`fx_rate()`,
  `convert()`) take an fx connection; the one set-based `recompute_market_cap_usd` join becomes a small
  **rate-map fetch** (currency→rate for the date, ~28 rows) applied locally. NO giant cross-DB joins.
- **`restate.py` stays a consumer primitive but moves with fx**: it reads sym's `v_prices_adjusted`/
  `securities`/`fact_returns` (read-only), so post-split it needs BOTH a sym connection (prices/returns)
  and the fx rate-fetch — see Dev Notes. This is the one place fx reads sym data.

## Acceptance criteria

1. `packages/fx/` is a workspace member with its **own `fx` database**: `db.py` → `fx` DB; a Sqitch
   `db/{deploy,revert,verify}` trio for the moved objects + plan; registered in `tools/deploy_all.py`;
   `deploy_all --status` clean; `uv sync --all-packages` succeeds. The `fx` DB is created + deployed via
   the house Docker-sqitch method (reference_sqitch_deploy_docker).
2. **`fx` imports nothing from `sym` at module load** (guard test/grep). The dependency edge is one-way
   **`sym` depends on `fx`** (sym calls `fx.convert`/`fx_rate`/`recompute_market_cap_usd`), never the
   reverse. `restate.py`'s sym-table reads are done through an **injected/explicit sym connection**, not
   a `sym` import (Dev Notes) — so fx the package stays sym-import-free.
3. The FX objects live in the **`fx` database**, not sym — no `fx_*` tables/views remain in the sym DB.
   No data is lost (migrate the existing `fx_rate` + `fx_rate_review` rows, or re-run `fx load` to
   repopulate — operator's call, documented). `fx_rate` is **immutable per (base, quote, date, source)**
   — preserve that invariant across the move.
4. **The `currency` FK is resolved cleanly.** `fx_rate.base_currency`/`quote_currency` today FK
   `currency(code)` in the sym DB; a cross-DB FK is impossible in Postgres. Decision (Dev Notes):
   **seed a `currency` reference table in the fx DB** (small, slow-moving ISO list) and keep the FK
   intact same-DB — do NOT drop to a soft reference unless the dev finds seeding impractical, in which
   case document the soft-reference fallback. `currency` is reference data, so duplicating the small
   table per package is acceptable (it is NOT operational fact data).
5. **No big cross-DB join anywhere.** The `recompute_market_cap_usd` set-based `LEFT JOIN fx_rate`
   becomes: fetch the **rate map** (USD-base rate per currency for the as-of date — tens of rows) from
   the fx DB, then update `fundamentals.market_cap_usd` in the sym DB using that map. Verify no
   per-row cross-DB chatter and no large join.
6. **Every existing behavior preserved, verified end-to-end:**
   - `fx load` (daily forward-fill + backfill, immutable insert, plausibility band → review queue) and
     `fx review` (accept inserts into `fx_rate`; reject/superseded close) work against the fx DB.
   - the EOD `fx` step (`sym eod --steps …,fx`) loads rates into the fx DB **then** recomputes
     `fundamentals.market_cap_usd` in the sym DB via the rate-map fetch — same nightly outcome.
   - `fx convert` / `fx px` / `fx returns` / `fx mcap` give identical results (triangulate through USD;
     `restate` reads sym prices via the sym conn + rates via the fx conn).
   - `fx coverage` / `fx divergence` still pass (coverage cross-checks sym `securities`/`prices_raw`
     currencies against fx rates — now cross-DB: fetch priced currencies from sym, assert fx covers them).
   - the **API FX matrix** (`fx_matrix_eod` / `fx_matrix_live` in `services/api`) reads rates from the
     fx DB (open it read-only like rates/commodities), overlays live Yahoo quotes unchanged.
   - the Data Monitor `fx`/`fx_load` bucket freshness reads the fx DB's `fx_rate.as_of_date`; the
     lineage `fx_rate` asset + the `fundamentals`-depends-on-`fx_rate` column lineage still resolve.
7. Suites green (sym, api+lineage, the new fx package), ruff clean, `lineage.definitions` loads.

## Developer context — READ THIS FIRST

This is a **brownfield extraction into its own database**, but a **markedly cleaner one than universe**.
The Explore map (2026-06-24) confirmed the asymmetry that makes fx easy:

- **No inbound FKs to `fx_rate`** — no sym table references it as a constraint. The integration is
  purely read-side SQL JOINs in consumers. Nothing blocks the table move except the *outbound* FK to
  `currency` (AC#4).
- **fx never writes a sym table.** `restate.py` reads `v_prices_adjusted`/`securities`/`fact_returns`
  SELECT-only; `ingest.py`/`review.py` write ONLY `fx_rate`/`fx_rate_review`. So the write-direction is
  strictly one-way: **sym writes prices → fx reads them → sym reads fx rates via `convert()`.**

### ✅ No circular dependency to invert (unlike universe)
universe needed a Resolver-protocol inversion because it *imports* `sym.identity` while sym imports it.
fx has **no such cycle**: fx's only sym dependency is data reads in `restate.py`, and those go through a
**passed-in sym connection** (the caller already holds one). So:
- `fx` the package imports nothing from sym. `restate.price_in_currency(sym_conn, fx_conn, figi, …)` /
  `returns_in_currency(sym_conn, fx_conn, …)` take both connections explicitly (or a tiny read-port
  the caller supplies). No `Resolver` protocol, no adapter, no injection ceremony — just thread the two
  connections that already exist at the call sites.
- `sym` depends on `fx` (its marketcap/eod/fundamentals code calls `fx.convert` / `fx.fx_rate` /
  `fx.recompute_market_cap_usd`). One-way `sym → fx`. AC#2.

### 🚦 Knot 1 — the `currency` FK across the DB boundary (AC#4)
`fx_rate(base_currency, quote_currency)` FK `currency(code)` in the sym DB. Cross-DB FKs don't exist in
Postgres. `currency` is **reference data** (small ISO-ish list, slow-moving) — so the clean answer is to
**seed a `currency` table in the fx DB** and keep the FK intact within the fx DB. Duplicating reference
data per package is fine (it is not operational fact data and does not drift independently in a way that
matters). The `fx_rate_review` table has **no FK to `fx_rate`** (quote_currency is plain TEXT there), so
it moves freely. Fallback if seeding proves awkward: drop the FK to a soft reference + document it.

### 🚦 Knot 2 — route the sym→fx reads at the fx DB (rate-fetch, not federation)
The fx rate set is tiny (≈28 currencies × dates), so — exactly like universe's roster-fetch — fetch the
small rate set, don't cross-DB-join. Per consumer:
- **`sym/marketcap.py` `market_cap()`** → calls `fx.convert(fx_conn, …)`; pass the fx connection.
- **`sym/universe/fundamentals.py` `recompute_market_cap_usd()`** (the one set-based `LEFT JOIN fx_rate`,
  line ~210) → fetch the **rate map** (`{currency: usd_rate}` for the as-of date, tens of rows) from the
  fx DB, then `UPDATE fundamentals.market_cap_usd` in the sym DB from that map. AC#5. This is the only
  place that was a real join; everything else already goes through the `fx_rate()`/`convert()` resolvers.
- **`sym/eod.py` `fx` step** → `fx.load` into the fx DB, then `recompute_market_cap_usd` (rate-map) into
  sym. Holds both connections; each write to its own DB. Non-critical step (stays non-critical).
- **`sym/fx/restate.py`** → `price_in_currency`/`returns_in_currency` take (sym_conn, fx_conn): prices/
  returns/securities from sym, rates from fx.
- **`sym/validate/fx.py` `check_fx_coverage()`** → cross-DB: read priced non-USD currencies from sym
  (`securities`/`prices_raw`), assert the fx DB resolves a non-stale USD rate for each. Mind the
  `feedback_db_validation_rollback` gotcha if tests touch real rows.
- **`services/api` `fx_matrix_eod` / `fx_matrix_live`** (gateway.py ~1251–1379) → open the fx DB
  read-only (the Data Monitor gateway already opens rates/commodities DBs this way) and resolve rates
  from it; `conventional_pair`/`quote_rank` move to the fx package (pure logic). Live overlay (Yahoo)
  unchanged.
- **`packages/rates/src/rates/ingest.py`** reads fx — confirm why (likely a USD conversion of a foreign
  curve input) and repoint it to the fx DB read API. Small, but don't miss it.
- **`packages/lineage`** → the `fx`/`fx_load` bucket Dataset moves to `package="fx", table="fx_rate"`
  (the Data Monitor reads the fx DB like it reads rates/commodities); the `fx_rate` asset + the
  `fundamentals`←`fx_rate` column-lineage edge stay (now crossing package DBs). Job name `fx_load` +
  the data-monitor bucket key `fx` stay.

### Objects — where each lands
Move to the **`fx`** DB: tables `fx_rate`, `fx_rate_review`; views `v_fx`, `v_fx_daily` (+ the
precedence rewrite); function `fx_source_rank(text)`. Seed a **`currency`** reference table in the fx DB
(AC#4) so `fx_rate`'s FK stays intact. **Nothing FX-related stays in sym** (contrast universe, where
`universe_benchmark` had to stay). `fundamentals.market_cap_usd` is a **sym** column fed by the fx
rate-map — it stays in sym (it's sym fundamentals data), just sourced cross-DB.

### Invariants you must not break
- **`fx_rate` immutability** — immutable insert per (base, quote, as_of_date, source); ON CONFLICT DO
  NOTHING; the plausibility-band → `fx_rate_review` rejection-queue flow; source precedence
  (frankfurter:10 < ecb:20 < fawazahmed0:30) and `v_fx_daily`'s source-rank tiebreaker.
- **USD-base canonical storage** + triangulate-through-USD conversion (model.py / convention.py /
  convert.py) — pure logic, moves wholesale; keep the `fx fx divergence` 2nd-source check
  (project_fx_retro_followups: ECB SDMX 2nd source; TWD deep-history gap stays on fawazahmed0).
- **DB-per-package discipline** (project_db_topology_direction): no cross-DB FKs (hence AC#4); each
  package owns its DB; reads cross via the small rate-map fetch (or DuckDB federation for analytics),
  never operational joins.
- **as_of_date canonical naming** (feedback_as_of_date_canonical_name): `fx_rate.as_of_date` keeps the
  name; reconcile the whole chain if anything touches it.
- Sqitch via the house Docker method; schedules keep explicit tz.

## Relationship to the `universe` extraction (universe-package.md)
These are **sibling stories** in the same sym-decomposition program (fold sym into one peer among
equals). They share the topology (own DB + Sqitch trio + `deploy_all` + Data Monitor reads it as another
package DB + the small-fetch-not-join rule) but their hard parts differ: **universe** needs dependency
inversion for a true circular dep; **fx** does not (one-way read coupling). They are independent and can
land in either order; fx is the lower-risk one to do first. No shared files except the cross-cutting
wiring (`tools/deploy_all.py`, root + api `pyproject.toml`, `lineage`), so sequence to avoid churn but
no hard ordering dependency.

## Suggested phasing
1. **Scaffold** `packages/fx/` (pyproject, `db.py`→`fx` DB, `db/` Sqitch trio + plan for the moved
   objects, seed `currency`, deploy_all registry, empty `cli.py`); create + deploy the `fx` DB (Docker
   sqitch).
2. **Move the FX domain** (model, source, convention, resolve, convert, ingest, review, reconcile,
   restate, validate/fx) → the package; fx imports nothing from sym; `restate` takes (sym_conn, fx_conn).
3. **Migrate the data**: move `fx_rate` + `fx_rate_review` rows from the sym DB to the fx DB (dump/
   restore, or re-run `fx load` to repopulate — document the chosen path); drop the fx objects from sym.
4. **Rewire each consumer** at the fx DB (marketcap, the `recompute_market_cap_usd` rate-map, eod fx
   step, validate coverage, api fx matrix, rates ingest, lineage bucket/asset). Verify each — esp. AC#5.
5. **CLI** → `fx` (`fx load`/…); decide `sym fx` shim vs removal (mirror whatever universe-package does).
6. **Verify** the full AC#6 behavior matrix end-to-end + suites + `deploy_all --status`.

## Out of scope / Deferred
- **DuckDB federation** as the operational read mechanism — use the cheap rate-map fetch here.
- Moving the API FX matrix into its own `fx` router/module (cosmetic follow-up; logic moves now, the
  HTTP surface can stay in the sym/data_monitor module for this story).
- Renaming the `fx_load` Dagster job / `fx` data-monitor bucket key.

## Key files (inventory)
- NEW: `packages/fx/{pyproject.toml, src/fx/{db,cli,__init__}.py + moved modules}, db/{deploy,revert,
  verify}/*.sql + sqitch.{conf,plan} (incl. seeded `currency`), tests/…}`.
- MOVED-FROM sym: `packages/sym/src/sym/fx/*` (→ fx package; `restate.py` gains an explicit sym_conn),
  `packages/sym/src/sym/validate/fx.py` (→ fx, cross-DB coverage), the fx table/view/function migrations
  (→ fx package's Sqitch project), the fx test files (→ fx package; most are DB-free pure-logic).
- UPDATE (sym): `cli.py` (`fx` shim/removal; subcommand dispatch), `marketcap.py` (pass fx_conn),
  `universe/fundamentals.py` (`recompute_market_cap_usd` → rate-map fetch), `eod.py` (fx step across
  both DBs), `packages/sym/pyproject.toml` (+`fx` dep).
- UPDATE (consumers → fx DB): `services/api/...gateway.py` (`fx_matrix_eod`/`fx_matrix_live`,
  `conventional_pair`/`quote_rank` → fx pkg), `packages/rates/src/rates/ingest.py`, the lineage `fx`/
  `fx_load` bucket Dataset + the `fx_rate` asset / `fundamentals`←`fx_rate` lineage edge.
- UPDATE (wiring): root `pyproject.toml`, `services/api/pyproject.toml`, `tools/deploy_all.py` (+fx DB).

## Dev Agent Record

### Key architecture decisions / deviations (recorded during dev, 2026-06-24)
Mapping the code precisely (Explore + direct reads) refined the story's literal module placement.
The deviations below all serve the story's load-bearing AC#2 (fx imports nothing from sym → one-way
`sym → fx`) and the prime directive (preserve behavior end-to-end):

1. **The fx PACKAGE = the sym-import-free FX *engine* only**: `model`, `convention`, `source`,
   `resolve`, `convert`, `ingest`, `review`, `reconcile`, `__init__`, plus `db.py` + `cli.py`. These
   touch only the fx DB (`fx.*` schema) + `fx.currency`; none import sym.
2. **`restate.py`, `validate/fx.py`, `marketcap.py`, `recompute_market_cap_usd` STAY in sym** (the
   story listed restate/validate as "moved"). Reason: `restate.py` imports `sym.returns.windows` +
   `sym.returns.loader` and all four read sym tables (`securities`/`v_prices_adjusted`/`fact_returns`/
   `fundamentals`). Moving them would force `fx → sym`, breaking AC#2 and re-introducing the cycle. They
   become sym-side *consumers* that call into the `fx` package with an explicit fx connection. Net
   effect = identical behavior + the one-way edge the story wants.
3. **`sym fx` CLI retained, behavior-identical, rewired cross-DB** (opens an fx conn alongside the sym
   conn); a NEW standalone `fx.cli` (`[project.scripts] fx`) provides the FX-DB-only verbs
   `load`/`review`/`divergence`/`convert`. Full `sym fx` removal is **deferred** (cosmetic; `sym fx`
   is also the `market_cap_usd` recompute trigger and hosts the sym-data consumer verbs px/returns/
   mcap/coverage). The lineage `fx` bucket keeps shelling `sym fx load` so the nightly load **and**
   market-cap recompute are preserved with zero lineage churn. (Story's "decide shim vs removal" +
   "Out of scope: cosmetic CLI"). 
4. **`rates` needs NO rewiring** — the apparent `rates/ingest.py` fx reference is a docstring comment
   ("Mirrors `sym.fx.ingest.fill_fx`") only; no code dependency. (Docstring updated cosmetically.)
5. **`recompute_market_cap_usd` cross-DB via a sym-side TEMP table**: its set-based `LEFT JOIN LATERAL
   fx_rate` is per-row/per-date (each fundamentals row needs the rate as-of ITS date), so a single
   latest-rate map is insufficient. Faithful impl: fetch the needed USD-base rows from the fx DB for
   the currencies present in fundamentals, COPY them into a sym TEMP table, run the IDENTICAL LATERAL
   UPDATE locally. No cross-DB join; exact semantics preserved (the "rate-fetch, not join" spirit).
6. **Schema `fx`** (matches the rates/commodities house convention) with table/view/function names
   preserved (`fx.fx_rate`, `fx.fx_rate_review`, `fx.v_fx`, `fx.v_fx_daily`, `fx.fx_source_rank`);
   `fx.currency` seeded (incl. a local `set_updated_at` trigger fn) to keep `fx_rate`'s FK intact
   same-DB (AC#4 — seed, not soft-reference).
7. **Sequencing for safety**: the destructive "drop fx objects from the sym DB" runs LAST, after the
   data is copied to the fx DB (counts verified) and all consumers are rewired + tests green — so an
   interruption leaves sym intact, not half-migrated.

### Tasks / Subtasks
- [x] **P1 — Scaffold + fx DB**: `packages/fx/` (pyproject, `src/fx/`, `db.py`, `cli.py`); `db/` Sqitch
  trio+plan (single `fx_schema` migration) creating `currency`(+trigger), `fx_rate`,
  `fx_rate_review`(superseded folded in), `v_fx`/`v_fx_daily`(precedence), `fx_source_rank` in schema
  `fx`; registered in `tools/deploy_all.py`; added to root workspace + sym/api deps +
  `[tool.uv.sources]`; `uv sync --all-packages` ✓; fx DB created + deployed + verified (Docker sqitch).
- [x] **P2 — Move FX engine**: moved 9 modules → `packages/fx/src/fx/`; imports `sym.fx.*`→`fx.*`; SQL
  schema-qualified to `fx.*`; 7 pure tests → `packages/fx/tests/`; fx import-guard passes (no sym import).
- [x] **P3 — Rewire sym consumers**: `market_cap(conn, fx_conn, …)`; `restate.{price,returns}_in_currency
  (conn, fx_conn, …)`; `check_fx_coverage(conn, fx_conn)`; `recompute_market_cap_usd(conn, fx_conn)`
  (sym-side TEMP table, identical LATERAL); `eod.py` fx step + `cli._cmd_fx` + `sym fundamentals` open
  an fx conn; validate runner opens fx conn in the isolated fx_coverage lambda; sym pyproject +`fx`.
- [x] **P4 — Rewire api + lineage**: gateway `fx_matrix`/`fx_matrix_live` read the fx DB via an injected
  `fx_conn` (route `_gateway` opens both; lazy-open fallback); `from fx.convention`/`fx.resolve`; api
  pyproject +`fx`; `lineage/buckets.py` fx Dataset `package="fx"`/`fx.fx_rate`; `assets.py` fx_rate
  asset db-label→fx; standalone `fx.cli` (load/review/divergence/convert). rates needed NO rewire
  (docstring-only ref, updated).
- [x] **P5 — Migrate data**: seeded `fx.currency` (32); COPY `fx_rate` (388,075) + `fx_rate_review` (3)
  sym→fx (streamed binary COPY); counts verified == sym.
- [x] **P6 — Verify**: fx 47 / sym 794 / lineage+api 215 suites green; ruff clean (my changes);
  `deploy_all --status` clean (fx + sym up to date); `lineage.definitions` loads; fx import-guard clean;
  live behavior matrix all OK (fx convert/review, cross-DB coverage, gateway FX matrix, cross-DB
  market_cap + recompute temp-table, Data Monitor fx bucket reads the fx DB = 28 pairs).
- [x] **P7 — Drop fx from sym DB**: sym `fx_extract` migration (deploy drops fx_rate/fx_rate_review/
  v_fx/v_fx_daily/fx_source_rank; `currency` stays — 4 other tables FK it; revert recreates the schema
  faithfully). Deployed via Docker sqitch; the 6 stale fx-create verify scripts no-op'd (objects moved).
  sym deploy+verify clean; suites + live behavior re-confirmed.

### File List
**NEW (fx package):** `packages/fx/pyproject.toml`, `packages/fx/src/fx/{db,cli}.py`,
`packages/fx/db/{sqitch.conf,sqitch.plan,deploy/fx_schema.sql,revert/fx_schema.sql,verify/fx_schema.sql}`.
**MOVED sym→fx (git mv):** `src/fx/{__init__,model,convention,source,resolve,convert,ingest,review,
reconcile}.py`; `tests/test_fx_{convention,convert,ingest,model,reconcile,resolve,source}.py`.
**NEW (sym migration):** `packages/sym/migrations/{deploy,revert,verify}/fx_extract.sql`.
**MODIFIED (sym):** `pyproject.toml`, `src/sym/cli.py`, `src/sym/eod.py`, `src/sym/marketcap.py`,
`src/sym/fx/restate.py`, `src/sym/universe/fundamentals.py`, `src/sym/validate/fx.py`,
`src/sym/validate/runner.py`, `migrations/sqitch.plan`, `migrations/verify/fx_{rate,views,source_rank,
views_precedence,rate_review,rate_review_superseded}.sql` (no-op'd), `benchmark/validate_fx_restatement.py`,
`tests/test_{durable_reviews,fx_coverage,marketcap}.py`.
**MODIFIED (api):** `services/api/pyproject.toml`, `modules/sym/{gateway,router}.py`,
`tests/test_{fx_matrix_route,data_monitor_eod}.py`.
**MODIFIED (lineage/root/tools):** `packages/lineage/src/lineage/{buckets,assets}.py`,
`packages/rates/src/rates/ingest.py` (docstring), `pyproject.toml`, `tools/deploy_all.py`, `uv.lock`.

### Review Findings (bmad-code-review 2026-06-24 — 3 adversarial layers)
- [x] [Review][Patch] fx.currency never seeded by the fx migration → a fresh `deploy_all` builds an
  empty `fx.currency`, so `fx_rate`'s FK rejects every insert and `_default_currencies` returns []
  (the live DB was seeded by the one-off migration script, but the migration wasn't self-contained)
  [packages/fx/db/deploy/fx_schema.sql] — FIXED: added `fx:seed_currency` migration (idempotent ISO
  seed, ON CONFLICT DO NOTHING; deployed + verified).
- [x] [Review][Defer] `sym:fx_extract` drops fx data with no in-migration copy-verification guard
  [packages/sym/migrations/deploy/fx_extract.sql] — deferred: the one-time live migration was done
  copy→verify-counts→drop (safe); fresh rebuilds have no data to lose; re-runs are no-ops.
- [x] [Review][Defer] No cross-DB reconciliation between `fx.currency` and `sym.currency` (a new sym
  currency won't exist in fx → `fx load` FK-fails / market_cap_usd silently NULLs) — deferred: add a
  validate check or auto-seed unknown currencies on `fx load`.
- [x] [Review][Defer] API FX-matrix raises a raw 500 (not a graceful 503) if the fx DB is unreachable
  [services/api/.../gateway.py _fx()] — deferred: low; matches most endpoints' DB-down behavior.
- [x] [Review][Defer] Data Monitor fx-bucket degrade-path lost test coverage (the boom test moved to
  `equity_prices`; no fx-DB-failure test added) [services/api/tests/test_data_monitor_eod.py] —
  deferred: add an fx-DB-unreachable degrade test.
- [x] [Review][Defer] `sym fundamentals` / `sym fx` open the fx conn unconditionally → now hard-depend
  on fx-DB availability even for paths that barely use it [packages/sym/src/sym/cli.py] — deferred:
  minor robustness (recompute needs fx anyway).
- [x] [Review][Defer] `recompute_market_cap_usd` uses a fixed TEMP-table name `_fx_rate_tmp` → a
  concurrent recompute reusing one sym conn could collide [packages/sym/src/sym/universe/fundamentals.py]
  — deferred: single-threaded EOD makes this very low-probability; DROP-first guards crashed runs.

_Dismissed as noise/false-positive (verified): "source-precedence regression" in recompute (the
ORIGINAL LATERAL also lacked `fx_source_rank` — identical, faithfully preserved); "autocommit forced on
borrowed conn" (pre-existing — original set it too); CHAR(3)/text padding (pre-existing join semantics);
`FX_DB_NAME` vs `FX_DATABASE_URL` override (verbatim the rates/commodities house pattern); connection-
cleanup style inconsistency (no actual leak found); `set_updated_at` trigger "dead weight" (harmless,
matches sym); psycopg floor skew (lockfile reconciles); `=ANY` CHAR(3) cast (not the NUMERIC float8
trap; ~30-row nightly fetch)._

### Completion Notes
FX is now a full peer package with its own `fx` database. The one-way `sym → fx` dependency holds (fx
imports nothing from sym; import-guard enforced). All 7 deviations from the literal story (see above) were
in service of AC#2 (no circular dep) and behavior preservation; net behavior is identical, verified by the
live cross-DB matrix. The `recompute_market_cap_usd` temp-table path is byte-for-byte equivalent (re-run
= 0 rows changed, 218,011 non-USD market_cap_usd values preserved). 388,075 fx_rate rows migrated; sym's
copies dropped. Suites: fx 47, sym 794, lineage+api 215, all green.

## Change Log
- 2026-06-24: Story created (approach B). Dev: built the fx package + DB, moved the FX engine, rewired
  all consumers cross-DB (roster/rate-fetch + temp-table, no cross-DB joins), migrated the data, dropped
  the fx objects from the sym DB. All ACs met; suites green; live behavior verified. Status → review.

## Verification
- fx import-guard (no `sym` import at module load); `deploy_all --status` clean incl. the new `fx` DB.
- AC#6 behavior matrix live; sym + api + lineage + fx suites green; ruff clean; `lineage.definitions`
  loads.
- Confirm AC#5 in `recompute_market_cap_usd`: rate-map fetched from the fx DB, no large cross-DB join.
- Web/UI (the FX matrix page + Data Monitor `fx` bucket) via the running console (toolchain caveat —
  CDP/inspection, feedback_minimize_dev_churn / feedback_scale_verification_to_change).
- Cross-cutting refactor: land on a branch; code-review adversarially on (a) the one-way `sym → fx`
  dependency + fx staying sym-import-free, (b) behavior preservation (conversion / market_cap_usd / FX
  matrix), (c) the `currency`-FK decision + the rate-map-not-join rule, before merge.
