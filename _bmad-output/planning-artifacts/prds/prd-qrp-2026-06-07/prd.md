---
title: QRP — Quant Research Platform (Console + API)
status: draft
created: 2026-06-07
updated: 2026-06-07
inputDocuments:
  - _bmad-output/brainstorming/brainstorming-session-2026-06-07-195212.md
  - _bmad-output/planning-artifacts/prds/prd-sym-2026-05-19/prd.md (structural model)
  - docs/architecture-modules.md
---

# PRD: QRP — Quant Research Platform
*"QRP" (Quant Research Platform) is a provisional name, editable (lives in `platform.toml`).*

## 0. Document Purpose

This PRD defines the functional and non-functional requirements for **QRP**, a
web console + API that sits on top of the existing **sym** warehouse. The audience is
the builder (Andre) and any future architecture/epics workflows that consume this
document. It is structured Glossary-first: features are grouped, with globally-numbered
Functional Requirements (FR-N) nested under them, cross-cutting NFRs in their own
section, and inferred decisions tagged inline `[ASSUMPTION]` and indexed in §12.

QRP is the **operator console + service layer** for a multi-module quant
platform. sym (the security master + market-data warehouse) already exists and is the
first module surfaced. This PRD covers the **platform shell** and the **sym console
area** as v1, and specifies the future modules (`macro`, `altdata`, `signal`, `backtest`,
`optimiser`, `portfolios`, `analytics`) at vision/roadmap resolution so the architecture
is shaped for them now.

Technical direction (Next.js console, FastAPI API, schema-per-module, background jobs)
and rejected alternatives live in `addendum.md` — this PRD states capabilities, not
implementation.

---

## 1. Vision

QRP turns the sym warehouse from a CLI-and-SQL tool into a **polished operator
console** — and grows into the single front end for an entire personal quant research
platform. Today, keeping sym healthy (running EOD, spotting stale universes, triaging
review queues, recomputing returns/FX) means remembering CLI invocations and reading
log tables by hand. QRP makes the warehouse's health legible at a glance and lets
the operator run its maintenance operations safely from the browser, with live
progress and a durable run history.

Beyond maintenance, QRP is the shell into which every future research capability
plugs: load a **client's portfolio** (as weights) and measure it against the market
with a full analytics suite (Sharpe, PnL, alpha, hit/batting/slugging); later, run
backtests (`backtest`) and optimisation (`optimiser`) and fold in macroeconomic data (`macro`),
alternative data (`altdata`), and derived signals (`signal`). Each
capability is a module that "lights up" as an area of the same console, all joined to
sym's vendor-neutral identity spine (`sym_id` = Composite FIGI).

QRP is built for **one operator — its owner**. It is not a product to sell and
not multi-tenant. That keeps v1 lean: no licensing, no tenant isolation, no client
auth — just a fast, trustworthy cockpit over data the operator already owns. The
discipline that matters is **safety and faithfulness to sym**: QRP only ever
*reads* sym's data or *triggers sym's own idempotent operations*. It never reimplements
sym's logic and never mutates sym's schema — so sym's reconstructability invariant is
preserved no matter what happens in the UI.

---

## 2. Target User

### 2.1 Primary Persona

**Andre — the operator-builder.** A quant practitioner who built sym and runs it for
personal research (and to analyse clients' portfolios). Comfortable with the CLI and
SQL, but wants the daily-driver ergonomics of a real console: one place to see whether
last night's data landed, to fix what didn't, and — increasingly — to do research on
top of the data rather than just maintain it. He is the *only* user of the system.

### 2.2 Jobs To Be Done

- **Know the warehouse is healthy** — at a glance, without writing a query: is data
  current, did overnight steps succeed, what needs attention?
- **Fix problems without leaving the browser** — trigger the right sym operation
  (recompute, delta, FX backfill, validation, universe review) and watch it run.
- **Triage attention items** — work through review queues, price gaps, and universe
  membership proposals deliberately and reversibly.
- **Trust what he sees** — every number traceable to sym; every action logged; nothing
  silently mutated.
- **(Roadmap) Measure portfolios** — load a client's portfolio as weights and see how
  it performed against a benchmark, across sym's return windows.
- **(Roadmap) Research** — backtest and optimise strategies on sym universes; bring in
  alternative-data signals.

### 2.3 Non-Users (v1)

- **Clients** — clients never log in. The operator analyses *their* portfolios; clients
  are data, not users.
- **Other practitioners / buyers** — QRP is not sold or distributed.
- **Anonymous / public** — not a public web app.

### 2.4 Key User Journeys

- **UJ-1. Andre's morning health check.** Andre opens QRP to the Overview. In one
  screen he sees the latest session date, freshness per data area (prices, returns, FX,
  fundamentals), the last EOD run's outcome, and a count of open attention items. A
  universe shows a stale "as-of" badge and validation flags one failed check. He knows
  in seconds what's wrong without opening a terminal. *Realizes FR-2, FR-3, FR-12.*

- **UJ-2. Andre fixes a gap and watches it run.** From the stale universe, Andre
  triggers the relevant sym operation (e.g. `recompute` / `delta`). A job panel opens
  with live progress streamed from the running op; on completion it shows the summary
  (rows touched, duration) and the new run appears in the run history, sourced from
  `pipeline_run_log`. He re-checks Overview and the freshness badge is green.
  *Realizes FR-7, FR-8, FR-9.*

- **UJ-3. Andre triages the attention queue.** Andre opens the Attention area: securities
  pending review, detected price gaps, and proposed universe membership changes. He
  inspects a proposal's evidence, confirms it (which triggers sym's
  `universe confirm`), and dismisses a false-positive gap. Each action is logged and
  reversible through sym's own mechanisms. *Realizes FR-10, FR-11.*

- **UJ-4. (Roadmap) Andre reviews a client portfolio.** Andre selects a client and one
  of their portfolios (a time series of weights). QRP shows the portfolio's
  return across standard windows and the full analytics suite versus a chosen
  benchmark. *Realizes FR-14, FR-15, FR-17.*

---

## 3. Glossary

*Downstream workflows and readers use these terms exactly. FRs, UJs, and SMs use these
terms verbatim — no synonyms elsewhere in the PRD.*

- **QRP (the Platform)** — the console + API product this PRD defines. "QRP" =
  Quant Research Platform, a provisional, configurable name; the concept is stable.
- **Console** — the web UI (single front end for all modules).
- **API** — the service layer the Console talks to; reads sym and triggers sym
  operations.
- **Operator** — the single human user (the owner). The only authenticated actor.
- **Module** — a bounded capability area surfaced as a Console area and an API router
  group: `sym`, `macro`, `altdata`, `signal`, `backtest`, `optimiser`, `portfolios`,
  `analytics`. A boundary for engineering, not a sellable unit.
- **Module Area** — a Module's section of the Console (its navigation entry + screens).
- **Feature Toggle** — config flag (in `platform.toml`) that enables/disables a Module
  Area and its API routes. Not a licence.
- **sym** — the existing security-master + market-data Module (system of record).
- **Macro Data (macro Module)** — traditional macroeconomic / official public-sector
  data: central-bank policy rates (e.g. Fed funds rate), FOMC/ECB/BoE statements &
  minutes, balance-sheet data, monetary aggregates, economic projections, inflation &
  financial-stability reports. Client-agnostic shared reference, like sym. **Distinct
  from Alternative Data:** macro is traditional/official; a dataset *derived* from a
  macro source (e.g. NLP sentiment of FOMC speeches) is Alternative Data, not Macro Data.
- **Alternative Data (altdata Module)** — *raw* datasets outside traditional financial
  reporting / official statistics: card transactions, satellite imagery, web-scraping,
  mobile-app usage, geolocation, social sentiment, shipping/logistics, job postings.
- **Signal (signal Module)** — *derived* investment signals: features, factors, and
  alpha signals computed from the underlying data (sym + macro + altdata). This is where
  a feature derived from a macro source (e.g. NLP sentiment of FOMC speeches) or from
  alt-data lives — `signal` is the derivation/identification module, distinct from the
  raw `altdata` and `macro` modules that feed it.
- **sym warehouse** — sym's PostgreSQL database (securities, prices, returns, FX,
  fundamentals, universes, and its log/queue tables).
- **sym_id** — the Composite FIGI; sym's permanent, vendor-neutral security identity
  and the universal join key across Modules.
- **sym Operation** — one of sym's existing idempotent CLI operations (`eod`, `delta`,
  `recompute`, `fx`, `validate`, `universe monitor|review|confirm`, etc.). QRP
  triggers these; it never reimplements them.
- **Run** — a single execution of a sym Operation triggered via QRP, with live
  progress and a persisted record (in sym's `pipeline_run_log`).
- **Freshness** — how current a data area is, expressed against the latest expected
  session/as-of date.
- **Attention Item** — something needing operator review: an entry in a sym review
  queue (`securities_review_queue`), a detected `price_gaps` row, or a universe
  membership proposal (`membership_proposal`).
- **Universe** — a sym-defined set of securities (e.g. an index), with point-in-time
  membership and resolution status.
- **Return Window** — one of sym's standard lookback windows (calendar/session/
  trailing/inception/period) used to express performance.
- **Benchmark** — a sym Universe or index whose return series a Portfolio is measured
  against.
- **Client** — an entity whose Portfolios the Operator analyses. Data, not a user.
- **Portfolio** — a Client's holdings expressed as a time series of effective-dated
  **weight vectors** over sym_id constituents (weights sum to ~1). *First cut is
  weights only; share quantities and transaction ledgers are later enhancements.*
- **Holding (Weight)** — one constituent's weight in a Portfolio at an effective date.
- **Analytics Metric** — a computed performance/skill measure: time-weighted Return,
  PnL, Sharpe ratio, alpha, hit ratio, batting average, slugging ratio.

---

## 4. Features

> **v1 = the Platform shell (§4.1) + the sym Module Area (§4.2–§4.5).** The
> `portfolios`, `analytics`, `backtest`, `optimiser`, `altdata`, `macro`, and `signal`
> features (§4.6–§4.12) are specified at roadmap resolution to shape the architecture;
> they are **not built in v1** (see §7 MVP Scope).

### 4.1 Platform Shell & Module Framework  *(v1)*

**Description:** The Console is a single application with a persistent shell —
navigation, a command palette, theming, and branding — that hosts Module Areas. Which
areas appear is driven by per-module Feature Toggles in `platform.toml`, so unfinished
modules stay hidden and a future module lights up by flipping a flag. The platform name
and theme are read from one config source of truth, never hardcoded. The API mirrors
this: a module's routes are mounted only when its Feature Toggle is on.

**Functional Requirements:**

#### FR-1: Module-aware shell driven by config

The Operator sees a Console shell whose navigation lists exactly the Module Areas whose
Feature Toggle is enabled.

**Consequences (testable):**
- With only `sym` enabled, the nav shows Overview + sym; no other-module entries appear.
- Enabling a module's Feature Toggle makes its nav entry and API routes available
  without code changes to the shell.
- The platform name and theme shown in the Console come from the single config source;
  changing the name there changes it everywhere (no hardcoded occurrences).

#### FR-2: Command palette & fast navigation

The Operator can open a command palette to jump to any Module Area, screen, or
entity, and to launch common actions.

**Consequences (testable):**
- A keyboard shortcut opens the palette from anywhere.
- The palette can navigate to each enabled area and can launch at least the operations
  exposed in FR-7.

### 4.2 sym — Overview & Freshness  *(v1)*

**Description:** The landing area for the sym Module: a health-at-a-glance dashboard.
It summarises warehouse scale (securities, universes, priced securities), the latest
session date, per-area Freshness, the outcome of the most recent EOD/maintenance Runs,
and a roll-up of open Attention Items. It answers UJ-1 without the Operator writing a
query.

**Functional Requirements:**

#### FR-3: Warehouse Overview

The Operator can view headline warehouse facts and per-area Freshness on one screen.
Realizes UJ-1.

**Consequences (testable):**
- Shows counts for securities, universes, and priced securities, and the latest
  session date, matching the sym warehouse at load time.
- Shows Freshness per data area (prices, returns, FX, fundamentals) relative to the
  latest expected session/as-of date, with a clear current/stale indicator.
- Surfaces the most recent Run's status and a count of open Attention Items, each
  linking to its detail area.
- All figures are reads of the sym warehouse; the Overview never writes to it.

### 4.3 sym — Data Explorer  *(v1)*

**Description:** Read-only browsing of sym's core entities so the Operator can inspect
what's in the warehouse: securities (by sym_id, name, exchange, currency, status),
universes and their membership + resolution status, prices, returns across Return
Windows, FX rates, and fundamentals. This is inspection, not editing.

**Functional Requirements:**

#### FR-4: Browse securities & universes

The Operator can list and inspect securities and universes, including a universe's
members and their resolution status.

**Consequences (testable):**
- Securities are listable and individually viewable with their core master fields,
  keyed by sym_id.
- Each universe shows its members with resolved/total counts matching the sym
  warehouse, and per-member resolution status.
- Lists support paging/filtering sufficient to navigate thousands of securities without
  loading all at once.

#### FR-5: Inspect prices, returns, FX, fundamentals

The Operator can view a security's price history, its returns across Return Windows,
relevant FX rates, and its fundamentals snapshots.

**Consequences (testable):**
- A security view shows its prices and its returns expressed across sym's Return
  Windows, read from sym's return facts/views.
- FX rates and fundamentals (incl. market cap in LCY and USD) are viewable where
  present; missing values are shown as gaps, never fabricated.

#### FR-23: Universe heat map

The Operator can view any Universe as a heat map — a treemap of its constituents, sized by
market cap, colored by return over a selected Return Window, grouped by GICS sector.

**Consequences (testable):**
- Tiles are sized by `market_cap_usd` and colored by the constituent's return over the
  chosen Return Window, grouped by GICS sector (from sym).
- Hover reveals name, return, and market cap; constituents missing market cap / return /
  GICS are shown explicitly (neutral tile / "unclassified" group), never fabricated.
- All values are live reads of sym (membership + fundamentals + return facts + GICS); the
  view is read-only.

**Notes:** Realizes part of the "polished, Perplexity-finance-style" target; introduces the
treemap charting primitive. v1 (Q2), sequenced after the Overview.

### 4.4 sym — Operations (Run & Monitor)  *(v1)*

**Description:** The maintenance half. The Operator can trigger sym's idempotent
Operations from the Console as background Runs, watch live progress, and review a
durable Run history. QRP shells out to / invokes sym's existing operations; it
does not reimplement them. Every Run is recorded in sym's `pipeline_run_log`. Because
operations are idempotent and sym-owned, re-running is safe.

**Functional Requirements:**

#### FR-6: Browse run history

The Operator can view the history of sym Runs with status, timing, and summary, sourced
from `pipeline_run_log`.

**Consequences (testable):**
- The Run history reflects `pipeline_run_log` entries (including Runs triggered outside
  QRP, e.g. scheduled EOD).
- Each Run shows operation, start/end, outcome (success/failure), and a result summary.

#### FR-7: Trigger sym Operations

The Operator can trigger sym's idempotent Operations (e.g. `eod`, `delta`, `recompute`,
`fx`, `validate`, `universe monitor|review|confirm`) from the Console. Realizes UJ-2.

**Consequences (testable):**
- Each exposed Operation maps to sym's actual CLI/library entry point with no
  reimplementation of its logic.
- Triggering creates a Run recorded in `pipeline_run_log`.
- Destructive-seeming or long operations require an explicit confirm before launch.
- QRP never mutates sym's schema directly; the only writes to sym are those sym's
  own Operations perform.

#### FR-8: Live Run progress

The Operator sees live progress for an in-flight Run and a final summary on completion.
Realizes UJ-2.

**Consequences (testable):**
- Progress updates stream to the Console while the Operation runs (not only on
  completion).
- On completion the Console shows outcome + summary and the Run appears in history
  (FR-6) without a manual refresh.

#### FR-9: Concurrency & safety guards

The Operator is prevented from launching conflicting concurrent Runs of the same
Operation.

**Consequences (testable):**
- Attempting to start an Operation already running is blocked or queued with a clear
  message.
- A failed Run surfaces its error; because Operations are idempotent, re-running is
  offered as the recovery path.

### 4.5 sym — Attention Queues  *(v1)*

**Description:** A worklist for the things sym flags for human judgement: securities
pending review, detected price gaps, and universe membership proposals. The Operator
triages each item and acts on it through sym's own review/confirm Operations, keeping
actions reversible and logged.

**Functional Requirements:**

#### FR-10: View attention items

The Operator can see open Attention Items grouped by type (review queue, price gaps,
membership proposals) with the evidence sym recorded. Realizes UJ-3.

**Consequences (testable):**
- Items reflect `securities_review_queue`, `price_gaps`, and `membership_proposal`
  (and related monitor logs) in the sym warehouse.
- Each item shows enough detail/evidence to decide without dropping to SQL.

#### FR-11: Act on attention items

The Operator can resolve an Attention Item (e.g. confirm/dismiss a membership proposal,
acknowledge a gap) via sym's corresponding Operation. Realizes UJ-3.

**Consequences (testable):**
- Resolving an item triggers the appropriate sym Operation (e.g. `universe confirm`)
  and is recorded as a Run / log entry.
- Resolution outcomes are reflected back in the queue (item leaves the open list).
- No attention state is changed except through sym's own mechanisms.

#### FR-12: Validation results

The Operator can view the latest `validate` results and drill into failures. Realizes
UJ-1.

**Consequences (testable):**
- Shows the most recent validation Run's pass/fail per check, sourced from sym's
  validation logs.
- Failed checks link to the relevant entity/area where possible.

### 4.6 portfolios — Clients & Portfolios  *(roadmap, post-v1)*

**Description:** Load a Client's Portfolio as a time series of effective-dated weight
vectors over sym_id constituents, and view it. Constituents resolve to sym_id via the
security master so the Portfolio plugs into sym's market data. *Weights-first: no share
quantities or transaction ledgers in the first cut.* [ASSUMPTION: portfolios are
uploaded as files (CSV/Excel); constituents identified by a sym-resolvable key
(ticker/ISIN/FIGI).]

**Functional Requirements:**

#### FR-13: Manage clients & portfolios

The Operator can create Clients and Portfolios and select a Client/Portfolio context.

**Consequences (testable):**
- Clients and their Portfolios are listable and selectable; selection scopes the
  portfolios/analytics areas (ordinary navigation, not security isolation).

#### FR-14: Load portfolio weights over time

The Operator can upload a Portfolio's holdings as effective-dated weight vectors;
constituents resolve to sym_id. Realizes UJ-4.

**Consequences (testable):**
- An upload produces a time series of weight vectors per Portfolio.
- Each constituent is resolved to a sym_id; unresolved constituents are flagged as
  gaps (never silently dropped or faked).
- Weights per effective date are validated (e.g. sum within tolerance of 1; residual/
  cash handled explicitly).

### 4.7 analytics — Portfolio Analytics  *(roadmap, post-v1)*

**Description:** Measure a Portfolio against a Benchmark using the **full** Analytics
Metric set, derived from weighted sym constituent returns across Return Windows.

**Functional Requirements:**

#### FR-15: Portfolio return & PnL

The Operator can view a Portfolio's time-weighted Return and PnL across Return Windows.
Realizes UJ-4.

**Consequences (testable):**
- Portfolio Return is computed from constituent weights × sym constituent returns over
  each Return Window.
- Results use sym's existing windows and FX conventions; missing inputs are flagged,
  not fabricated.

#### FR-16: Risk & skill metrics

The Operator can view Sharpe, alpha, hit ratio, batting average, and slugging ratio for
a Portfolio versus a selected Benchmark.

**Consequences (testable):**
- Each metric is computed against a sym-sourced Benchmark the Operator selects.
- Metric definitions are documented and reproducible from sym inputs.

#### FR-17: Benchmark selection

The Operator can choose the Benchmark (a sym Universe/index) a Portfolio is measured
against. Realizes UJ-4.

**Consequences (testable):**
- Available Benchmarks come from sym Universes/indexes; the chosen Benchmark drives
  alpha/batting/relative metrics.

### 4.8 backtest — Backtesting  *(roadmap, vision-level)*

**Description:** Run a *defined* paper strategy / portfolio over a sym Universe and date
range and produce its historical track record (a paper Portfolio = weights over time)
that the analytics Module can measure. The evaluation engine the optimiser builds on.
Vision level only; detailed FRs deferred to a later PRD/epic. [NON-GOAL for MVP]

#### FR-18: Run a backtest (vision)

The Operator can define and run a paper strategy over a sym Universe and date range,
producing a paper Portfolio (weights over time) consumable by analytics.

### 4.9 optimiser — Optimisation  *(roadmap, vision-level)*

**Description:** Given an objective and constraints over a sym Universe (and optionally
`signal` factors), search for optimal weights — the optimiser. Its output is a Portfolio
that `backtest` can simulate and `analytics` can measure; the optimiser uses backtests to
score candidate allocations. Vision level only; deferred. [NON-GOAL for MVP]

#### FR-22: Optimise an allocation (vision)

The Operator can run an optimisation (objective + constraints over a sym Universe, with
optional `signal` inputs) that produces optimal weights as a Portfolio.

**Consequences (testable):**
- The optimisation is reproducible from its objective, constraints, universe, and inputs.
- The resulting weights are a Portfolio consumable by `backtest` and `analytics`.

### 4.10 altdata — Alternative Data  *(roadmap, vision-level)*

**Description:** Ingest and surface *raw* alternative datasets (card transactions,
satellite, web-scraping, geolocation, social sentiment, shipping/logistics, job
postings) keyed to sym_id, for use by the `signal` and research modules. Vision level
only; deferred. [NON-GOAL for MVP]

#### FR-19: Surface an alt-data series (vision)

The Operator can view a raw alternative-data series joined to a security by sym_id.

### 4.11 macro — Macroeconomic & Central-Bank Data  *(roadmap, vision-level)*

**Description:** Ingest and surface traditional **Macro Data** — central-bank and
official public-sector releases (policy rates, FOMC/ECB/BoE statements & minutes,
balance sheets, monetary aggregates, economic projections, inflation & financial-
stability reports) — as a client-agnostic shared-reference Module alongside sym. Macro
series are time series of economic indicators (not security-level), available to
research and analytics. Raw official releases live here; datasets *derived* from them
(e.g. NLP sentiment of FOMC speeches) belong to `signal` (the Signal module), not macro.
Vision level only; detailed FRs deferred to a later PRD/epic. [NON-GOAL for MVP]

#### FR-20: Surface a macro series (vision)

The Operator can view a Macro Data series (e.g. a policy-rate or monetary-aggregate
time series) and reference it in research/analytics.

**Consequences (testable):**
- Macro series are stored with their official source attribution and release/as-of
  dating; missing observations are gaps, never fabricated.
- Macro series are time series (by indicator/date), not keyed by sym_id; analytics may
  reference them as context/factors.

### 4.12 signal — Signal Identification  *(roadmap, vision-level)*

**Description:** Compute and surface *derived* investment **Signals** — features,
factors, alpha signals — from the underlying data (sym + macro + altdata). This is the
derivation/identification module: e.g. an NLP-sentiment signal from FOMC speeches, a
factor built from alt-data, or a composite signal across sources. Distinct from the raw
`altdata`/`macro` modules that feed it. Vision level only; deferred. [NON-GOAL for MVP]

#### FR-21: Identify / surface a signal (vision)

The Operator can define and view a derived Signal computed from sym + macro + altdata
inputs (e.g. a factor or sentiment series), with its inputs and method traceable.

**Consequences (testable):**
- A Signal is reproducible from its named inputs (sym/macro/altdata) and method; inputs
  are traceable, never fabricated.
- Signals are consumable by `optimiser`/`backtest` (as strategy inputs) and `analytics`
  (as factors).

---

## 5. Cross-Cutting NFRs

- **NFR-1 — Faithfulness to sym (reconstructability).** QRP MUST NOT mutate sym's
  schema or data except through sym's own idempotent Operations. All other interaction
  with the sym warehouse is read-only. This preserves sym's reconstructability
  invariant regardless of UI actions.
- **NFR-2 — No reimplementation.** Business logic (returns, FX, validation, universe
  resolution, market cap) is never reimplemented in QRP; the Console/API read
  sym's results or trigger sym's Operations.
- **NFR-3 — Single-operator, no auth (v1).** v1 has one Operator, no authentication,
  and no multi-tenancy/RLS. The instance is protected by running locally / on a trusted
  host and not being exposed publicly. Auth is revisited only if it is ever exposed
  beyond localhost. (Decided 2026-06-07.)
- **NFR-4 — Action safety.** Operation triggers are explicit and auditable: confirms
  for heavy/destructive-seeming ops, every Run logged, idempotent re-runs as the
  recovery path. No hidden writes.
- **NFR-5 — Responsiveness.** Read screens (Overview, explorer lists) render quickly on
  a warehouse of thousands of securities and hundreds of thousands of FX/return rows
  (paging/filtering rather than full loads). [ASSUMPTION: interactive p95 < ~1s for
  standard read screens on the current data scale.]
- **NFR-6 — Live progress.** Long Runs stream progress rather than blocking the UI or
  forcing manual refresh.
- **NFR-7 — Observability.** Every triggered Run is traceable end-to-end (request →
  `pipeline_run_log` entry → outcome). The Console never shows a number it cannot trace
  to a sym source.
- **NFR-8 — Type-safe contract.** The API exposes typed schemas so the Console and API
  cannot silently drift (generated types). *(How: addendum.)*
- **NFR-9 — Configurable identity.** Platform name/branding/theme come from one config
  source of truth; rebrand is a one-line change.
- **NFR-10 — Modularity.** A new Module Area can be added (nav + routes + screens)
  without modifying the shell beyond enabling its Feature Toggle.

---

## 6. Constraints & Guardrails

- **Consumer-only of sym.** QRP is a consumer Module per `docs/architecture-
  modules.md`: read + trigger, never own sym's data.
- **Cost / footprint.** Single-operator; no cloud-scale infrastructure assumed. Runs on
  the operator's machine/host against the existing Postgres. [ASSUMPTION: local-first
  deployment for v1.]
- **Data governance.** Client Portfolio data (weights) is the only client-specific data
  stored; heavier client data (NAV, financing, recon, fund structure) is explicitly out
  (separate project). No client PII beyond what a portfolio weight file contains.

---

## 7. MVP Scope

### 7.1 In Scope (v1)

- **Platform shell** — module-aware navigation, command palette, branding/theme from
  config, Feature Toggles (§4.1).
- **sym Module Area** — Overview & Freshness (§4.2), Data Explorer (§4.3), Operations
  run/monitor with live progress + run history (§4.4), Attention Queues + validation
  results (§4.5).
- **API** over the sym warehouse — typed read endpoints + Operation-trigger endpoints
  with streamed progress; reads tables/views, triggers sym Operations, logs to
  `pipeline_run_log`.

### 7.2 Out of Scope for MVP

- **portfolios, analytics, backtest, optimiser, altdata, macro, signal Module Areas** —
  specified as roadmap; deferred to post-v1. [NOTE FOR PM: `portfolios` + `analytics` is
  the most likely v2, since "run clients' portfolios" is the load-bearing next capability.]
- **Act-on-attention (FR-11)** — deferred to post-v1 (decided 2026-06-07). v1 attention
  is read-only (FR-10 view + FR-12 validation); triggering sym Operations (FR-6/7/8/9)
  stays in v1.
- **Multi-tenancy / client login / RLS** — single operator only.
- **Client-data ingestion** (NAV, financing rates, reconciliations, fund structure,
  share classes) — separate project.
- **Share-quantity holdings & transaction ledgers** — portfolios are weights-first;
  these are later enhancements.
- **Selling/licensing/entitlement** — not a product; Feature Toggles are not licences.
- **sym schema changes** — any new sym capability is sym's own PRD/epics, not this one.

---

## 8. Success Metrics

*Owner-operated tool; metrics are about the operator's lived experience and safety, not
adoption.*

**Primary**
- **SM-1 — Health legibility.** The Operator can determine warehouse health and what
  needs attention from the Overview alone, without dropping to SQL, in normal daily use.
  Validates FR-3, FR-12.
- **SM-2 — Maintenance from the console.** Routine sym maintenance (recompute/delta/fx/
  validate/universe triage) is performed from QRP rather than the terminal, with
  every Run logged. Validates FR-7, FR-8, FR-11.

**Secondary**
- **SM-3 — Traceability.** Every figure shown traces to a sym source and every action
  to a `pipeline_run_log` Run (no untraceable state). Validates NFR-7, FR-6.

**Counter-metrics (do not optimize)**
- **SM-C1 — Don't trade safety for convenience.** Reducing clicks/confirmations must not
  enable an unlogged or schema-mutating write. Counterbalances SM-2. A faster console
  that bypasses sym's Operations or logging is a regression, not progress.
- **SM-C2 — Don't reimplement sym.** Adding console-side computation that duplicates
  sym logic (to "speed up" a screen) counterbalances SM-1/SM-3 and violates NFR-2.

---

## 9. Non-Goals (Explicit)

- QRP is **not** a multi-tenant SaaS, **not** for sale, and **not** client-facing.
- QRP does **not** own or compute market data — sym does.
- QRP is **not** a replacement for sym's CLI; it's a console over the same
  Operations (the CLI remains valid).
- v1 is **not** trying to deliver portfolios/analytics — those are roadmap.

---

## 10. Open Questions

1. **Background-job mechanism** — in-process async task runner vs a lightweight queue
   for Runs? (Architecture decision; affects FR-8 progress streaming.)
2. ~~sym invocation boundary~~ **DECIDED (2026-06-07): library-first.** The API invokes
   sym as a library (in-process function calls) to trigger Operations; DB reads stay
   direct; subprocess only for any CLI-only op.
3. ~~Auth posture for v1~~ **DECIDED (2026-06-07): no auth in v1** (localhost / trusted
   host; see NFR-3).
4. **Portfolio file format(s)** — exact upload schema for weights + the constituent
   identifier(s) accepted for sym_id resolution (FR-14). Deferred to portfolios PRD.
5. **Benchmark coverage** — are sym's universes/indexes sufficient as Benchmarks for
   all portfolios analysts will load, or is a custom-benchmark capability needed? (FR-17.)
6. **Monorepo fold-in timing** — keep console/API alongside sym (read its DB / import
   it) for v1, or fold sym into the monorepo as a package during v1? **OPEN (Andre
   undecided).** Working default: **alongside** (do not fold in yet); nothing committed.
   Revisit at the architecture step. (Addendum A.)

---

## 11. Roadmap (post-v1 sequencing)

1. **v1** — Platform shell + sym Module Area (this PRD's MVP).
2. **v2 (most likely)** — `portfolios` (load weights over time) + `analytics` (full
   metric set vs benchmark): the "run clients' portfolios" capability.
3. **v3+** — `macro` (central-bank / macroeconomic data) + `altdata` (alternative data)
   as shared-reference data modules; `signal` (derived signals/factors over sym + macro +
   altdata); and the research engine `backtest` (run defined strategies) + `optimiser`
   (search optimal weights) over them.

---

## 12. Assumptions Index

- §4.6 — Portfolios are uploaded as files (CSV/Excel); constituents identified by a
  sym-resolvable key (ticker/ISIN/FIGI).
- §5 NFR-5 — Interactive p95 < ~1s for standard read screens at current data scale.
- §6 — Local-first deployment for v1 (no cloud-scale infra).

*(Resolved 2026-06-07, no longer assumptions: sym invocation boundary → library-first
(§10 Q2); v1 auth → none (NFR-3).)*

---

*End of PRD draft. Inferred decisions are tagged `[ASSUMPTION]` (indexed §12) and open
forks are in §10 — both for review before this feeds `bmad-create-architecture` /
`bmad-create-epics-and-stories`.*
