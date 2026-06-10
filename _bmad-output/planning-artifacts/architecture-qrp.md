---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-06-07'
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/prd.md
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/addendum.md
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/.decision-log.md
  - _bmad-output/planning-artifacts/epics-qrp.md
  - _bmad-output/planning-artifacts/architecture.md (sym architecture — technical context only)
workflowType: 'architecture'
project_name: 'QRP (Quant Research Platform)'
user_name: 'Andre'
date: '2026-06-07'
scope: 'v1 — Epics Q1–Q3 (Console Spine, sym—See, sym—Operate)'
note: 'Separate from sym''s own architecture.md (status: complete). QRP is a consumer of sym.'
---

# Architecture Decision Document — QRP (Quant Research Platform)

_This document builds collaboratively through step-by-step discovery. Sections are appended
as we work through each architectural decision together. Scope: QRP v1 (the console + API
over the sym warehouse). QRP is a **consumer** of sym — it reads sym's views and triggers
sym's idempotent operations; it never reimplements sym logic or mutates sym's schema._

## Architecture Revision Log

### 2026-06-08 — DB topology revised: database-per-package + DuckDB federation (supersedes AR-Q4)

A dedicated DB-topology brainstorm (`brainstorming-session-2026-06-08-123427.md`; see also
`sprint-change-proposal-2026-06-08.md`) replaced the incidental "QRP schemas inside the sym
database" layout with a deliberate topology. **This supersedes AR-Q4 ("schema-per-module on
shared Postgres").**

- **New target topology:** each package (sym, signal, backtest, optimiser, portfolios, macro,
  altdata, + future incl. external) is its **own independent Postgres database** — own Sqitch
  project, backups, engine, version, release cadence (modularity + expansion/specialisation,
  the operator's top value, and the Mirantia founding "separately sellable" constraint).
  **DuckDB** (embedded in the API/CLI) is the read-only federation layer: `ATTACH READ_ONLY`
  to each package DB (+ Parquet for external/large) → **native `catalog.schema.table` cross-
  database joins** (the Snowflake-style ergonomics) over the independent stores. DuckDB
  complements Postgres (OLAP query/federation engine), never replaces it (OLTP system of record).
- **Unchanged by this revision:** the consumer/actuator boundary (read sym via stable views,
  mutate only via sym ops); **AR-Q3** (one FastAPI service, per-module routers) and **AR-Q7**
  (monorepo fold-in alongside) are orthogonal to storage and stand; "numbers tie to the
  warehouse". Reads-are-read-only is *strengthened* — physically enforced by DuckDB's
  `READ_ONLY` attach + a read-only role (also closes the dual-credential read-only item). The
  "contract" is a **discipline** (`sym_id` + stable views + no cross-DB FK), not an SDK package
  (solo right-sizing — no SDK/entitlement/remote ceremony until/if selling).
- **What this reframes in the sections below:** the **Data Architecture** framing ("shared
  PostgreSQL / QRP-owned `qrp` schema in sym's DB") and **ADR-3** (read contract = in-DB views)
  — each package now owns a database; cross-package reads go through the DuckDB federation layer;
  the `qrp` job-state *schema* becomes the `qrp` *database*. The dual-credential model resolves to
  a per-package read-only role consumed by the federation layer.
- **Status: DIRECTION, not yet implemented.** Current state: schemas remain co-resident in the sym
  database but are now **Sqitch-formalized** (project `qrp`, commit `38074b0`). The built v1
  (Q1–Q5 + the 8 module areas) is **NOT invalidated** — this changes deployment topology, not the
  consumer/actuator design. Migration is a forward, incremental, force-triggered workstream.
- **ADR-3 interim ruling (2026-06-10, project-wide code review chunk 1):** module reads of sym
  **base tables are accepted until the DuckDB-federation restructure lands** — the spec'd published
  views mostly don't exist, and building them now would be throwaway work given the federation
  direction above. The views-only contract is NOT abandoned: it re-materializes as the per-package
  read-only role + `ATTACH READ_ONLY` discipline when the restructure is built. Until then,
  reads-are-read-only remains a code-review-enforced discipline, not a physical one.
- **New design items it introduces:** a **materialization tier** (regenerable Parquet snapshots
  for heavy analytical paths; never authoritative), a **live-vs-materialized freshness contract**
  per read surface, and **meta-orchestration** (deploy-all migrations / compose-up-all DBs / one
  DSN registry — which DuckDB's ATTACH list also consumes) as the accepted price of N-database
  independence.
- **First implementation step (lowest-risk):** a DuckDB federation spike — `ATTACH READ_ONLY` two
  of today's schemas-as-DBs and run the real heat-map cross-DB join, measuring live-attach perf.

## Project Context Analysis

### Requirements Overview

**Functional Requirements (v1 = Q1–Q3):**
QRP v1 is a consumer console + API over sym. Architecturally the FRs reduce to three
capability clusters: (a) a config-driven shell + typed API (FR-1; FR-2 palette deferred);
(b) read/inspect sym — overview/freshness, explorer, read-only attention, validation
(FR-3,4,5,10,12); (c) trigger sym ops as guarded background jobs with status/history
(FR-6,7,8,9; FR-11 act-on-attention deferred). Roadmap FRs (13–22) add their own module
schemas joined on sym_id but are not designed in depth here.

**Non-Functional Requirements (architecture drivers):**
- NFR-1/2 (faithfulness / no-reimplementation) → consumer-only boundary for reads (via
  published views) and mutate only through sym's idempotent ops. **NFR-2 has teeth on the
  read side too:** "expected session / freshness" is *domain logic*; if QRP computes it
  rather than sourcing it from sym, that is reimplementation (see hard core #2 below).
- NFR-4/6/7 (action safety / live progress / observability) → an out-of-web-process job
  executor with per-op locking, audit via pipeline_run_log, and a progress transport.
- NFR-8 (typed contract) → Pydantic models → generated TypeScript types.
- **Principle (confirmed by Andre): numbers always tie to the warehouse.** No mocked or
  un-provenanced data — every figure the console shows is a live read of sym (or clearly
  stamped with its as-of), and is traceable to its sym source (reinforces NFR-7).
- NFR-3 (single operator, no auth) → local/trusted-host deployment; no user auth in v1.
  **Conscious risk:** the actuation path (triggering ops that mutate the warehouse) is
  unauthenticated — anything that reaches localhost can mutate sym. Acceptable for one
  local operator; named, not omitted. Least-privilege DB creds still apply.
- NFR-5 (responsiveness) → paged/filtered reads. **Constraint chain:** NFR-1 (no schema
  mutation) means QRP *cannot add indexes to sym* → read perf is capped by sym's existing
  views/indexes; tune queries within that, or request a view/index from the sym side.
- NFR-9/10 (config identity / modularity) → platform.toml single source; per-module
  routers mounted by feature toggle.

### Scale, Complexity & Risk Location

- Primary domain: full-stack web (Next.js console + FastAPI API) over an existing Postgres.
- **Reframed posture:** QRP is a **consumer (for reads) + actuator (for writes — it
  triggers state changes in sym)**. "Consumer-only" understates the actuation risk.
- **Complexity vs risk:** *small surface, single operator, no multi-tenancy/auth/compliance
  — but a high-risk actuation core.* Risk ≠ size; low volume does not make the core safe.
- **Two hard cores (not one):**
  1. **sym-Operation execution** — out-of-web-process run, per-op locking, durable commit,
     progress. (The Q3.1 spike subject.)
  2. **Freshness / expected-session authority** — a calendar-aware notion of "current vs
     stale" per area that must respect sym's off-calendar/phantom finding + FX outage caps.
     Open NFR-2 question: **does sym expose "expected session / freshness", or does QRP
     compute it?** Lean: source from sym / co-locate the definition; do NOT recompute in QRP.
     **Principle:** there is a single source of truth for "what is current" — sym owns
     calendars + validation, so freshness *authority* is sym's; QRP only *displays* it.
- Architectural components: console (shell + screens), API (per-module routers), a sym-read
  layer (views), a sym-invocation + job-execution layer, a small QRP job-state store, a
  type-generation pipeline.

### Technical Constraints & Dependencies

- Consumer/actuator of sym: reads sym's Postgres via **views** (psycopg3-era schema,
  Sqitch-managed); triggers sym's idempotent ops; never alters sym's schema or logic.
- sym is Python; QRP API is Python (FastAPI) → library-first invocation feasible, subprocess
  fallback for CLI-only ops.
- **Dual DB credentials:** a read-only role for reads; a separate privileged path for op
  execution (the connection is NOT purely read-only end-to-end).
- Shared PostgreSQL; QRP owns any new schema (e.g. job state) under its own namespace,
  joined to sym on sym_id where relevant.
- Single config source of truth (platform.toml) for name/theme + enabled modules.
- A throwaway scaffold spike (C:\Projects\mirantia-platform) proved FastAPI+psycopg reading
  the live sym DB — reference only, not committed scope.

### Cross-Cutting Concerns Identified

**Center of gravity:** `pipeline_run_log` + the freshness/expected-session function are the
shared hub of the three highest-risk concerns (freshness ↔ job-execution ↔ observability
form a cycle: stale → suggests an op → op writes pipeline_run_log → updates freshness).
Design them as one coherent unit, not separate bullets.

1. **sym-invocation boundary + background-job execution** (the Q3.1 spike) — highest-risk;
   decides deployment topology.
2. **Cross-process concurrency with sym's OWN scheduled runs** — a per-op lock only guards
   QRP-initiated runs; an external `sym eod` cron could run concurrently. The lock must be a
   **DB-level lock sym itself also takes** (verify whether sym already locks), or QRP cannot
   actually prevent the collision.
3. **Read contract** — views-first; documented dependencies; **policy when a needed view
   does not exist** (request from sym vs pin specific tables); a read-only role.
4. **sym schema-drift coupling** — a sym migration can silently break QRP's reads; needs a
   read-contract test / pinned dependency against sym's schema.
5. **Freshness / expected-session authority** (NFR-2 boundary — see hard core #2).
6. **Run provenance / correlation** — distinguish QRP-triggered runs from external ones in
   pipeline_run_log; correlate the QRP job heartbeat ↔ sym's run row.
7. **Op-failure surfacing** — how a failed sym op's error propagates to the console.
8. **Worker process supervision / lifecycle** — who runs/restarts the out-of-process
   executor (local deployment).
9. **Typed contract** — Pydantic → generated TS types so console/API can't drift.
10. **Config-driven identity + feature-toggle module mounting** (shell + API).
11. **Read perf capped by sym's indexes** — NFR-1 forbids QRP adding indexes (see above).
12. **Actuation-path security without auth** — "no auth in v1" must not mean "any webpage
    can trigger ops": bind to 127.0.0.1 only, add a same-origin/CSRF guard (or local shared
    secret) on trigger endpoints, an **op allow-list** (the library-callable set), and
    **never interpolate strings into a shell** (argument arrays / library calls).
13. **Orphaned / zombie-run detection** — a worker dying mid-op can leave a run marked
    "running" with no completion; need heartbeat-timeout reconciliation.
14. **Config validation on boot** — a malformed/missing `platform.toml` must fail safe
    (refuse to start with a clear error), not mount a broken shell.
15. **Command transparency** — the console shows the exact sym op/command it triggered (so
    actions are auditable and never diverge from what the CLI would run).

### Decision Agenda (ADR stubs — picks deferred to the decision steps)

*Pure analysis phase: options are framed here; decisions are made in the technology/
decision steps (and ADR-1/2 are what the Q3.1 spike resolves).*

- **ADR-1 — sym-Operation execution topology:** in-proc pool · subprocess per op · minimal
  in-house worker · real queue (RQ/arq/Celery). Out of the web process either way.
- **ADR-2 — Concurrency lock:** Postgres advisory lock (only prevents external-cron
  collision if sym takes the same lock) · app lock · job-table unique constraint.
- **ADR-3 — Read contract:** sym views · base tables (coupled) · sym-provided read API.
- **ADR-4 — Monorepo fold-in:** scaffold alongside (read DB / import sym) · fold sym in now.
- **ADR-5 — Progress transport:** client poll · SSE · WebSocket.
- **ADR-6 — Pydantic→TS type generation:** openapi-typescript from FastAPI's OpenAPI ·
  pydantic2ts · manual.

### Likely sym-side dependency

If sym does not already expose an "expected session / freshness" signal (and a lock QRP can
share — ADR-2), a small **sym-side addition** may be needed (a view/function), requested
from the sym module — NOT reimplemented in QRP. To confirm during the Q3.1 spike.

## Starter Template Evaluation

### Primary Technology Domain

Full-stack web, **split**: a Next.js **console** (frontend) + a Python **FastAPI** API
(backend) that calls sym library-first. Python monorepo scaffolded ALONGSIDE the existing
sym repo (ADR-4 default). No single full-stack starter fits, because the backend must be
Python (to invoke sym in-process) — so the console and API are scaffolded independently.

### Starter Options Considered

- **Console — create-next-app (Next.js 16) + shadcn/ui CLI v4** (selected). App Router +
  RSC, TS, Tailwind v4, Turbopack, ESLint out of the box; shadcn v4 supplies the
  Radix-based design-system primitives that realize Q1.1's Perplexity-style look.
- **T3 stack (create-t3-app)** rejected — bundles tRPC + Prisma + NextAuth and assumes
  Next *is* the backend; QRP's backend is a separate FastAPI service over sym's Postgres.
- **API — no boilerplate generator** — FastAPI is a library; hand-scaffold via **uv**
  (matches sym's uv + psycopg3 tooling), as the spike proved.
- **Single-process FastAPI + HTMX/Jinja** — the honest simpler alternative (one toolchain,
  one process, in-process sym). Not chosen — the polished-UI requirement justifies the split
  — but it is the fallback if that UI bar ever softens (see trade-off below).

### Selected Starter

Console: `create-next-app@latest` (Next 16) + `shadcn@latest init`.
API: `uv`-managed FastAPI service (no template).

**Initialization Commands:**

```bash
# Console (frontend)
npx create-next-app@latest apps/console --typescript --tailwind --eslint --app --use-npm
cd apps/console && npx shadcn@latest init      # CLI v4, Tailwind v4, --base radix

# API (backend) — uv, matching sym's tooling
uv init services/api
uv add fastapi "uvicorn[standard]" "psycopg[binary]"
```

**Architectural Decisions Provided by the Starter(s):**

- **Language & runtime:** TypeScript (console) · Python 3.11+ (API, uv-managed).
- **Styling / design system:** Tailwind **v4** + shadcn/ui v4 (Radix) — basis for Q1.1.
- **Build tooling:** Turbopack (Next 16) · uv (Python).
- **Routing / structure:** App Router + RSC; `@/*` alias; route-groups per module area;
  per-module FastAPI routers.
- **Dev experience:** Next dev server + HMR; `AGENTS.md` for coding-agent guidance.

**Versions web-verified (June 2026):** Next 16.2.x · shadcn CLI v4 · Tailwind v4 ·
React 19.2. Supersedes the throwaway scaffold's stale pins (Next 14 / TW v3).

**Note:** Project initialization with these commands is the first implementation story
(folds into Q1.1 design foundation + Q1.2 API spine).

### Foundation — locked direction, pre-lock probes & scoping (roundtable + Andre)

**Locked direction:** the split stack is the foundation — justified *by the polished-UI
requirement, and only that*. **Accepted trade-off:** a single operator maintains two
toolchains (npm + uv) — a conscious cost paid for UI quality; revisit FastAPI+HTMX if the
UI bar ever softens.

**Pre-lock probes (run BEFORE committing — cheap, convert assumptions to facts):**
1. **sym import-boundary probe (~1 hr, highest-leverage).** Verify sym is cleanly callable
   in-process: `import sym` with `PYTHONPROFILEIMPORTTIME=1` (any I/O/connect/env at
   import?); grep for module-level `connect(`/`getenv`/`load_dotenv`/top-level statements;
   confirm the real op + read entry points take a connection/config *parameter*, not a
   global; `uv add` sym beside FastAPI and confirm the resolver completes. If it fails →
   subprocess fallback for ops (the in-process rationale weakens) — a finding worth having
   early. (Also the Q3.1 spike subject + the "likely sym-side dependency".)
2. **Front-end vertical spike (~½ day).** create-next-app (Next 16) → Tailwind v4 → shadcn
   CLI v4 → render two components (one Radix) under Turbopack. Collapses the Tailwind-v4 /
   shadcn-v4 / Next-16 / React-19.2 maturity claims into evidence (Tailwind v4's CSS-first
   config is the only genuine churn surface).

**Scoped minimum foundation (first visible slice — a read-only Overview):**
uv workspace + **sym imported in-process** + audit **only the Overview's read path** +
**OpenAPI→TS codegen** + one RSC page through a **Next `rewrites()` proxy** (`/api/*` →
`:8000`, no CORS) rendering **real** freshness/last-run data + **exact version pins** (no
carets; commit `package-lock.json` + `uv.lock`) + `.gitignore`. **Deferred until after
screen 1:** the full design *system* and the job-runner/actuator model (a read-only
Overview triggers nothing). The **universe heat map (Q2.6, FR-23)** is the second screen and
brings the **treemap** charting primitive online.

**Foundation conventions to pin now (cheap, expensive to retrofit):**
- **Directory layout pre-shaped for fold-in:** `apps/console`, `services/api`, a reserved
  `packages/sym` slot — eventual fold-in is a `git mv`, not a re-layout. Wire the uv
  workspace + in-process sym import NOW; "fold in later" = merge git history later, not
  integrate later.
- **Typed seam:** `openapi-typescript` (types-only) off FastAPI's OpenAPI; require explicit
  `response_model=` + unique `operation_id` on every route; `gen:types` is a committed,
  scripted step (+ CI freshness check), never at dev-server start.
- **shadcn vendored + pinned:** `npx shadcn@<pinned> init`, commit `components.json` +
  `globals.css` + `lib/utils.ts`; let the CLI own the Tailwind-v4 `globals.css`; discard the
  spike's TW-v3 config wholesale.
- **Charting primitives (named, not all built now):** a **treemap** (universe heat map,
  Q2.6), an inline **sparkline**, and a **TanStack-Table-backed DataTable** wearing shadcn
  cells (large/sortable lists) — so styled tables/charts aren't ripped out later.

**Q1.1 reconciliation (Sally ↔ John):** Q1.1 ships *enough* design tokens to not read as a
generic template — bespoke dark palette (not slate), `tabular-nums` locked, the
**ok/degraded/failed/stale** status vocabulary, tightened density/radius — and **names** the
treemap/sparkline/DataTable seams; it does **not** build the full design system before
screen 1. The system is extracted from real screens once 2–3 exist.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical (block implementation):** execution topology, concurrency lock, read contract,
auth posture.
**Important (shape architecture):** fold-in, progress transport, type-gen, frontend state,
charting, QRP data store.
**Deferred (post-MVP):** generalized job framework, act-on-attention (FR-11), full design
system, command palette (FR-2), SSE, any auth, CI beyond lint/type/test/gen-types.

### Data Architecture
- **DB:** sym's existing PostgreSQL. **Read via published views**, documented dependencies.
- **Dual DB credentials:** a read-only role for reads; a separate privileged path for op
  execution (the connection is not read-only end-to-end).
- **QRP-owned schema:** a `qrp` schema for job state (heartbeat, provenance), via Sqitch
  (matching sym). sym's schema is never mutated by QRP.
- **Caching:** none server-side in v1 (numbers tie to the warehouse); client TanStack Query
  with short/`no-store` staleness for live reads.
- **Read perf:** capped by sym's existing indexes (NFR-1 forbids QRP adding any) —
  page/filter within that; request a view/index from sym-side if needed.

### Authentication & Security
- **Auth: none in v1** (single operator, local/trusted host).
- **Actuation-path defense (still required):** bind 127.0.0.1; same-origin/CSRF guard on
  trigger endpoints; an **op allow-list** (the library-callable set); never interpolate
  strings into a shell.

### API & Communication Patterns
- **REST**, FastAPI, **per-module routers** mounted by feature toggle.
- **Type contract:** `openapi-typescript@7.13.x` (types-only); explicit `response_model=` +
  unique `operation_id` per route; `gen:types` committed + CI freshness check.
- **Execution topology (ADR-1):** sym ops run **OUT of the web process**.
  **FINALIZED (2026-06-10, Story O.2): the subprocess arm is the chosen mechanism** —
  `uv run sym <op>` under a supervising thread with heartbeat + timeout; process isolation,
  the tested CLI as the contract, and output capture outweigh in-proc reuse for op
  EXECUTION. **Library-first remains the rule for data-ACCESS gateways** (module routers
  read via psycopg/gateways in-process); the two are different layers, not a contradiction.
- **Concurrency (ADR-2):** a **Postgres advisory lock per op-key**. **Deviation recorded
  (Story O.2): the key is per (op + args)** — deliberately finer than the spec's
  per-Operation, so e.g. two universes can monitor concurrently while identical runs still
  exclude each other. Residual risk unchanged: sym's own scheduled runs don't take the
  lock, so QRP prevents only its own concurrent runs.
- **Progress transport (ADR-5):** **client polling** of `pipeline_run_log` + a QRP job
  heartbeat ("RUNNING · elapsed · last-completed op"); no "% complete". SSE deferred.
- **Errors:** structured error responses; failed-op errors surfaced to the console.

### Frontend Architecture
- **Console:** Next.js 16 (App Router/RSC) + Tailwind v4 + shadcn/ui v4 (Radix).
- **Server state:** **TanStack Query v5** (confirm React 19.2 compat in the spike); reads via
  **RSC server-fetch** through a **Next `rewrites()` proxy** (`/api/*` → `:8000`).
- **Charting primitives:** **Nivo** for the universe heat-map **treemap** (FR-23/Q2.6) —
  Recharts lacks treemaps; **DataTable** = TanStack Table + shadcn cells; **sparkline** =
  visx or a small custom SVG. Built when first needed (heat map = first treemap use).
- **Design tokens:** Q1.1 minimal token set (palette, tabular-nums, ok/degraded/failed/stale
  status vocabulary, density) — full system extracted from real screens later.

### Infrastructure & Deployment
- **Hosting:** local / trusted single host (no auth, single operator). No cloud scale.
- **Processes:** API (uvicorn) + a separate op-execution worker; a simple local supervisor.
- **CI:** lightweight — ruff/eslint/tsc/pytest + the gen-types freshness check.
- **Observability:** `pipeline_run_log` + the `qrp` job-state schema; every figure
  traceable; orphaned-run reconciliation via heartbeat timeout.

### Decision Impact Analysis
- **Implementation sequence:** pre-lock probes (sym import-boundary, front-end spike) →
  Q1 foundation (uv workspace + in-process import + shell + typed contract) → Q2.1 Overview →
  Q2.6 heat map (treemap) → Q3 Operate (spike-first: topology + lock + poll).
- **Cross-cutting:** `pipeline_run_log` + the freshness/expected-session function are the hub
  for freshness ↔ job-execution ↔ observability; the sym import-boundary probe gates the
  execution topology (ADR-1) and the "expected session" source (sym vs QRP).

## Implementation Patterns & Consistency Rules

### Naming Patterns

**Database (QRP's own `qrp` schema only — sym's schema is never touched):**
- snake_case tables/columns; `*_id` keys; `idx_<table>_<cols>` indexes; DATE-naming per
  sym's `docs/data-conventions.md` (`*_at` timestamptz, `*_date` dates). Sqitch migrations,
  matching sym. Job table e.g. `qrp.job` (id, op, status, triggered_by, run_log_id,
  heartbeat_at, started_at, ended_at, error).

**API:**
- REST under `/api/<module>/...`; plural resource nouns (`/api/sym/universes`,
  `/api/sym/universes/{id}/heatmap`); `{id}` path params; snake_case query params (`?window=...`).
- **Wire format is snake_case end-to-end** — Pydantic models emit snake_case, generated TS
  types preserve it (no auto-camelCase). Keeps the typed contract honest and matches sym's
  snake_case domain.

**Code:**
- Python (API): snake_case, **ruff line-length 100** (match sym); modules under
  `src/qrp_api/`, per-module `modules/<m>/router.py` + `gateway.py`.
- TypeScript/React: PascalCase components + files (`UniverseHeatmap.tsx`), `useX` hooks,
  camelCase locals, lowercase route-segment folders.

### Structure Patterns
- Monorepo: `apps/console`, `services/api`, reserved `packages/sym`. Python `src/` layout
  (matches sym); pytest in `tests/`. Console: App Router `app/(<area>)/...`, shared UI in
  `components/`, helpers in `lib/`, **generated types in `lib/api-types.ts`** (committed).

### Format Patterns
- **Success = the typed body directly** (no `{data:...}` wrapper). **Errors = a consistent
  model** `{ error: { type, message, detail? } }`, surfaced to the console (incl. op
  failures). HTTP status used honestly (404 missing, 409 lock conflict, 422 validation).
  **IMPLEMENTED (O.4):** global exception handlers in `qrp_api.main` translate every
  HTTPException/validation/unhandled error; a top-level `detail` mirror remains during
  the console migration (structured details — e.g. the 422 errors array — mirror
  byte-compatibly with the original FastAPI contract). Accepted un-enveloped
  exceptions: TrustedHost's plain-text 400 (a rebound/malicious Host gets no JSON
  niceties) and CORS preflight rejections (the browser consumes those, not app code).
- Dates: ISO-8601 strings. Numbers as-is from sym (no client re-rounding; display formatting
  only). Missing = explicit null + "gap" UI, never fabricated.

### Communication Patterns
- **Jobs:** status enum `QUEUED|RUNNING|SUCCEEDED|FAILED`; every job carries provenance
  (`triggered_by`) and correlates to sym's `pipeline_run_log` row. Status by **polling**
  (`GET /api/sym/jobs/{id}`), not push. Lock key = the op name (advisory lock).
- **Server state (console):** TanStack Query; query-key convention
  `['<module>','<resource>',...params]` (e.g. `['sym','universe',id,'heatmap',window]`);
  RSC for initial read, Query for client refetch/polling; immutable updates.

### Process Patterns
- **Status vocabulary everywhere:** the 4 states `ok | degraded | failed | stale` use one
  color/pill/icon set across all screens (freshness, validation, jobs). **Recorded
  deviation (O.4):** sym freshness deliberately reports a 3-state `ok | stale | unknown`
  — `unknown` (nothing measurable) is MORE honest than forcing a 4th token state; the
  console renders it via the neutral fallback pill (no degraded branch exists).
- **Loading:** skeletons matching final layout (no reflow); per-area error boundaries.
- **Logging:** the API uses its own structured logger; **never reconfigure sym's logging or
  global state** (protects the in-process import boundary).

### Enforcement
- All agents MUST: read sym **only via views**; mutate sym **only via its ops** (never its
  schema); keep every shown figure **traceable to a sym source** (numbers tie to warehouse);
  regenerate `api-types.ts` on any API schema change.
- Tooling gate: ruff (py-100) · eslint + prettier · tsc · pytest · gen-types freshness check.

## Project Structure & Boundaries

### Complete Project Directory Structure

```
qrp/                      # monorepo root (alongside C:\Projects\sym; folds sym in later)
├─ platform.toml                   # name/theme + enabled-modules (single source of truth)
├─ package.json                    # npm workspaces: ["apps/*"]
├─ package-lock.json               # committed, exact pins
├─ pyproject.toml                  # uv workspace root; members: services/api; sym as path source
├─ uv.lock                         # committed, exact pins
├─ .env / .env.example             # SYM_DB_* (read-only role) + QRP_OPEXEC_* (privileged) + API_BASE
├─ .gitignore                      # node_modules, .next, __pycache__, .venv
├─ README.md                       # exact `dev` command + port contract (written after slice runs)
├─ .github/workflows/ci.yml        # ruff(py-100) · eslint · tsc · pytest · gen-types freshness
├─ apps/
│  └─ console/                     # Next.js 16 (App Router/RSC) + Tailwind v4 + shadcn v4
│     ├─ package.json · next.config.ts (rewrites /api/* -> :8000) · tsconfig.json · components.json
│     ├─ app/
│     │  ├─ layout.tsx · globals.css (shadcn TW v4 @theme) · page.tsx (-> /sym)
│     │  └─ (sym)/sym/
│     │     ├─ page.tsx                          # Overview            (Q2.1)
│     │     ├─ universes/page.tsx                # universe list       (Q2.2)
│     │     ├─ universes/[id]/page.tsx           # universe detail     (Q2.2)
│     │     ├─ universes/[id]/heatmap/page.tsx   # heat map (treemap)  (Q2.6/FR-23)
│     │     ├─ securities/[figi]/page.tsx        # security detail     (Q2.3)
│     │     ├─ attention/page.tsx                # attention (read)    (Q2.4)
│     │     ├─ validation/page.tsx               # validation results  (Q2.5)
│     │     ├─ runs/page.tsx                     # run history         (Q3.2)
│     │     └─ operate/page.tsx                  # trigger + job panel (Q3.3/Q3.4)
│     ├─ components/
│     │  ├─ ui/                     # vendored shadcn primitives
│     │  └─ features/               # StatusBadge, FreshnessBadge, DataTable(TanStack), Treemap(Nivo), Sparkline, JobPanel
│     ├─ lib/                       # api.ts · api-types.ts (generated, committed) · query.ts · format.ts
│     └─ tests/                     # *.test.tsx
├─ services/
│  └─ api/                         # FastAPI (uv)
│     ├─ pyproject.toml             # fastapi, uvicorn, psycopg; sym via [tool.uv.sources] path
│     ├─ src/qrp_api/
│     │  ├─ main.py                 # app factory; mounts enabled module routers by toggle
│     │  ├─ config.py               # platform.toml + DSNs (read-only + op-exec)
│     │  ├─ db.py                   # read-only pool; op-exec connection factory
│     │  ├─ jobs/                   # worker.py · lock.py (pg advisory) · store.py (qrp schema) · poll
│     │  └─ modules/
│     │     └─ sym/                 # router.py · gateway.py (reads via views) · ops.py (allow-list->sym lib) · freshness.py
│     └─ tests/
├─ packages/
│  └─ sym/                          # RESERVED fold-in slot (empty until `git mv`)
├─ db/
│  └─ qrp/                          # Sqitch project for the `qrp` schema (job state) — sym's schema untouched
│     ├─ sqitch.plan · deploy/ · revert/ · verify/
└─ scripts/
   ├─ gen-types                     # openapi-typescript -> apps/console/lib/api-types.ts
   └─ dev                           # run uvicorn + worker + next concurrently
```

### Architectural Boundaries
- **Console <-> API:** HTTP only, `/api/*` via Next `rewrites()` proxy. The console **never**
  touches Postgres or sym directly.
- **API <-> sym:** reads via sym **views** on the **read-only role**; triggers sym ops
  **library-first in the worker** on the **op-exec** path; never mutates sym's schema. The
  `packages/sym` slot + uv path source is the in-process import seam.
- **Data:** sym schema (read-only, via views) + `qrp` schema (QRP-owned job state, R/W),
  joined on `sym_id`. QRP migrations live only under `db/qrp/`.
- **Worker:** ops run in the worker process (not the web worker), guarded by a per-op
  advisory lock; status via `pipeline_run_log` + `qrp.job` heartbeat.

### Requirements -> Structure Mapping
- **Q1 Console Spine ->** `platform.toml`, `apps/console` (layout/shell/design tokens),
  `services/api/src/qrp_api/{main,config,db}.py`, `scripts/gen-types`.
- **Q2 sym — See ->** `apps/console/app/(sym)/sym/*` read pages + `components/features/*`;
  `modules/sym/{gateway,freshness}.py` + read routes. **FR-23 heat map ->**
  `universes/[id]/heatmap/page.tsx` + `Treemap` (Nivo) + a heatmap read endpoint.
- **Q3 sym — Operate ->** `services/api/src/qrp_api/jobs/*` + `modules/sym/ops.py`
  (allow-list) + `db/qrp/` (the `qrp.job` migration); `apps/console` `operate/` + `runs/`
  pages + `JobPanel`.

### Development Workflow
- `scripts/dev` boots uvicorn (`:8000`) + the worker + `next dev` (`:3000`); the console
  proxies `/api/*` -> `:8000`. `scripts/gen-types` regenerates `lib/api-types.ts` from the
  API's OpenAPI (committed; CI checks freshness).

## Architecture Validation Results

### Coherence Validation (PASS)
- **Decision compatibility:** the stack is mutually compatible (Next 16 / React 19.2 /
  Tailwind v4 / shadcn v4 / Turbopack · FastAPI / uv / psycopg3 / PostgreSQL). One item to
  confirm in the front-end spike: TanStack Query v5 <-> React 19.2 (v5 targets React 18+).
- **Pattern consistency:** patterns align with the stack — snake_case end-to-end matches
  Pydantic + sym's domain; ruff-100 matches sym; per-module routers match the module model.
- **Structure alignment:** the tree supports every decision (qrp schema isolated under
  `db/qrp/`; read-only vs op-exec creds; out-of-process worker; reserved `packages/sym`
  fold-in slot; Next `rewrites()` proxy).

### Requirements Coverage Validation (PASS)
- **Epics:** Q1–Q3 fully mapped to files/dirs; Q4–Q9 (roadmap) shaped, not designed.
- **Functional:** v1 FRs FR-1,3,4,5,6,7,8,9,10,12,23 each have a home; **FR-2 (palette)
  and FR-11 (act-on-attention) are consciously deferred** (documented, not gaps).
- **Non-functional:** NFR-1/2 (consumer boundary, views, no-reimpl), NFR-3 (no auth +
  actuation defense), NFR-4 (advisory lock + audit), NFR-5 (index-capped paging), NFR-6
  (poll + heartbeat), NFR-7 (traceable; numbers tie to warehouse), NFR-8 (typed contract),
  NFR-9 (platform.toml), NFR-10 (feature-toggle mounting) — all addressed.

### Implementation Readiness Validation (PASS)
- **Decisions:** documented with web-verified versions; the one genuinely open mechanism
  (in-process worker vs subprocess) is decided *with a fallback*, gated by the Q3.1 probe.
- **Structure & patterns:** complete tree, boundaries, conflict points, and req->structure
  mapping are all specified.

### Gap Analysis Results
- **Critical (block implementation):** none open. The load-bearing unknown (sym's
  in-process import boundary) is handled by a designed fallback (subprocess) + a cheap
  pre-lock probe scheduled as the FIRST implementation step — so the architecture is
  coherent under either outcome.
- **Important (address as first steps):** (1) confirm TanStack Query v5 <-> React 19.2 in
  the spike; (2) confirm/request a sym-side "expected session/freshness" signal (else a
  small sym-module addition, never recomputed in QRP); (3) pin the Nivo (treemap) version at
  build; (4) specify the local worker supervisor; (5) finalize the heat-map endpoint shape.
- **Nice-to-have:** SSE progress, command palette (FR-2), richer CI — all post-v1.

### Architecture Completeness Checklist
**Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**Architectural Decisions**
- [x] Critical decisions documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Performance considerations addressed

**Implementation Patterns**
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified
- [x] Process patterns documented

**Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment
**Overall Status:** READY FOR IMPLEMENTATION (all 16 checklist items checked; no open
Critical gaps — the sym-import unknown has a designed fallback + a pre-lock probe as step 1).
**Confidence Level:** high (modulo two spike confirmations: sym import boundary, TanStack
Query/React 19.2).
**Key Strengths:** strict consumer/actuator boundary preserving sym's invariants; numbers
always tie to the warehouse; reads-before-writes; risk concentrated and spiked first; modern,
verified, polished UI stack.
**Areas for Future Enhancement:** the full design system, the job-runner generalization,
act-on-attention, SSE, command palette, the roadmap modules (portfolios/analytics/...).

### Implementation Handoff
**AI Agent Guidelines:** follow the decisions exactly; read sym only via views; mutate sym
only via its ops; keep every figure traceable; regenerate `api-types.ts` on schema change.
**First Implementation Priority:** run the two pre-lock probes (sym import-boundary ~1 hr;
front-end vertical spike ~1/2 day), THEN the Q1 foundation init (`create-next-app` +
`shadcn init`; `uv init services/api` + sym as a uv path source).

### Probe Results (2026-06-07) — ADR-1 resolved: library-first (in-process)

The sym import-boundary probe **passed**: `import sym` and submodules are clean against an
unreachable DB host (no import-time DB/network/env); `src/sym/__init__.py` is inert; the only
module-level side effects are benign in-memory registry registrations (AR-5 plugin pattern);
`load_dotenv()`/`psycopg.connect()` are function-scoped; `sym.db.connect(conninfo=...)` is
parameter-based. **Decision:** the op-execution worker invokes sym **library-first in-process**;
the subprocess fallback is NOT needed. (Front-end vertical spike to run during Q1 scaffolding.)
