---
stepsCompleted: [1, 2, 3, 4]
workflow_completed: true
session_active: false
ideas_generated: ['#1 Mono-DB many schemas', '#2 Trust-Split Twins', '#3 DB-per-dataset', '#4 Sym-Core + Regenerable Research DB', '#5 One-DB tiered schemas', '#6 Isolate-only-what-forces', '#7 Read-replica fan-out', '#8 Bundle-per-product', '#9 Federate-dont-ingest', '#10 blast-radius/DR lens', '#11 solo-operator-toil lens', '#12 Federation layer = seamlessness organ', '#13 Specialise-and-federate', '#14 Postgres-per-package + DuckDB federation (CHOSEN)']
inputDocuments: []
session_topic: 'Platform database topology — sym + QRP (+ future internal/external datasets): one database with many schemas, or separate standalone databases per dataset?'
session_goals: 'Decide a deliberate database topology (replacing the incidental sym-DB-with-QRP-schemas layout) that fits near-term simplicity AND a future of many datasets incl. external ones. Surface options, tradeoffs (isolation, cross-dataset queries, sellable/standalone modules, migrations, backup/DR, access control, ops), and a recommended direction + migration path from today.'
selected_approach: 'ai-recommended'
techniques_used: ['First Principles Thinking', 'Morphological Analysis', 'Solution Matrix']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Brainstorming guide (Claude)
**Participant:** Andre
**Date:** 2026-06-08

## Session Overview

**Topic:** Platform database topology — should sym, QRP, and future datasets (including
external ones) live as schemas in one database, or as separate standalone databases?

**Goals:** Replace the *incidental* current layout (QRP's six schemas living inside the `sym`
database, an artifact of sym-came-first-then-QRP) with a *deliberate* topology. Decide what
best fits both near-term simplicity and the realistic future of many datasets — including
external ones — surfacing the full option space and tradeoffs, and landing a recommended
direction with a migration path.

### Session Setup

The current state (to be reconsidered, not assumed): one Postgres database `sym` holding
sym's own schema (public) PLUS QRP's six schemas (`qrp`, `macro`, `signal`, `backtest`,
`optimiser`, `altdata`), with two Sqitch projects (`sym`, `qrp`) in a shared registry.
This emerged incrementally. Prior decisions that this session may revisit: **AR-Q4**
("schema-per-module on shared Postgres") and the **standalone/sellable-module** constraint
from the platform brainstorm. The driving new fact: more datasets are coming, including
**external** ones, which changes the isolation / ownership / connectivity calculus.

Initial framing tension (participant): one-DB-many-schemas (simple, cheap joins) vs.
separate-DB-per-dataset (isolation, standalone/sellable, but cross-DB joins are harder);
simplicity favors one now, the multi-(external-)dataset future favors separation.

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis context:** an architecture *decision-space* (not a binary), anchored by a
"sym-came-first" historical accident that must be reset before deciding.

**Recommended sequence (broad → narrow):**
- **First Principles Thinking** — strip the history; rebuild from fundamental data/access/
  isolation truths so we don't rationalize the accidental layout.
- **Morphological Analysis** — map the real parameter space (grouping axis · internal-vs-
  external split · cross-dataset access mechanism · isolation level · migration/registry)
  into candidate topologies beyond the two first named.
- **Solution Matrix + What-If stress** — score candidates against the forces and future
  scenarios → recommended topology + migration path.

## Phase 1 — First Principles (design principles)

Working assumptions (operator to confirm): A1 more datasets coming, internal + external,
some large/licensed/vendor-hosted; A2 client/multi-tenant stays OUT but don't architect
against its return; A3 sellable/standalone is a design value, not a near-term sales motion
(→ optimize cheap-to-split-later, not split-now); A4 ≥1 external feed will carry a
redistribution/licensing constraint (topology must ALLOW isolating a dataset).

- **P1 — sym is a hub, everything else a spoke.** One-way dependency (spokes read sym; sym
  reads nothing). Make sym-read-only physically enforceable, not just convention.
- **P2 — the real fault line is the trust boundary, not module count.** internal-derived vs
  external-ingested matters more than one-schema-per-feature.
- **P3 — splitting is cheap IFF nothing is physically coupled.** Single-owner writes +
  tolerant analytical reads + value-only join keys (no cross-dataset FKs) = a dataset can be
  lifted later cheaply. Protect THIS property, not the initial placement.
- **P4 — access mechanism is the real design variable** (in-DB cross-schema · postgres_fdw ·
  read-replica · API/contract), downstream of which "one DB or many" mostly falls out.

## Phase 2 — Morphological Analysis (candidate topologies)

Axes: A placement {one-DB · trust-split · DB-per-dataset · bundle} · B isolation {schema ·
database · instance} · C access {in-DB · fdw · replica · API} · D identity {value-only · FK ·
external-mapping} · E migration {one project · per-dataset · per-DB}.

1. **Mono-DB, Many Schemas** (today) — cheapest ops+joins, weakest isolation, one blast radius.
2. **Trust-Split Twins** — `core` (sym+derived) + `ext` (external feeds); the real fault line,
   one split to manage.
3. **Hub-and-Spokes (DB-per-dataset)** — max isolation/sellability, max ops surface.
4. **Sym-Core + Regenerable Research DB** — group by lifecycle (durable / regenerable / external);
   per-group DR policy.
5. **One DB, Schemas Grouped by Tier** (`sym`/`derived`/`external`) — P2 clarity at zero cross-DB cost.
6. **Isolate-Only-What-Forces-You** — split a dataset out only when size/licence/host demands (policy).
7. **Read-Replica Fan-Out** — consumers read a sym replica (physical read-only); overlay, not standalone.
8. **Bundle-per-Product** — group storage by sellable bundle; only if A3 becomes a sales motion.
9. **Federate, Don't Ingest** — external stays at source (API/object store/DuckDB); only sym_id mapping local (policy).

Driving lenses (orthogonal): **#10 blast-radius/DR** (independent PITR; runaway loader can't bloat
sym) · **#11 solo-operator toil** (N DBs = N pools/migration targets/monitors — heaviest counterweight
to over-splitting).

## Phase 3 — Solution Matrix

Whole-topology contenders scored (#6/#9 are escape-valve *policies* that compose with any base;
#7 is a read-path overlay). Scores 1–5, weights reflect the solo-operator + sym-hub + external-
future reality. Weighted totals out of 145.

| Criterion (weight) | #1 Mono | #5 Tiered | #2 Twins | #3 Per-DB |
|---|---|---|---|---|
| Operator toil / simplicity (5) | 5 | 5 | 4 | 2 |
| Isolation & DR / blast-radius (3) | 2 | 2 | 4 | 5 |
| Cross-dataset read ergonomics (4) | 5 | 5 | 4 | 2 |
| Cheap-to-split-later — optionality (5) | 3 | 4 | 4 | 5 |
| sym read-only enforceability (3) | 2 | 3 | 4 | 5 |
| External-data fit (licence/size/host) (4) | 2 | 3 | 5 | 5 |
| Sellable / standalone alignment (2) | 2 | 2 | 3 | 5 |
| Migration burden *from today* (3) | 5 | 4 | 3 | 1 |
| **Weighted total / 145** | **99** | **108** | **115** | **106** |

**Result:** #2 Trust-Split Twins (115) > #5 Tiered (108) > #3 Per-DB (106) > #1 today (99).
#5 is the low-cost runner-up AND a natural stepping-stone to #2. #3's capability is real but
dragged down by toil + migration + cross-read cost for a solo operator (it splits eagerly to
buy optionality obtainable lazily). Weights are the subjective crux — pending operator review.

### What-If stress test of #2 (winner)

#2 survived DR (7), residency (8), vendor-death (9), huge-feed (1), cost (10); it **bent** on:
B1 selling/sharing **sym alone** (it buries sym with derived in `core`) and B2 **per-feed**
external needs (one `ext` DB is too coarse for per-licence/region/engine). Refinements: treat
tiers as 3 (`sym`/`derived`/`external`), keep sym independently liftable; `external` = a
per-feed *policy*, not one DB.

## DECISION (operator, 2026-06-08): full independence — modularity over consolidation

The operator **overrode the matrix winner**, choosing **#3-refined: Independent Packages +
Contract Seam**, because **modularity is the top value** (and the original Mirantia founding
constraint: each package standalone + separately sellable). This is a deliberate reweight of
sellable/standalone/independence to the top — by that weighting, #3 wins. Not a whim; a return
to first principles already set.

**The decision commits to:**
- **Every package owns everything** — own database · own Sqitch project + migrations · own API
  router · own version · own console slice. sym, signal, backtest, optimiser, portfolios, macro,
  altdata each its own DB; each future (incl. external) dataset too.
- **The `contract` seam is mandatory** — downstream depends on `sym_id` + published views/types +
  a `sym-client` SDK, never another package's raw tables (Mirantia rule #2). This is what makes
  independence clean rather than brittle, and enables pointing a module at a **remote** sym.
- **Load-bearing invariant:** value-only join keys, **no cross-database FKs**, cross-dataset reads
  only via the contract.

**Pivotal sub-decision — how independent DBs read the hub** (recommended default, operator may
revisit): **Access B = API/SDK contract** (cleanest boundary; true remote capability; QRP's API
already assembles sym reads in code) — with **Access C (logical replication / local read-model)**
for any consumer whose joins are too hot for API calls, and **Access A (`postgres_fdw`)** as the
transitional bridge while packages still share one instance.

**Accepted cost (eyes-open):** N databases = N pools / migration targets / monitors / credentials —
real solo-operator toil. Mitigation is mandatory **meta-orchestration**: one "deploy all Sqitch
projects" command, one compose file to bring up all DBs, shared secret/config resolution (the
DB/migration analogue of today's `dev.mjs` running API+console together). This tooling is the
price of modularity — budget for it.

### Migration path (from today's shared `sym` DB)

1. **Extract the contract** — define `sym-client` (the published `sym_id` + views/types/SDK) so
   consumers stop touching sym internals. (Enabler; unblocks everything.)
2. **Carve QRP's schemas into their own databases** — `macro`, `signal`, `backtest`, `optimiser`,
   `altdata`, `qrp`(portfolios+jobs) each become a database with its own Sqitch project (the
   formalized migrations already exist — repoint each project's target to its own DB).
3. **Repoint reads to the contract** (Access B), package-by-package; replicate (C) only a hot path
   if/when one bites. FDW (A) only as a temporary same-instance bridge.
4. **sym becomes its own DB + read replica** (#7) when a second consumer or a standalone sale
   appears — also closes the deferred read-only-DB-role hardening item.
5. **Build the meta-orchestration** (deploy-all migrations + compose-up-all DBs) before the DB
   count makes manual ops painful.
6. **Invariant guard:** a check that no migration introduces a cross-database FK or reads another
   package's raw tables (keeps independence honest).

### Refinement (operator): independent BUT seamless + specialisable

Two added requirements: (i) independence must **facilitate expansion/specialisation** of each
package; (ii) packages must **talk seamlessly, as if one unit/product**. These pull against each
other — clean independence adds seams; "feels like one product" wants none. **Resolution: split
the two onto different layers** so they stop fighting.

- **Ownership / write layer — fully independent.** Own DB, engine, migrations, version, cadence.
  This is where specialisation lives: a package can later adopt Timescale / DuckDB / ClickHouse /
  a vector store and scale alone, with no permission from neighbours.
- **Connective tissue — a shared semantic contract.** Universal `sym_id` + sym's standardized
  conventions (date naming, currency, return windows) are the lingua franca. Packages line up
  because they share identity + conventions, not a database — the real source of the "one unit"
  feel.
- **Read / seamless layer — a federation surface.** `postgres_fdw` (or a dedicated *federated
  read-DB*) exposes each package's published views as foreign schemas so cross-package analytics
  read **as if one database** (SQL joins work), while ownership stays split; FDWs exist for non-PG
  engines, so a *specialised* package still federates. The **API gateway** (QRP's API already is
  one) presents **as if one product** at the app layer.

**Idea #12 — Federation layer = the seamlessness organ.** The seam is unavoidable under
independence; put it in ONE designed place (federated read surface for SQL + API gateway for the
app) instead of smearing it everywhere. Reframes "seamless vs independent" as a *layering* choice.

**Idea #13 — Specialise-and-federate.** A package can diverge in engine/scale *because* the
contract + federation insulate everyone else; independence enables specialisation, the contract
keeps it seamless. Heterogeneous engines become a feature, not fragmentation.

**Access recommendation → hybrid by purpose** (supersedes the single-mechanism pick):
- App/product reads → **API gateway** (Access B) = "as if one product".
- Cross-package analytics → **federated read surface** (Access A / FDW, or a federated read-DB) =
  "as if one database".
- Hot/heavy paths → **local read-model** (Access C, logical replication).
- All three ride the same `sym_id` + conventions contract (the connective tissue).

### Right-sizing correction (operator): "no contract — building for myself, for now"

The operator rejected the formal `contract` package / `sym-client` SDK as premature ceremony
(it was a *sellability* enabler; not warranted solo). This **supersedes** the "contract seam is
mandatory" framing above. Recalibrated, leaner shape:

- **"The contract" collapses from a package to a discipline** — no SDK to build/version. The
  interface IS just: `sym_id` (composite_figi) as the universal join key + **sym's stable
  published views** as what consumers read + sym's existing conventions (date naming, currency,
  return windows). All already exist; nothing to build.
- **Access recommendation flips to `postgres_fdw`-first for solo** — with no SDK, FDW is the
  simplest seamless organ: independent DB per package, but query **across** them with plain SQL
  **as if one DB**. QRP's *existing* API stays the app surface (no new gateway abstraction).
  API/SDK (Access B) and logical replication (C) are deferred until a real need (e.g. a remote
  consumer or a heavy hot path) actually bites.
- **Near-free future-proofing to KEEP even solo:** the *discipline* — read sym only via its stable
  views, never another package's raw tables, no cross-database FKs. Costs nothing now; lets a
  formal SDK be a *later* refactor IF selling ever happens. Don't pre-pay for it; don't preclude it.
- **Deferred until/if selling:** formal `sym-client` SDK, entitlement/licensing, remote-sym,
  bundle-per-product (#8).

**Net solo shape:** separate DB per package (modularity + specialisation) · **FDW** for seamless
cross-DB SQL · existing QRP API as the app surface · the lightweight discipline as the only
"contract". Lean; preserves the modularity goal without the enterprise ceremony.

**Migration-path correction:** step 1 ("extract the contract / `sym-client`") is **dropped** — there
is no package to extract. It becomes: *adopt the discipline* (consumers read sym's stable views +
sym_id; no cross-DB FK) and *stand up FDW* so cross-DB reads stay seamless. Steps 2–6 stand.

### The Snowflake-join constraint (decision-shaping fact)

Operator works in Snowflake terms and wants native `database.schema.table` cross-DB joins.
**PostgreSQL cannot do this** — a connection sees one database; "database" is a hard wall (no
3-part names, no cross-database joins). Postgres's native equivalent of a Snowflake cross-DB join
is a cross-**schema** join *within one database* (`sym.fundamentals JOIN signal.score`). So in
vanilla PG: **separate databases ⇒ FDW (local foreign-table names, not native 3-part)**, while
**schemas-in-one-DB ⇒ native joins but no hard isolation**. This tension is what surfaced DuckDB.

### Topology #14 (operator-favoured): Postgres-per-package + DuckDB federation

**Concept:** each package = its own independent **Postgres** DB (system of record; writes via
psycopg; own migrations/backups/engine). **DuckDB** (embedded in the QRP API / a CLI) is the
analytical + federation layer: `ATTACH` **read-only** to each package's Postgres DB (+ Parquet for
external/large), giving **native `catalog.schema.table` cross-database joins** — the Snowflake
ergonomics — over independent stores. Resolves the independence-vs-native-join tension *by layer*:
Postgres owns truth per package; DuckDB is the "as if one warehouse" read surface. DuckDB
complements, never replaces, Postgres (OLAP query/federation engine vs. OLTP system of record).

**Pressure test — holds:**
- **Snowflake-style joins** — native 3-part names across attached DBs ✓ (the goal).
- **External / large / heterogeneous** — Parquet/object-store joined in the same query; non-PG
  engines (MySQL/SQLite/Parquet) attachable ✓✓ (the #9 "federate" policy, now native + ergonomic).
- **DR** — each Postgres independently backed up; the DuckDB layer is a **regenerable cache**
  (disposable, never backed up) ✓✓.
- **Read-only boundary** — `READ_ONLY` attach + a read-only PG role → physically enforced ✓
  (also closes the deferred read-only-DB-role item).
- **Specialisation** — a package may be PG / MySQL / SQLite / Parquet and still federate ✓✓
  (validates Idea #13, specialise-and-federate).
- **Sell sym alone** — sym is its own PG DB; a buyer gets sym + optionally their own DuckDB layer ✓.

**Pressure test — bends (needs design):**
- **B-i — live-attach perf on HEAVY analytics** (full-history backtests over ~20M return rows):
  live Postgres scans can be slow → add a **materialization tier** (Parquet snapshots refreshed by
  a job); live-attach for fresh/filtered reads (one-universe heatmap), materialized snapshots for
  heavy/full-history crunching.
- **B-ii — concurrency:** don't have many processes writing one DuckDB file (single-writer).
  Materialize to **Parquet** (multi-reader) or write a new snapshot atomically; readers open
  read-only.
- **B-iii — freshness contract:** decide per surface — live-attach = 0 staleness but slower;
  materialized = fast but refresh-cadence stale. (Heatmap likely live; backtests on a snapshot.)
- **B-iv — two query idioms:** psycopg for single-DB transactional/simple reads + all writes;
  DuckDB for cross-package analytical reads. Needs a clear "which path" discipline.

**Honest non-fix:** DuckDB solves the seamless-**JOIN** problem, **not** the N-database
**operator-toil** problem. N independent Postgres DBs are still N backup/migration/monitor targets;
**meta-orchestration** (deploy-all migrations, compose-up-all DBs, a central DSN registry — which
DuckDB's ATTACH list also consumes) remains the mandatory price of independence.

**Guard:** materialized DuckDB/Parquet is **always a regenerable cache, never authoritative** —
else it drifts into a shadow source of truth.

**Refined #14 (leading direction):** systems of record = Postgres DB per package · DuckDB embedded
federation (read-only ATTACH + Parquet) · a materialization tier (regenerable Parquet snapshots for
heavy paths) · discipline (`sym_id` + sym's stable views as the interface; cache never authoritative;
no cross-DB FK). Delivers independence + Snowflake-style joins + external/heterogeneous fit; the
only unpaid bill is the N-DB operational toil → meta-orchestration.

---

## Session Summary & Decision

**CHOSEN DIRECTION: Topology #14 — Postgres-per-package (independent systems of record) +
DuckDB as the federated analytical/query layer.**

Each package (sym, signal, backtest, optimiser, portfolios, macro, altdata, and future incl.
external) is its **own independent Postgres database** — own Sqitch migrations, backups, engine,
version, release cadence (modularity + expansion/specialisation, the operator's top value, and the
original Mirantia founding constraint). **DuckDB**, embedded in the QRP API/CLI, `ATTACH`es them
**read-only** (+ Parquet for external/large) and provides **native `catalog.schema.table`
cross-database joins** — the Snowflake-style ergonomics the operator wanted — over the independent
stores. Postgres owns truth; DuckDB is the disposable "as if one warehouse" read surface.

**The "contract" is a discipline, not a package** (right-sized for solo): `sym_id` + sym's stable
published views + sym's conventions are the interface. No SDK/entitlement/remote ceremony until/if
selling. **Load-bearing invariants:** no cross-database FKs; consumers read only stable views;
materialized Parquet/DuckDB is always a regenerable cache, never authoritative.

### Key insights (the arc)
1. "One DB vs many" is **not binary** — it's a *layering* decision: independence at the
   ownership/write layer, unification at the read/federation layer.
2. The decisive personal constraint was **Snowflake-style native joins** — Postgres can't do
   cross-*database* joins natively (a "database" is a hard wall); only cross-*schema*. DuckDB's
   `ATTACH` resolves it without sacrificing independence.
3. The **contract** is a discipline, not a package (solo right-sizing).
4. **DuckDB fixes the seamless-join problem, not the operator-toil problem** — N independent DBs
   still need meta-orchestration. That toil is the conscious price of modularity.

### Action plan (sequenced)
1. **Spike the federation (lowest-risk first move):** embed DuckDB, `ATTACH READ_ONLY` to two of
   today's schemas-as-DBs (or carve one out first), run a real cross-DB Snowflake-style join (the
   heatmap: sym + signal + fundamentals + gics). Measure live-attach perf (pressure point B-i).
2. **Write the freshness contract:** classify each QRP read surface as **live-attach** (heatmap,
   explorer, per-security) vs **materialized Parquet snapshot** (full-history backtests).
3. **Carve packages into their own Postgres DBs, one at a time** — reuse the Sqitch projects already
   built; repoint each to its own DB. Start with the most independent (macro/altdata — external, no
   sym writes); end with sym itself (→ own DB + read replica, which also closes the read-only-role item).
4. **Stand up the materialization tier** — a refresh job writing regenerable Parquet snapshots for
   heavy paths (guard: never authoritative).
5. **Build meta-orchestration** — deploy-all-migrations across the N Sqitch projects, compose-up-all
   DBs, one DSN registry (also feeds DuckDB's ATTACH list). The mandatory price of independence.
6. **Invariant guard (CI/check):** no cross-DB FK; consumers read only stable views; cache regenerable.
7. **Architecture reconciliation:** this **revises AR-Q4** ("schema-per-module on *shared* Postgres")
   → run `bmad-correct-course` / update `architecture-qrp.md` in the QRP repo to record the new topology.

### Open design items (deferred sub-decisions)
- Materialization format + refresh cadence/trigger (Parquet files vs a DuckDB file).
- Where DuckDB runs (embedded in the API process vs a small dedicated query service) + concurrency.
- External-dataset identity mapping (`sym_id` ↔ external id), per feed.
- Whether/when to adopt **MotherDuck** (hosted DuckDB) — deferred.

### Reflections
Strong convergent session: started from "the DB layout feels wrong (an accident of sym-first)",
reframed to a layered decision, ran the option space wide (14 candidates), and landed on a topology
that satisfies the full goal set — independence, Snowflake-style joins, external/heterogeneous fit,
read-only enforcement, specialisation — with eyes open on the one real cost (N-DB ops → orchestration)
and one design tier (materialization for heavy paths). The DuckDB insight was the unlock that turned a
genuine either/or (independence vs native joins) into a both/and.
