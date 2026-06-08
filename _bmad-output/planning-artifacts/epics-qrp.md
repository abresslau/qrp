---
stepsCompleted: ["step-01-validate-prerequisites", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/prd.md
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/addendum.md
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/.decision-log.md
  - _bmad-output/planning-artifacts/architecture.md (sym architecture — technical context only)
---

# QRP (Quant Research Platform) - Epic Breakdown

## Overview

This document provides the epic and story breakdown for **QRP** — the console + API
platform over the sym warehouse — decomposing the QRP PRD (`prd-qrp-2026-06-07`) into
implementable stories. No QRP-specific Architecture or UX spec exists yet (those steps
were intentionally skipped); sym's `architecture.md` is referenced for technical context
only. This file is deliberately separate from sym's own `epics.md` (and the
`epics-fx`/`epics-universe-layer`/`epics-validation` files), which belong to the sym
module, not to QRP.

## Requirements Inventory

### Functional Requirements

**v1 — Platform shell + sym Module Area (in MVP scope):**

- **FR-1**: Module-aware shell driven by config — the nav lists exactly the Module Areas
  whose Feature Toggle (in `platform.toml`) is enabled; enabling a module surfaces its
  nav entry + API routes without shell code changes; platform name/theme come from the
  single config source.
- **FR-2**: Command palette & fast navigation — keyboard-opened palette to jump to any
  area/screen/entity and launch common actions.
- **FR-3**: Warehouse Overview — headline counts (securities, universes, priced) + latest
  session date + per-area Freshness + most-recent Run status + open-Attention roll-up, on
  one screen; reads only.
- **FR-4**: Browse securities & universes — list/inspect securities (by sym_id) and
  universes with members + resolution status; paging/filtering at thousands-of-securities
  scale.
- **FR-5**: Inspect prices, returns, FX, fundamentals — per-security price history,
  returns across Return Windows, FX, fundamentals (LCY + USD market cap); missing = gaps,
  never fabricated.
- **FR-6**: Browse run history — history of sym Runs (status/timing/summary) sourced from
  `pipeline_run_log`, including Runs triggered outside QRP.
- **FR-7**: Trigger sym Operations — launch sym's idempotent ops (eod/delta/recompute/fx/
  validate/universe monitor|review|confirm) mapped to real sym entry points; creates a
  logged Run; confirm for heavy/destructive ops; never mutates sym schema directly.
- **FR-8**: Live Run progress — stream progress for an in-flight Run; show outcome +
  summary on completion and reflect it in history without manual refresh.
- **FR-9**: Concurrency & safety guards — block/queue conflicting concurrent Runs of the
  same Operation; surface failures; offer idempotent re-run as recovery.
- **FR-10**: View attention items — open Attention Items grouped by type
  (`securities_review_queue`, `price_gaps`, `membership_proposal` + monitor logs) with
  sym-recorded evidence.
- **FR-11**: Act on attention items — resolve an item (confirm/dismiss/acknowledge) via
  sym's corresponding Operation; logged; item leaves the open list; no state changed
  except through sym's mechanisms. *(DEFERRED to post-v1 per the roundtable; v1 attention
  is read-only.)*
- **FR-12**: Validation results — latest `validate` results (pass/fail per check) with
  drill-into-failures, sourced from sym's validation logs.
- **FR-23**: Universe heat map — visualize a universe as a **treemap** of constituents,
  tiles **sized by market cap** (USD), **colored by return** over a selected window,
  **grouped by GICS sector**; hover shows name/return/market cap; missing data shown as
  gaps, never fabricated. Pure read (universe membership + fundamentals + return facts +
  gics_scd). *(v1 Q2 story, sequenced after the Overview; needs the treemap primitive.)*

**Roadmap — post-v1 (specified to shape architecture; NOT in MVP):**

- **FR-13**: Manage clients & portfolios — create Clients/Portfolios; select a
  Client/Portfolio context (ordinary navigation, not security isolation).
- **FR-14**: Load portfolio weights over time — upload effective-dated weight vectors;
  constituents resolve to sym_id; unresolved flagged as gaps; weights validated (sum≈1,
  residual/cash explicit).
- **FR-15**: Portfolio return & PnL — time-weighted Return + PnL across Return Windows
  from weights × sym constituent returns.
- **FR-16**: Risk & skill metrics — Sharpe, alpha, hit ratio, batting average, slugging
  ratio vs a selected Benchmark; reproducible from sym inputs.
- **FR-17**: Benchmark selection — choose a sym Universe/index as the Benchmark driving
  relative metrics.
- **FR-18**: Run a backtest (vision) — `backtest`: run a *defined* strategy over a sym
  Universe + date range → paper Portfolio (weights over time) consumable by analytics.
- **FR-19**: Surface a raw alt-data series (vision) — view an `altdata` series (card
  transactions, satellite, geolocation, social sentiment, ...) joined to a security by
  sym_id.
- **FR-20**: Surface a macro series (vision) — view a `macro` series (policy rate /
  monetary aggregate) with source attribution + release dating; time series, not keyed by
  sym_id.
- **FR-21**: Identify / surface a signal (vision) — define and view a *derived* `signal`
  (feature/factor/alpha) computed from sym + macro + altdata, with inputs + method
  traceable; consumable by backtest/optimiser (strategy inputs) and analytics (factors).
- **FR-22**: Optimise an allocation (vision) — `optimiser`: search an objective +
  constraints over a sym Universe (with optional `signal` inputs) → optimal weights as a
  Portfolio, reproducible from its inputs; consumable by backtest/analytics.

### NonFunctional Requirements

- **NFR-1**: Faithfulness to sym (reconstructability) — never mutate sym schema/data
  except via sym's idempotent Operations; all other sym interaction is read-only.
- **NFR-2**: No reimplementation — returns/FX/validation/universe/market-cap logic is
  never reimplemented in QRP; read sym's results or trigger sym's Operations.
- **NFR-3**: Single-operator, no auth (v1) — one Operator, no authentication, no
  multi-tenancy/RLS; protected by local/trusted-host deployment.
- **NFR-4**: Action safety — explicit, auditable triggers; confirms for heavy ops; every
  Run logged; idempotent re-run as recovery; no hidden writes.
- **NFR-5**: Responsiveness — read screens fast at thousands-of-securities /
  hundreds-of-thousands-of-rows scale (paging/filtering, not full loads). [ASSUMPTION p95 < ~1s]
- **NFR-6**: Live progress — long Runs stream progress; never block the UI / force manual
  refresh.
- **NFR-7**: Observability — every Run traceable end-to-end (request → `pipeline_run_log`
  → outcome); never show a number untraceable to a sym source.
- **NFR-8**: Type-safe contract — typed API schemas → generated TS types so Console/API
  cannot silently drift.
- **NFR-9**: Configurable identity — name/branding/theme from one config source; rebrand
  is a one-line change.
- **NFR-10**: Modularity — a new Module Area adds (nav + routes + screens) without shell
  changes beyond enabling its Feature Toggle.

### Additional Requirements

*(Architecture-derived — from the PRD addendum + decision log. No QRP architecture doc
yet; these are the technical givens that shape stories.)*

- **AR-Q1 — Consumer posture / boundary:** the API READS sym tables/views and TRIGGERS
  sym Operations as logged background jobs; never owns sym's data.
- **AR-Q2 — sym invocation = library-first:** the API invokes sym as a library
  (in-process calls); DB reads direct; subprocess only for any CLI-only op. (Decided.)
- **AR-Q3 — One FastAPI service, per-module routers:** `/api/sym/...` now; future
  `/api/portfolios|analytics|...` mounted only when the module's Feature Toggle is on.
- **AR-Q4 — Schema-per-module on shared Postgres:** sym keeps its schema; future modules
  get own schemas joined on sym_id; each owns its migrations (Sqitch).
  **[SUPERSEDED 2026-06-08 → database-per-package + DuckDB federation. Each package (incl.
  sym) its own Postgres DB + Sqitch project; cross-package reads via a read-only DuckDB
  federation layer (ATTACH + Parquet) giving native cross-DB joins; value-only sym_id keys,
  no cross-DB FK. See architecture-qrp.md "Architecture Revision Log" +
  brainstorming-session-2026-06-08-123427.md + sprint-change-proposal-2026-06-08.md.
  Direction, not yet implemented.]**
- **AR-Q5 — Background jobs + live progress:** Runs are tracked async jobs with streamed
  progress and a persisted history (`pipeline_run_log`). Mechanism (in-proc vs queue) is
  an open architecture question.
- **AR-Q6 — Single config source of truth:** `platform.toml` holds name/theme + per-module
  Feature Toggles, read by both API and Console.
- **AR-Q7 — Monorepo fold-in = alongside (working default, undecided):** for v1, scaffold
  console/API alongside the existing sym (import it / read its DB); do not fold sym into a
  monorepo package yet.
- **AR-Q8 — Type generation:** Pydantic models → generated TypeScript types (NFR-8).

### UX Design Requirements

None — no UX specification exists for QRP. The PRD references a Perplexity-style polish
target and a shadcn/ui design system (addendum), but detailed UX work (tokens,
components, accessibility) is deferred to the build or a later `bmad-create-ux-design`
pass. Visual/interaction conventions are NOT enumerated as requirements here.

### FR Coverage Map

- **FR-1** → Epic Q1 — branding/name from config + simple enabled-modules list (sym shows)
- **FR-2** → Epic Q1 — command palette *(later story; de-prioritized, not gating)*
- **FR-3** → Epic Q2 — warehouse Overview & Freshness
- **FR-4** → Epic Q2 — browse securities & universes
- **FR-5** → Epic Q2 — inspect prices/returns/FX/fundamentals
- **FR-6** → Epic Q3 — run history
- **FR-7** → Epic Q3 — trigger sym Operations
- **FR-8** → Epic Q3 — live Run progress
- **FR-9** → Epic Q3 — concurrency & safety guards
- **FR-10** → Epic Q2 — view attention items *(read-only)*
- **FR-11** → **Deferred to post-v1** (act on attention) — was Q3; deferred per the
  party-mode roundtable. v1 attention is read-only (FR-10 view + FR-12 validation, in Q2).
- **FR-12** → Epic Q2 — validation results *(read-only)*
- **FR-23** → Epic Q2 — universe heat map (treemap; read-only; after Overview)
- **FR-13** → Epic Q4 (roadmap) — manage clients & portfolios
- **FR-14** → Epic Q4 (roadmap) — load portfolio weights over time
- **FR-15** → Epic Q5 (roadmap) — portfolio return & PnL
- **FR-16** → Epic Q5 (roadmap) — risk & skill metrics
- **FR-17** → Epic Q5 (roadmap) — benchmark selection
- **FR-18** → Epic Q6 (roadmap) — run a backtest (`backtest`)
- **FR-22** → Epic Q7 (roadmap) — optimise an allocation (`optimiser`)
- **FR-19** → Epic Q8 (roadmap) — surface raw alt-data series (`altdata`)
- **FR-20** → Epic Q8 (roadmap) — surface macro series (`macro`)
- **FR-21** → Epic Q9 (roadmap) — identify/surface a derived signal (`signal`)

*NFRs are cross-cutting; key bindings: NFR-1/2 (faithfulness/no-reimpl) → Q2 (reads) +
Q3 (writes); NFR-4/6/7 (action safety/progress/observability) → Q3; NFR-5 (perf) → Q2;
NFR-8 (typed contract) & NFR-9 (config identity) → Q1; NFR-10 (modularity) → Q1, built
just-in-time (full generic module framework deferred until module #2 lands).*

## Epic List

> **v1 (MVP) = Epics Q1–Q3** (reads-before-writes, no speculative framework). Epics
> Q4–Q9 are **roadmap** (post-v1), listed so all 22 FRs are covered and the architecture
> is shaped for them; story creation (step-03) focuses on Q1–Q3.
>
> **Keep v1 tight to accelerate v2.** The stated motivation for QRP is *running clients'
> portfolios* (Q4 + Q5) — all roadmap. v1 is deliberately the minimal sym console so v2
> (portfolios + analytics) comes fast; resist gold-plating the maintenance console.
>
> *(Restructured 2026-06-07 via advanced elicitation: former Q1 "Platform Shell & Module
> Framework" shrank to a thin **Console Spine** — generic module-registry/feature-toggle
> + command palette deferred to just-in-time; read-only attention/validation (FR-10/12)
> moved into "See"; act-on-attention (FR-11) merged into "Operate & Act" with the job
> machinery it needs, removing the old Q4→Q3 cross-epic coupling.)*
>
> *(Refined 2026-06-07 via party-mode roundtable: Q3 renamed "Operate" and descoped —
> act-on-attention (FR-11) deferred to post-v1; v1 keeps the safety wall (out-of-web-
> process execution + one advisory lock per op + `pipeline_run_log`-tailed status) and a
> spike that precedes Q3 AC-lock and fixes the sym invocation topology. Other roundtable
> ideas — a Q2 resolve-and-align reader, Overview-honesty ACs, architecture pins — were
> considered but NOT adopted into the epics at this time.)*

### Epic Q1: Console Spine  *(v1 — foundation)*
The Operator can open QRP in the browser and land on a branded sym Overview, backed by a
running API. Minimal shell: name/theme from the single config source (`platform.toml`)
and a simple enabled-modules list so the sym area shows; the API is one service with the
sym router mounted and typed schemas surfaced to the Console. **Deferred (just-in-time,
not v1-gating):** the generic module-registry / per-module bundle loader and the command
palette (FR-2) — built when a second module (portfolios) actually arrives, not
speculatively.
**User outcome:** a polished, branded QRP that opens and hosts the sym area — the spine
later modules plug into.
**FRs covered:** FR-1 (FR-2 deferred to a later story). **Also:** AR-Q2, AR-Q3, AR-Q6,
AR-Q8; NFR-8, NFR-9.
**Depends on:** nothing (foundation).

### Epic Q2: sym — See (Visibility)  *(v1 — reads)*
The Operator can see the health and contents of the sym warehouse without writing a
query: a one-screen Overview (counts, latest session, per-area Freshness, recent-Run +
attention roll-ups), a read-only Data Explorer (securities, universes with membership
resolution, prices, returns across windows, FX, fundamentals), the **read-only** attention
queue, and the latest validation results. All reads — no writes, no jobs.
**User outcome:** answers UJ-1 (morning health check) and "what's in the warehouse / what
needs attention?" end-to-end.
**FRs covered:** FR-3, FR-4, FR-5, FR-10 (view), FR-12 (validation results). **Also:**
NFR-1/2 (read side), NFR-5, NFR-7.
**Depends on:** Q1.
**Build note:** Freshness needs an explicit, trading-calendar-aware notion of *expected*
session/as-of per area, so "stale vs current" badges don't lie — pin this in its story.

### Epic Q3: sym — Operate  *(v1 — writes/jobs)*
The Operator can trigger sym's idempotent Operations (the handful actually run by hand)
from the Console as tracked background Runs, watch their status, and review a durable Run
history — guarded so the same Operation can't run twice at once. **Descoped per the party-
mode roundtable (2026-06-07):** the *safety wall stays* — Operations run **out of the web
process** (worker/subprocess), with **one advisory lock per Operation**, and status is
**tailed from `pipeline_run_log`** plus a QRP job heartbeat. The generalized job
framework, cross-Operation concurrency policy, and **act-on-attention (FR-11) are deferred
to post-v1** (over-built for one low-frequency operator).
**User outcome:** answers UJ-2 (fix a gap and watch it run). Acting on attention items is
post-v1; in v1 the read-only attention rows (Q2) name the manual fix command.
**FRs covered:** FR-6, FR-7, FR-8, FR-9. *(FR-11 deferred — see below.)* **Also:** AR-Q1,
AR-Q2, AR-Q5; NFR-1, NFR-4, NFR-6, NFR-7.
**Depends on:** Q1 (and the read-only attention views from Q2 for context).
**Spike first — precedes AC-lock:** a foundation spike runs BEFORE Q3 story ACs are
written and proves, in code: (a) trigger → job id returns immediately while the op runs
out of the web process; (b) two concurrent triggers of one op → one runs, one is rejected
by the advisory lock; (c) the op owns its own connection and commits durably (kill the
request mid-flight → no partial commit); (d) the heartbeat + `pipeline_run_log` poll drive
a truthful status line ("RUNNING · elapsed · last-completed op" — **not** "% complete",
which sym can't emit today). The sym **invocation topology** (worker/subprocess vs
in-process, library-first per AR-Q2) is *decided here, before ACs* — not left for the
spike to "discover".

---

### Epic Q4: portfolios — Clients & Portfolios  *(roadmap, post-v1 — likely v2)*
The Operator can create Clients and Portfolios and load a Portfolio as a time series of
effective-dated weight vectors that resolve to sym_id.
**FRs covered:** FR-13, FR-14. **Depends on:** Q1 (+ sym data).

### Epic Q5: analytics — Portfolio Analytics  *(roadmap, post-v1 — likely v2)*
The Operator can measure a Portfolio against a chosen Benchmark with the full metric set
(return, PnL, Sharpe, alpha, hit/batting/slugging).
**FRs covered:** FR-15, FR-16, FR-17. **Depends on:** Q4 (portfolios) + sym returns.

### Epic Q6: backtest — Backtesting  *(roadmap, vision)*
The Operator can run a *defined* paper strategy over a sym Universe and date range,
producing a paper Portfolio (track record) consumable by analytics. The evaluation engine
the optimiser builds on.
**FRs covered:** FR-18. **Depends on:** Q1 + sym; feeds Q5 (analytics) & Q7 (optimiser).

### Epic Q7: optimiser — Optimisation  *(roadmap, vision)*
The Operator can run an optimisation (objective + constraints over a sym Universe, with
optional `signal` inputs) that produces optimal weights as a Portfolio.
**FRs covered:** FR-22. **Depends on:** Q6 (backtest, to score candidates) + sym (+ Q9
signal optionally); feeds Q5 (analytics).

### Epic Q8: altdata & macro — Raw Data Modules  *(roadmap, vision)*
The Operator can surface raw alternative-data series (`altdata`, joined by sym_id) and
macroeconomic series (`macro`, indicator time series), as shared-reference data feeding
the `signal`/research modules.
**FRs covered:** FR-19 (altdata), FR-20 (macro). **Depends on:** Q1.

### Epic Q9: signal — Signal Identification  *(roadmap, vision)*
The Operator can define and surface derived Signals (features/factors/alpha) computed
from sym + macro + altdata, with inputs + method traceable; consumable by
backtest/optimiser and analytics.
**FRs covered:** FR-21. **Depends on:** Q8 (altdata/macro) + sym; feeds Q6/Q7 & Q5.

---

# v1 Stories

*Detailed stories for the v1 epics (Q1–Q3). Roadmap epics Q4–Q9 stay at vision level and
get stories in a later pass. Stories are sized for a single dev session and have no
forward dependencies within an epic.*

> **Look & feel north star (applies to every v1 screen).** QRP's UI target is
> **Perplexity-finance-style polish**: a calm dark theme, generous whitespace with dense-
> but-legible data, restrained typography, card/section layouts, tabular numerals that
> don't jitter, confident empty/loading states, and quiet motion. Built on Tailwind +
> shadcn/ui (Radix). The **design foundation (Story Q1.1)** establishes this baseline; every
> later screen story (shell, Overview, explorer, job panel) inherits it — "matches the
> design foundation" is an implicit AC on each. A deeper UX pass (`bmad-create-ux-design`)
> can follow if needed, but is not required to start.

## Epic Q1: Console Spine

**Goal:** a branded, module-aware QRP console + API spine — opening to the sym area — that
sets the Perplexity-style visual baseline for the whole platform.
**FRs:** FR-1 (FR-2 command palette deferred). **NFRs:** NFR-8 (typed contract), NFR-9
(config identity), NFR-10 (modularity, just-in-time). **UX:** establishes the look & feel
north star (see above).

### Story Q1.1: Design foundation & app chrome (Perplexity-style)

As the Operator,
I want QRP's visual foundation — theme, layout primitives, and app chrome — to feel like a
polished Perplexity-finance-style product from the first screen,
So that every later screen inherits a consistent, calm, professional look.

**Acceptance Criteria:**

**Given** the console app
**When** the design foundation is in place
**Then** a Tailwind + shadcn/ui (Radix) setup exists with a calm dark theme, a defined type
scale, spacing scale, and color tokens (all from a single theme source, no ad-hoc values)

**Given** the app chrome
**When** any screen renders
**Then** it uses shared layout primitives — sidebar nav + content area, page header,
cards/sections, data tables with tabular numerals, badges/status pills, and confident
empty / loading / error states — that match the look & feel north star

**Given** a reusable component gallery (or equivalent reference screen)
**When** a developer builds a new screen
**Then** the primitives above are available to compose from (so screens look consistent
without re-styling)

**And** no business data is required — this story is pure UI foundation (it can ship before
the API returns real data)

### Story Q1.2: Config-driven API spine

As the Operator,
I want a running QRP API that reads `platform.toml` and exposes platform + health
endpoints with module routers mounted by config,
So that the console can render the right branding and reach only the live modules.

**Acceptance Criteria:**

**Given** `platform.toml` with name/theme/enabled-modules
**When** the API starts
**Then** `GET /api/platform` returns name, theme, and the module list with `enabled` flags
**And** `GET /api/health` returns ok + the enabled module keys

**Given** a module's `enabled` flag is false
**When** the API mounts routers
**Then** that module's routes are absent (404)
**And** only enabled modules' routers mount

**Given** the `sym` module is enabled
**When** the API is running
**Then** the sym router is mounted under `/api/sym` and reachable

**Given** the public API surface
**When** any endpoint responds
**Then** responses are typed (Pydantic models), not untyped dicts
**And** the API performs no writes to sym (read/trigger posture only — this story adds no sym writes)

### Story Q1.3: Branded, module-aware console shell

As the Operator,
I want a branded console whose navigation reflects the enabled modules,
So that I can open QRP and navigate to the sym area.

**Acceptance Criteria:**

**Given** the `/api/platform` response
**When** the console loads
**Then** the shell shows the configured platform name + theme (no hardcoded name)
**And** the nav lists exactly the enabled Module Areas (Overview + sym in v1)

**Given** the console shell
**When** I select the sym area
**Then** I land on the sym Overview route (placeholder content acceptable until Q2)

**Given** a module is disabled in `platform.toml`
**When** the console renders
**Then** no nav entry or route for that module exists

**Given** a changed name/theme in `platform.toml`
**When** the API + console restart
**Then** the console branding reflects the change with no code edit

**Given** the design foundation (Q1.1)
**When** the shell renders
**Then** it is built from those primitives and matches the Perplexity-style look & feel
north star (not default/unstyled framework chrome)

### Story Q1.4: Typed contract → generated TS types

As the developer-operator,
I want the console's API types generated from the API's schemas,
So that the console and API cannot silently drift.

**Acceptance Criteria:**

**Given** the API's Pydantic models
**When** the type-generation step runs
**Then** matching TypeScript types are produced and consumed by the console for
`/api/platform` + `/api/health`

**Given** an API schema change
**When** types are regenerated
**Then** a mismatched console usage fails typecheck (drift caught at build)

**Given** a fresh checkout
**When** a developer runs the documented type-gen command
**Then** the types regenerate reproducibly (single command, documented)

## Epic Q2: sym — See (Visibility)  *(v1 — reads only)*

**Goal:** see the warehouse's health and contents without writing a query. **FRs:** FR-3,
FR-4, FR-5, FR-10 (read-only), FR-12, FR-23 (heat map). **NFRs:** NFR-1/2 (read side),
NFR-5, NFR-7. **Depends on:** Q1.

### Story Q2.1: Warehouse Overview & Freshness

As the Operator,
I want a one-screen Overview of warehouse scale, latest session, per-area freshness, and
roll-ups,
So that I can judge sym's health at a glance (UJ-1).

**Acceptance Criteria:**

**Given** the sym warehouse
**When** I open the Overview
**Then** I see counts (securities, universes, priced securities) and the latest session
date, matching the warehouse at load time

**Given** each data area (prices, returns, FX, fundamentals)
**When** the Overview renders
**Then** each shows a current/stale indicator relative to the latest expected
session/as-of date

**Given** the most recent Run and open attention/validation items
**When** the Overview renders
**Then** it shows the last Run's status and counts of open attention items, each linking
to its area (link targets land with Q2.4/Q2.5)

**Given** the Overview
**When** it renders any figure
**Then** every figure is a read of sym (no writes) and is traceable to its sym source

### Story Q2.2: Securities & universes explorer

As the Operator,
I want to browse and inspect securities and universes,
So that I can see what's in the master and how universes resolved.

**Acceptance Criteria:**

**Given** the securities master
**When** I open the explorer
**Then** securities are listable and individually viewable by sym_id with core master
fields (name, exchange, currency, status)
**And** listing supports paging/filtering that does not load all rows at once (NFR-5)

**Given** a universe
**When** I open it
**Then** I see its members with resolved/total counts matching the warehouse and each
member's resolution status

### Story Q2.3: Security detail — prices, returns, FX, fundamentals

As the Operator,
I want a security's prices, returns across windows, FX, and fundamentals on one view,
So that I can inspect its data without SQL.

**Acceptance Criteria:**

**Given** a security
**When** I open its detail
**Then** I see its price history and its returns expressed across sym's Return Windows
(read from sym's return facts/views)

**Given** FX rates and fundamentals (incl. market cap in LCY and USD) where present
**When** the detail renders
**Then** they are shown
**And** missing values appear as gaps, never fabricated

### Story Q2.4: Attention queue (read-only)

As the Operator,
I want to see what sym flagged for review,
So that I know what needs attention (the view-half of UJ-3).

**Acceptance Criteria:**

**Given** open attention items
**When** I open the Attention area
**Then** items are grouped by type (`securities_review_queue`, `price_gaps`,
`membership_proposal` + related monitor logs) with the evidence sym recorded

**Given** an attention item
**When** I view it
**Then** it shows enough detail to decide without dropping to SQL
**And** acting on the item is NOT available in v1 (FR-11 deferred; this view is read-only)

### Story Q2.5: Validation results

As the Operator,
I want the latest `validate` results with drill-into failures,
So that I can see what's failing and where.

**Acceptance Criteria:**

**Given** the latest validation Run
**When** I open Validation
**Then** I see pass/fail per check, sourced from sym's validation logs

**Given** a failed check
**When** I view it
**Then** it links to the relevant entity/area where possible

### Story Q2.6: Universe heat map

As the Operator,
I want to view any universe as a heat map of its constituents,
So that I can see the universe's performance and composition at a glance.

**Acceptance Criteria:**

**Given** a selected universe and a selected return window
**When** I open its heat map
**Then** I see a treemap of the universe's constituents, each tile **sized by market cap
(USD)** and **colored by return** over that window, **grouped by GICS sector**

**Given** a constituent tile
**When** I hover it
**Then** it shows the security name, its return for the window, and its market cap

**Given** a constituent missing market cap, return, or GICS
**When** the heat map renders
**Then** the gap is shown explicitly (e.g. a neutral/unsized tile or an "unclassified"
group), never fabricated

**Given** the heat map
**When** it renders
**Then** all values are live reads of sym (membership + fundamentals + return facts +
gics_scd); the view is read-only

*(Sequenced after Q2.1 Overview; introduces the treemap charting primitive — the first
concrete use of the charts seam.)*

**Goal:** trigger sym Operations safely from the console as guarded background jobs with
status + history. **FRs:** FR-6, FR-7, FR-8, FR-9. **Deferred:** FR-11 (act-on-attention).
**NFRs:** NFR-1, NFR-4, NFR-6, NFR-7. **Depends on:** Q1 (+ Q2 attention views for context).
**Spike (Q3.1) leads and precedes AC-lock for Q3.3/Q3.4.**

### Story Q3.1: Foundation spike — execution model  *(enabling; precedes AC-lock)*

As the developer-operator,
I want a spike that proves and fixes the sym-Operation execution model,
So that the trigger/status stories rest on a decided, safe topology.

**Acceptance Criteria:**

**Given** a chosen topology (library-first per AR-Q2, executed out of the web process)
**When** the spike triggers a sym Operation
**Then** a job id returns immediately while the op runs outside the web request worker

**Given** two concurrent triggers of the same Operation
**When** both are submitted
**Then** one runs and the other is rejected by a single advisory lock keyed on the Operation

**Given** a triggered op
**When** it executes
**Then** it owns its own DB connection and commits durably; killing the request mid-flight
leaves no partial/corrupt commit

**Given** a running op
**When** status is requested
**Then** a status line is derivable from `pipeline_run_log` + a QRP heartbeat
("RUNNING · elapsed · last-completed op"); "% complete" is not claimed

**And** the spike documents the decided topology + the list of library-callable vs CLI-only
ops (this list scopes Q3.3)

### Story Q3.2: Run history

As the Operator,
I want the history of sym Runs with status/timing/summary,
So that I can see what ran and how it went.

**Acceptance Criteria:**

**Given** `pipeline_run_log`
**When** I open Run history
**Then** I see Runs (operation, start/end, outcome, summary), including Runs triggered
outside QRP (e.g. scheduled EOD)

**Given** the Run history
**When** it renders
**Then** the view is read-only

### Story Q3.3: Trigger a sym Operation as a guarded background job

As the Operator,
I want to trigger sym's idempotent Operations as background jobs that can't collide,
So that I can fix data from the browser (UJ-2).

**Acceptance Criteria:**

**Given** the supported Operations (the hand-run set from the spike's library-callable list
— e.g. recompute/delta/fx/validate/universe monitor|review|confirm)
**When** I trigger one
**Then** it runs out of the web process and a Run is recorded in `pipeline_run_log`, mapped
to sym's real entry point (no reimplementation)

**Given** a heavy/destructive-seeming Operation
**When** I trigger it
**Then** I must explicitly confirm before launch

**Given** an Operation already running
**When** I trigger the same Operation
**Then** it is blocked/queued with a clear message (the advisory lock)

**And** QRP never mutates sym's schema directly — the only sym writes are those the
Operation performs

### Story Q3.4: Run status & progress

As the Operator,
I want live status for an in-flight Run and a summary on completion,
So that I'm never left guessing.

**Acceptance Criteria:**

**Given** an in-flight Run
**When** I watch it
**Then** status (RUNNING · elapsed · last-completed op) refreshes without me reloading, in a
job panel that matches the design foundation (Q1.1)

**Given** completion
**When** the Run finishes
**Then** I see outcome + summary and the Run appears in history (Q3.2) without manual refresh

**Given** a failed Run
**When** it fails
**Then** its error is surfaced and idempotent re-run is offered as recovery
