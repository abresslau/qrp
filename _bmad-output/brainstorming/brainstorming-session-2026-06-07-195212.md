---
stepsCompleted: []
inputDocuments: []
session_topic: ''
session_goals: ''
selected_approach: ''
techniques_used: []
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** {{user_name}}
**Date:** {{date}}

## Session Overview

**Topic:** A web app for **maintenance + monitoring** of the sym warehouse, built on the existing schema/CLI — an operator console, not a new data layer.

**Framing:** sym is Module 1 (system of record). Per `docs/architecture-modules.md`, this app is a **consumer module**: it READS via the schema/contract + sym-as-library, and for maintenance it TRIGGERS sym's existing idempotent operations (`sym eod`/`delta`/`recompute`/`fx`/`validate`/`universe monitor|review|confirm`) and logs to `pipeline_run_log`. It never reimplements logic or mutates sym's schema.

**Goal:** high-level idea map first → refine interactively → a scoped first cut.

## Direction (decided)

Take the **longer route — a polished product**, and build it as the **multi-module platform console** (sym is Module 1; the app is the shell, with sym maintenance/monitoring as the first feature area; live-pricing / backtests / analytics slot in later as sections).

**Stack (Perplexity-style polish):** Next.js (App Router, React, TS) + Tailwind + shadcn/ui (Radix) frontend; **FastAPI over the sym library** for reads + actions; shared PostgreSQL; TanStack Query; a React charting lib; cmdk command palette. Monorepo of packages (matches `architecture-modules.md`).

**Architecture (consumer module):** the API READS sym tables/views (via the sym lib / SQL) and TRIGGERS sym's idempotent ops (`eod`/`delta`/`recompute`/`fx`/`validate`/`universe ...`), logging to `pipeline_run_log`; never mutates sym's schema. Pydantic models → generated TS types.

## Platform module map (the bigger project)

The console is the UI shell over a multi-module platform. Two tiers by data scope:

**Client-agnostic (shared reference — like sym):**
- **sym** — symbology, security master, prices/returns/FX/fundamentals (Module 1, exists).
- **Alternative data** — short interest, earnings/podcast transcripts, etc.

**Client-specific (tenant-scoped):**
- **Client data** — holdings, financing rates, reconciliations, NAV, share classes, fund structure.
- **Backtesting & optimization** — (name TBD) strategy sim + optimizer.
- **Portfolio analytics** — Sharpe, PnL, alpha, hit ratio, batting average, slugging ratio.

**Implication:** shared modules join on `sym_id`; client modules are keyed `(client_id/fund_id, sym_id)`. The console needs a **client/fund context switcher**; shared areas are global, client areas are scoped to the selected client. This is the pivotal design axis.

## Scope decision: client data = separate project

**Client-specific data (holdings, NAV, financing, recon, fund structure, share classes) is OUT** — a separate project with its own tenancy/auth/isolation. This console is **single-operator** (no client switcher, no RLS) for now.

Remaining console scope — all client-agnostic / research on shared data:
- **sym** (data/SoR) — build first.
- **Alt data** — short interest, transcripts, etc.
- **Backtest & optimize** (name TBD) — paper strategies on sym universes; *generates its own paper portfolios*.
- **Analytics** — Sharpe, PnL, alpha, hit/batting/slugging, measured on the backtest/paper portfolios (no external holdings needed).

The research stack (backtest → analytics) is self-contained on sym + alt-data; it doesn't depend on the deferred client-data module.

## Naming ideas

Existing: `sym` (data/SoR). Want: a platform/umbrella name + module names (esp. backtest/optimize), ideally a cohesive lowercase family.

**Module-name candidates by area:**
- Alt data: `signal` / `sig`, `echo` (transcripts/audio), `lore`, `fathom`
- Backtest & optimize: `forge`, `crucible`, `proving`, `anvil`, `lab`, `sim`
- Analytics: `edge` (alpha/skill metrics = the manager's edge), `lens`, `scorecard`, `ledger`

**Platform/umbrella candidates:** Vantage, Meridian, Sextant, Helix, Lattice, Atlas, Tessera, Praxis, Keystone.

**Recommended cohesive system:** umbrella **Meridian** (or Vantage/Sextant) over the family
`sym` (data) · `signal` (alt data) · `forge` (backtest+optimize) · `edge` (analytics).

## Platform name: Mirantia (provisional, editable)

Name = **Mirantia** for now, **editable later**. Implication: the name lives in a SINGLE config source of truth (e.g. `platform.toml` / `PLATFORM_NAME` env), read by both the API (settings) and the console (build/runtime config) — never hardcoded in components — so a rebrand is a one-line change.

## Focus: platform/console STRUCTURE

Proposed monorepo (per `architecture-modules.md` "monorepo of packages"):

```
mirantia/                      monorepo root
├─ apps/
│   └─ console/                Next.js (App Router, TS, Tailwind, shadcn/ui) — the UI shell
├─ services/
│   └─ api/                    FastAPI — modular routers, one per module
├─ packages/
│   ├─ sym/                    EXISTS: symbology/prices/returns/fx/fundamentals + migrations + CLI
│   ├─ signal/                 (later) alt data
│   ├─ forge/                  (later) backtest + optimize
│   ├─ edge/                   (later) analytics
│   └─ ui/                     shared React component lib (shadcn)
├─ db/                         shared Postgres; schema-per-module (sym.* signal.* forge.* edge.*), joined on sym_id
├─ platform.{toml,ts}          branding/name + theme (single source of truth)
└─ tooling                     uv workspace (Python) + pnpm/turbo (JS)
```

Key structural decisions (proposed defaults):
- **Repo:** one monorepo; sym folds in as `packages/sym` (history preserved). Polyrepo split only if cadences diverge.
- **API:** ONE FastAPI service with per-module routers (`/api/sym/...`, later `/signal`, `/forge`, `/edge`); split into services only if needed. Pydantic → generated TS types.
- **Schema:** shared Postgres, **schema-per-module** for boundaries; everything joins on `sym_id`. Each module owns its migrations.
- **Frontend:** Next.js route-groups per module area + a shared `ui` package; module-aware shell (areas light up as modules ship).
- **Reads vs actions:** API reads tables/views; actions trigger sym's idempotent CLI ops as logged background jobs (SSE progress).

## Module family (updated)

Analytics module renamed to an "opt-" word (metrics over backtest/optimisation):
`sym` (data) · `signal` (alt data) · `forge` (backtest + optimise) · **`optic`** (analytics/metrics) — `optima` is the optimisation-flavored alternative.

## DECIDED: module family

`sym` (data) · `signal` (alt data) · `forge` (backtest + optimise) · `optima` (analytics/metrics) — under platform **Mirantia** (editable). `optima` = plural of optimum; in optimisation the local/global *optima* are exactly what `forge` finds.

## CORRECTION: module family (final)

- `sym` — data / security master / prices / returns / FX / fundamentals
- `signal` — alternative data (short interest, transcripts, ...)
- `optima` — **backtesting & optimisation** (the local/global *optima* it searches for)
- `analytics` — **overall portfolio analytics** (Sharpe, PnL, alpha, hit / batting / slugging)

(`forge` dropped; `optima` is the backtest/optimise module; analytics is simply `analytics`.)

## Constraint: packages must be standalone + individually sellable

Monorepo now, but architected so each module is an independently deployable, **separately sellable** product (and a clean polyrepo split later is trivial). Rules that enforce it:

1. **Each package is self-contained:** own `pyproject`/`package.json`, **own version** (independent semver), own **migrations**, tests, docs/README, **own API router**, own **console UI slice**. No relative cross-package imports — depend on *published* package versions (workspace protocol now → registry later).
2. **Depend on contracts, not implementations.** A thin **`contract`** package (sym_id + the published schema/API types + a `sym-client` SDK) is the only thing downstream modules import. `sym` *implements* it; `optima`/`signal`/`analytics` *depend on the contract*, never on sym's internals. This seam is what makes a component sellable/swappable on its own.
3. **Cross-module data access only via published views / the API** — never another module's raw tables. So a module can later point at a *remote* sym instance.
4. **Console = shell + per-module UI bundles** (`console-sym`, `console-optima`, …) loaded via a **module registry + entitlement** (a licence enables a module's API + UI). Selling a component = shipping its package + console bundle + a key.

**Dependency graph (acyclic) / product bundles:**
- `sym` — base, standalone (sellable alone).
- `signal` → depends on `contract` (needs sym_id). Bundle: sym + signal.
- `optima` → depends on `contract` (universes/prices/returns), optionally `signal`. Bundle: sym + optima.
- `analytics` → depends on `optima` output + `contract`. Bundle: sym + optima + analytics.
`sym` (or a sym-compatible data layer) is the foundation; everything else is an add-on tier.

## SETTLED — scaffolding

Forks resolved: (1) scaffold `contract` + `services/api` + `apps/console` **alongside** the existing sym (against its DB); fold sym into `packages/sym` later. (2) **Per-module FastAPI routers** over each package, composed into one service; console talks only to the API + contract types. Standalone/sellable discipline + contract seam + shell/entitlement as captured above. → Proceed to scaffold the Mirantia monorepo skeleton.
