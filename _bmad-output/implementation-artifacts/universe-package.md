# Story: Extract `universe` into its own peer package WITH its own database

Status: done  <!-- P1-P4 done + code-reviewed (6a64a39) + merged to main (b872f1d). Follow-up hotfix fix/sym-router-lazy-conns (2c3b834: lazy fx/universe conns in the sym router so a sibling-DB fault no longer 500s all /api/sym/*) merged to main de41779; 175 API tests green. Extraction arc closed. -->>

<!-- Created via bmad-create-story 2026-06-24 (Andre: "feels like universe should be a separate
package" → "do it" → "change also to separate database"). FINAL DECISION: approach **B** — a full
peer package like rates/commodities/macro/altdata: own `universe` database under the DB-per-package +
DuckDB-federation topology (project_db_topology_direction), library-first (project_qrp_structure_target,
sym_is_peer_not_hub). This is LARGER than the shared-DB variant: the universe_* tables LEAVE the sym
database, so every operational read of membership (sym price load, EOD monitor, backtest, signals,
validate, data-monitor) becomes cross-database. universe is the FIRST package whose data must be
*joined operationally* with sym (membership × prices/returns) — earlier peers (rates/commodities) are
read in isolation. Read the Dev Notes fully before touching anything; this needs phasing + adversarial
review. -->

## Story

As the QRP maintainer,
I want the universe/membership subsystem extracted from `sym` into its own `universe` peer package
**with its own database** (like rates/commodities),
so that universe is a fully independent bounded context under the DB-per-package topology — without
breaking the membership-drives-ingestion coupling the daily pipeline relies on.

## Scope

- **NEW `packages/universe/`** peer package — own `pyproject.toml`, `src/universe/`, workspace member,
  **own `universe` Postgres database** (own `db.py` resolving the `universe` DB via PG* env, own
  `db/` Sqitch project registered in `tools/deploy_all.py`), library-first. Models rates/commodities.
- **Move the universe domain** out of sym: the 24 `sym/universe/*` modules (registry, events,
  projection, query, resolution-as-protocol, monitor, gating, accuracy, review, snapshot,
  membership_diff, fundamentals, providers/*) → the package; the `universe` CLI → `universe.cli`
  (`universe load`/`refresh`/`monitor`/… house verbs, project_loader_vocabulary).
- **Move the universe tables to the `universe` database** (the migrations move from sym's project to
  the universe package's Sqitch project) — see the per-table call-outs in Dev Notes (one table stays).
- **Break the package-level circular dependency** via dependency inversion (the same Resolver pattern
  as the shared-DB plan — orthogonal to the DB split, still required).
- **Make every cross-DB membership read work via the roster-fetch pattern** (small roster from the
  universe DB → filter sym data by it), preserving all behavior end-to-end. NO giant cross-DB joins.

## Acceptance criteria

1. `packages/universe/` is a workspace member with its **own `universe` database**: `db.py` →
   `universe` DB; a Sqitch `db/{deploy,revert,verify}` trio for the moved tables + plan; registered in
   `tools/deploy_all.py`; `deploy_all --status` clean; `uv sync --all-packages` succeeds. The
   `universe` DB is created + deployed via the house Docker-sqitch method.
2. **`universe` imports nothing from `sym`** (guard test/grep). One-way dependency: **`sym` depends on
   `universe`**, never the reverse — via the injected `Resolver` (Dev Notes).
3. The universe tables live in the **`universe` database**, not sym — no `universe_*` tables remain in
   the sym DB (except `universe_benchmark`, which stays in sym; see Dev Notes). No data is lost
   (migrate/re-derive the existing rows, or re-run refresh to repopulate — operator's call, documented).
4. **No big cross-DB join anywhere.** Every consumer that needs membership fetches the **roster**
   (the small list of `composite_figi` for a universe as-of a date — hundreds of rows) from the
   `universe` DB via the universe package's read API, then filters sym data by that list locally. This
   is the load-bearing design rule — verify it in each consumer.
5. **Every existing behavior preserved, verified end-to-end:**
   - `sym load --scope universe:<id>` loads exactly the same members with the same per-member end-caps
     (the `universe_reload_no_gaps` invariant — leavers included — MUST hold), now sourcing the roster
     + end-caps from the universe DB.
   - the EOD `monitor` step discovers → stages → promotes → re-resolves (via the injected sym resolver)
     → re-projects, writing membership to the universe DB.
   - `backtest` / `signals` get the same point-in-time rosters (fetched from universe, applied to sym).
   - `sym validate` universe completeness/accuracy still pass (cross-DB roster vs sym prices).
   - the API universe explorer, the Data Monitor per-universe coverage + the `universe_load` bucket
     freshness, and the lineage asset graph still work — the Data Monitor reads the `universe` DB as
     another package DB (it already reads rates/commodities DBs independently).
6. Suites green (sym, api+lineage, the new universe package), ruff clean, `lineage.definitions` loads.

## Developer context — READ THIS FIRST

This is a **brownfield extraction of a deeply-wired subsystem into its own database**. Two hard knots:
the **dependency direction** (code) and the **cross-DB reads** (data). The Explore map (2026-06-24)
found universe *conceptually separable but operationally entangled*, and universe reads MORE from sym
(identity/`securities`/`exchange`) than sym reads from it (just membership).

### 🚨 Knot 1 — the circular dependency (code) → invert it
Today, in one package: **universe → sym** (token resolution calls `sym.identity.figi.plan_resolutions`
+ `symbology.write_security`; reads `securities`/`exchange`) and **sym → universe** (`sym load --scope
universe:` + the EOD monitor read `universe_membership` to shape the load + apply changes). A package
that imports sym while sym imports it is a circular workspace dependency — uv will reject it.

**Invert so the edge is one-way `sym → universe`:**
- `universe` owns pure membership/provider/projection/query logic, imports **nothing** from sym, and
  defines a **`Resolver` protocol** (`resolve(tokens) -> {token: composite_figi}` + an
  `ensure_security(figi, …)` hook) instead of calling `sym.identity`.
- `sym` provides the `Resolver` impl (adapter over `sym.identity.figi` + `symbology.write_security`,
  writing securities into the **sym** DB) and **injects** it into universe's refresh/monitor entry
  points. sym keeps the universe-driven price-load orchestration (it loads into sym's `prices_raw`).
- Net: `sym → universe` only. AC#2.

### 🚨 Knot 2 — the database split (data) → roster-fetch, not federation joins
The universe_* tables move to the `universe` DB, so the operational reads cross DBs. **The mechanism is
NOT a giant cross-database join** — it's: *membership rosters are tiny* (a universe as-of a date is a
few hundred `composite_figi`). So:
- `universe` exposes a read API, e.g. `members_as_of(universe_id, date) -> list[composite_figi]` (+
  end-caps `valid_to` per member, + the richer coverage/explorer queries), connecting to the universe DB.
- Each sym-side / consumer path **fetches the small roster from the universe DB, then filters sym data
  by that list** (an `IN`/`= ANY` against sym's prices/fact_returns). No 13M-row cross-DB join.
- This is exactly AC#4. DuckDB federation (project_db_topology_direction) is the *analytical/ad-hoc*
  cross-DB story; the operational paths here use the cheap roster-fetch instead — call this out so the
  dev doesn't reach for federation where a small list suffices. (Federation can be a later nicety.)

**Per-consumer cross-DB rewire:**
- `sym load --scope universe:<id>` / `sym/ingest`: get the member set + per-member end-caps from the
  universe DB (via the package API), then run sym's price load filtered to that roster. **Preserve
  `universe_reload_no_gaps`** — the end-caps for leavers come from the universe DB now.
- EOD `monitor` (`sym/eod.py`): orchestrated by sym; provider discovery + projection write to the
  universe DB (universe package), resolution via the injected sym Resolver (writes securities to sym).
  Holds both connections; each write goes to its own DB. Watch partial-failure ordering.
- `backtest/engine.py` `_members(...)`, `signals/compute.py` `_members(...)`: today direct
  `universe_membership` SQL on the sym conn — repoint to fetch the roster from the universe DB (open a
  universe connection / use the universe read API), then proceed against sym data. The signals asset
  spec input `sym:universe_membership` becomes `universe:universe_membership`.
- `sym/validate/*` completeness/accuracy: cross-DB — fetch current members from universe, assert sym
  prices cover them. Mind the `feedback_db_validation_rollback` gotcha if tests touch real rows.
- `services/api/modules/sym` explorer + `modules/data_monitor/eod.py` `_equity_universe_breakdown`:
  read membership from the universe DB. The Data Monitor EOD gateway already opens each package DB
  read-only (rates/commodities) — add `universe` the same way; the `universe`/`universe_load` bucket's
  freshness reads the universe DB's `membership_event`.
- `packages/lineage`: the `universe_load` bucket + `universe`/`equity`/`fundamental` discovery shell
  `sym universe …` → repoint to `universe …` (or keep a `sym universe` delegating shim). Bucket job
  name `universe_load` + the data-monitor key stay.

### Tables — where each lands
Move to the **`universe`** DB: `universe`, `membership_event`, `universe_membership`,
`universe_member_resolution`, `membership_proposal`, `universe_member_monitor_run_log`,
`universe_accuracy_check`.
**Stays in `sym`:** `universe_benchmark` — it FKs `instrument(sym_id)` (index-benchmark plumbing), and
a cross-DB FK is impossible in Postgres. Keep it + `sym/indices/links.py` in sym; its `universe_id`
column becomes a **soft reference** (no cross-DB FK) to the universe DB. (The `universe_membership` FK
to `universe`, and the other tables' FKs, all move together to the universe DB — intact, same-DB.)

### Invariants you must not break (same as before, now cross-DB)
- **`universe_reload_no_gaps`**: reload covers ALL point-in-time members incl. leavers; the per-member
  end-cap logic now sources `valid_to` from the universe DB — do not regress it.
- **`identity_key_decision`**: composite_figi (equities) + sym_id bridge stays whole in **sym**;
  membership is composite_figi-keyed (a string — crosses the DB boundary fine as a roster list).
- **SCD/projection** (project_sym_universe_layer, feedback_scd_same_day_inplace): valid_from/valid_to,
  same-day-SCD = update-in-place, event-log→projection rebuild — all move intact to the universe DB.
- **DB-per-package discipline** (project_db_topology_direction): no cross-DB FKs; each package owns its
  DB; reads cross via small roster lists (or DuckDB federation for analytics), never operational joins.
- Sqitch via the house Docker method (reference_sqitch_deploy_docker); schedules keep explicit tz.

## Suggested phasing
1. **Scaffold** `packages/universe/` (pyproject, `db.py`→`universe` DB, `db/` Sqitch trio + plan for the
   moved tables, deploy_all registry, empty `cli.py`); create + deploy the `universe` DB (Docker sqitch).
2. **Move the sym-free domain** (providers, events, projection, query, store, monitor, gating,
   accuracy, review, snapshot, membership_diff, fundamentals) + the `Resolver` protocol; adapt
   `resolution.py`. universe imports nothing from sym.
3. **Migrate the data**: move the 7 tables' rows from the sym DB to the universe DB (dump/restore, or
   re-run `universe refresh` to repopulate from providers — document the chosen path); drop them from
   sym (keep `universe_benchmark`).
4. **Invert the resolver** + wire sym's adapter; **rewire each cross-DB consumer** to roster-fetch
   (ingest, eod monitor, backtest, signals, validate, api, data_monitor, lineage). Verify each.
5. **CLI** → `universe.cli`; decide `sym universe` shim vs removal.
6. **Verify** the full AC#5 behavior matrix end-to-end + suites + `deploy_all --status`.

## Relationship to the `fx` extraction (fx-package.md)
Sibling story in the same sym-decomposition program (fold sym into one peer among equals). Both target
own-DB peer packages and share the topology (own DB + Sqitch trio + `deploy_all` + Data Monitor reads it
as another package DB + small-fetch-not-join). The hard parts differ: **universe** needs dependency
inversion (true circular dep); **fx** does not (one-way read coupling) and is the lower-risk one to do
first. Independent; no hard ordering dependency, but they share the cross-cutting wiring files
(`tools/deploy_all.py`, root + api `pyproject.toml`, `lineage`) — sequence to avoid churn.

## Out of scope / Deferred
- **DuckDB federation** as the operational read mechanism — use the cheap roster-fetch here; federation
  is for ad-hoc/analytical cross-DB queries (a later nicety, per the topology direction).
- Moving the API universe explorer to its own `universe` router/module (cosmetic follow-up).
- Renaming the `universe_load` Dagster job / data-monitor bucket key.

## Key files (inventory)
- NEW: `packages/universe/{pyproject.toml, src/universe/{db,cli,__init__}.py + moved modules +
  providers/}, db/{deploy,revert,verify}/*.sql + sqitch.{conf,plan}, tests/…}`.
- MOVED-FROM sym: `packages/sym/src/sym/universe/*` (→ universe package; `resolution.py` → Resolver
  protocol) and the universe table migrations (→ universe package's Sqitch project).
- UPDATE (sym): `cli.py` (`universe` shim/removal; `load --scope universe:` → roster-fetch), `ingest`,
  `eod.py` (monitor orchestration across both DBs), a new `universe_resolver` adapter,
  `packages/sym/pyproject.toml` (+`universe` dep), `sym/validate/*` (cross-DB), keep `indices/links.py`
  + `universe_benchmark` in sym.
- UPDATE (consumers → roster-fetch): `backtest/engine.py`, `signals/compute.py`,
  `services/api/modules/{sym,data_monitor}`, `packages/optimiser` (via backtest), the lineage
  `universe_load`/`equity`/`fundamental` bucket builders.
- UPDATE (wiring): root `pyproject.toml`, `services/api/pyproject.toml`, `tools/deploy_all.py`
  (+universe DB), `lineage` if the CLI path changes.

## Dev Agent Record

### Phase status (2026-06-24)
- [x] **P1 — Scaffold + universe DB (DONE, committed `72a8032` on `feat/universe-package`)**: `packages/
  universe/` (pyproject, db.py→`universe` DB, cli stub); Sqitch `universe_schema` migration recreating
  the 7 moved tables in schema `universe` (universe, membership_event, universe_member_resolution,
  universe_membership [GiST no-overlap + btree_gist], membership_proposal, universe_monitor_log,
  universe_accuracy_check) + `universe.set_updated_at`; registered in deploy_all + root workspace; DB
  created+deployed+verified. **Additive — nothing wired in yet, sym unchanged, zero behavior change.**
- [x] **P2 — Invert the circular dep + move the membership domain (DONE, committed `184cfb0`)**:
  13 modules + 8 providers moved to `packages/universe`; `Resolver` protocol (universe owns it) +
  `SymResolver` adapter (sym); monitor/refresh/accuracy/gating take the injected resolver; universe
  imports nothing from sym (guard clean); `universe.db` pins `search_path=universe`.
- [x] **P3 — Migrate data + rewire the CORE consumers (DONE, committed `184cfb0`)**: 7 tables copied
  sym→universe (counts verified; fixed 2 column drifts first_seen_date/as_of_date); rewired sym cli
  universe subcommands, eod monitor step, ingest price-load bridge (roster-fetch), backtest/signals
  `_members`. Topology contract updated (universe relations → peer reads). Suites green: universe 153,
  sym 641, backtest 39, signals 14, lineage+api 215; ruff clean.
- [x] **P4 — Cut over the READ-ONLY consumers + drop from sym (DONE, committed `5b119f2` + `ee50fa1`)**:
  rewired to the universe DB — `validate/{completeness,readiness}` (cross-DB roster-fetch; completeness
  writes `universe_member_completeness` in sym), `validate/{projection,plans}` + `referential_integrity`
  (universe seams) via the runner's `_with_universe` per-check conn; `api gateway` (universes/coverage/
  heatmap/live_heatmap/securities-universe-filter/proposals) via an injected universe conn (coverage +
  heatmap joins → roster-fetch + Python aggregation); `data_monitor` (bucket package=universe + the
  breakdowns); `indices/links` + `fundamentals.resolved_member_figis`; sym_contract relations moved to
  UNIVERSE_RELATIONS. THEN `sym:universe_extract` dropped the 7 tables (universe_benchmark +
  universe_member_completeness stay; their universe_id FK → soft ref); 8 stale verify scripts no-op'd;
  qrp_readonly grant now 13 relations. AC#3 met — no universe_* tables in sym.

### Completion Notes
Universe is now a full peer package with its own `universe` database; one-way `sym → universe` (import-
guard clean). All ACs met. Verified LIVE with the tables only in the universe DB: backtest _members(sp500)
=501, gateway universe_coverage + 633-cell heatmap, `sym validate` runs every universe check cross-DB
(referential/projection/readiness/maintenance/completeness — no crashes; the 2 remaining validate fails
are pre-existing DATA gaps — 13 incomplete members, 9 unpriced — not regressions), `sym universe members`.
deploy_all --status clean (sym + universe + fx). Suites: universe 153, sym 641, backtest 39, signals 14,
lineage+api 215; ruff clean. 7 documented deviations (resolver impl/ingest/fundamentals stay in sym as
the injected adapter; etc.) all serve AC#2 + behavior preservation.

## Change Log
- 2026-06-24/25: Story (approach B) implemented across 5 commits on feat/universe-package: P1 scaffold +
  universe DB (72a8032); P2 invert circular dep via Resolver + P3 migrate data + rewire core consumers
  (184cfb0); P4a read-only-consumer cutover (5b119f2); P4b drop the 7 tables from sym + cross-DB
  referential check (ee50fa1). All ACs met; suites green; live cross-DB verified. Status → review.
- 2026-06-25: code-reviewed (6a64a39, conn-leak + self-contained-revert patches), merged to main
  (b872f1d). Follow-up hotfix fix/sym-router-lazy-conns (2c3b834): the sym router's _gateway eagerly
  opened the fx + universe DBs for EVERY /api/sym/* request, so a sibling-DB outage/broken import 500'd
  ALL sym endpoints (incl. the FX matrix, seen live). Fixed to open only the core sym conn eagerly +
  let the gateway open fx/universe lazily per-method via _fx()/_universe(). 175 API tests green; merged
  to main (de41779). Status → done; extraction arc closed.

### Refined design from the coupling map (Explore, 2026-06-24) — READ BEFORE P2
The map CONFIRMS approach B and sharpens the module split. The inversion is deeper than "inject one
resolver": universe modules read **4 sym core tables** (securities, security_symbology, exchange,
trading_calendar), call the **sym ingestion pipeline** (`sym.ingest.pipeline.run_load`), and use the
**`SeedSecurity`** identity type. The split that keeps `universe` sym-import-free:

**MOVE to `packages/universe/src/universe/` (pure membership domain):** `registry`, `events`,
`projection`, `query`, `gating`, `membership_diff`, `store`, `snapshot`, `review`, `monitor`, `refresh`,
`accuracy`, the providers (`index_source`, `b3`, `etf_holdings`, `fmp`, `wikipedia`, `criteria`,
`index_provider`, `custom_list`), and the universe-side of `resolution.py` (`resolve_universe_members`
orchestration + `MemberResolution`/`ResolveFn` types + `_parse_token`). Rewrite intra-package imports
`sym.universe.*`→`universe.*`; schema-qualify all SQL to `universe.*`.

**STAY in sym (the resolver IMPL + price-load bridge + consumers — this is what sym injects/owns):**
- `ingest.py` (`run_universe_load`): calls `sym.ingest.pipeline.run_load` + `write_security` +
  `backfill_equity_instruments` — the universe-DRIVEN price load into sym's prices_raw. The story
  explicitly keeps this in sym. It fetches the member roster from the universe DB (roster-fetch).
- The resolver factories `make_local_resolve_fn` / `make_openfigi_resolve_fn` (read securities/
  security_symbology, call `plan_resolutions`/`read_exch_codes`) → become a **sym-side adapter**
  implementing `universe.Resolver`. `fundamentals.py` stays in sym (sym data; `recompute_market_cap_usd`
  already cross-DB to fx; `resolved_member_figis`/`all_resolved_member_figis` query
  universe_member_resolution → repoint to the universe DB via roster-fetch).

**The `Resolver` protocol (universe owns it; sym injects an impl):**
```
class Resolver(Protocol):
    def resolve_member_tokens(raw_identifiers: Sequence[str]) -> dict[str, MemberResolution]: ...
    def read_exchange_codes() -> dict[str, str]: ...            # MIC -> OpenFIGI exch_code
    def ensure_security_for_figi(seed, composite_figi, share_class_figi) -> bool: ...  # write_security
    def load_seed_universe(path: str | None) -> Iterable[Seed]: ...  # custom_list provider seed
```
`monitor.run_monitor(conn, universe_id, resolver, ...)`, `refresh.refresh_universe(conn, universe_id,
resolver, ...)`, `accuracy.*`, and `custom_list` take the injected `resolver`. **`SeedSecurity`**: keep
the canonical type in `sym.identity.universe`; universe defines its OWN minimal `Seed` shape (ticker/
mic/isin) for the protocol so it doesn't import sym — the sym adapter maps `Seed`↔`SeedSecurity`.
**`trading_calendar`** read in `monitor` → inject a `calendar_lookup` callable (or fetch the small
session list before the run). All universe→sym table reads become injected functions or roster-fetches.

**Cross-DB consumers (P3, roster-fetch — small composite_figi lists, NO cross-DB joins):**
`backtest/engine.py:_members`, `signals/compute.py:_members` (+ the `sym:universe_membership` asset-spec
input → `universe:universe_membership`), `sym/cli.py` universe subcommands (add/list/refresh/members/
monitor/coverage/review/confirm/accuracy/reverse/index — open a universe conn; `coverage`/`index` are
cross-DB: roster from universe, prices/instrument from sym), `eod.py` monitor step (open universe conn +
inject sym resolver), `sym/validate/*` universe checks (cross-DB), `services/api/modules/sym` explorer +
`modules/data_monitor` universe bucket (read the universe DB; bucket already supports per-package DBs via
`package_dsn`), `lineage` universe bucket/asset (package=`universe`). `universe_benchmark` STAYS in sym;
`sym/indices/links.py` + `api/sym_contract.py` keep reading it; its `universe_id` FK→ soft reference (P4).

**Invariants (carry over):** `universe_reload_no_gaps` (end-caps incl leavers now from the universe DB),
identity bridge whole in sym, SCD/projection + `feedback_scd_same_day_inplace`, no cross-DB FKs, Docker
sqitch, schedules keep explicit tz. Seed-in-migration gotcha from fx: if universe needs reference seed
rows, seed them IN a migration (a fresh deploy_all must build a functional DB).

## Verification
- universe import-guard (no `sym` import); `deploy_all --status` clean incl. the new `universe` DB.
- AC#5 behavior matrix live; sym + api + lineage + universe suites green; ruff clean;
  `lineage.definitions` loads.
- Confirm AC#4 in each consumer: roster fetched from the universe DB, no large cross-DB join.
- Web/UI (explorer + Data Monitor coverage) via the running console (toolchain caveat — CDP/inspection).
- Large, cross-cutting refactor: land on a branch; code-review adversarially on (a) the one-way
  dependency, (b) behavior preservation, (c) the cross-DB roster pattern + `reload_no_gaps`, before merge.
