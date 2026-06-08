# Addendum — QRP PRD

Depth that belongs downstream (architecture / solution design) or earned a place
but does not fit the capability-focused PRD. The PRD states *what*; this captures
*how* and *why-not*.

## A. Technical direction (for the architecture workflow, not committed by the PRD)

- **Console:** Next.js (App Router, React, TypeScript) + Tailwind + shadcn/ui (Radix).
  TanStack Query for server state; a React charting lib; `cmdk` command palette.
- **API:** ONE FastAPI service with **per-module routers** (`/api/sym/...`, later
  `/api/portfolios`, `/api/analytics`, ...). Pydantic models → generated TypeScript
  types so the console and API never drift. Split into multiple services only if
  cadences diverge.
- **Data:** shared PostgreSQL. sym owns its existing schema. New modules
  (portfolios, analytics, ...) get their **own schema** (`portfolios.*`, ...),
  joined to sym on `sym_id` (composite FIGI). Each module owns its migrations
  (Sqitch, matching sym's convention).
- **Consumer posture:** the API READS sym tables/views (via the sym library / SQL)
  and TRIGGERS sym's idempotent CLI ops (`eod`/`delta`/`recompute`/`fx`/`validate`/
  `universe ...`) as background jobs, streaming progress (SSE) and logging to
  `pipeline_run_log`. It never reimplements sym logic or mutates sym's schema.
- **Monorepo:** one repo. sym folds in as a package later (history preserved); for
  now the console + API are scaffolded alongside the existing sym repo and read its DB.
- **Branding:** platform name lives in a single source of truth (`platform.toml`),
  read by both API and console — a rebrand is a one-line change.
- **Background jobs:** sym ops are long-running; run them as tracked async jobs with
  live progress and a persisted run history. Mechanism (in-process task runner vs a
  queue) is an architecture decision.

## B. Rejected / reversed alternatives (provenance)

- **Individually-sellable modules + entitlement/licensing** (brainstorm §"Constraint:
  packages must be standalone + individually sellable"). **Reversed** — QRP is
  owner-operated, not for sale. Module boundaries remain for engineering hygiene
  (clear ownership, own schema/migrations) but carry no commercial/licensing weight.
- **A thin `contract` package (sym_id types + sym-client SDK)** as the only thing
  downstream modules may import. **Dropped** — without the sellability driver it is
  unneeded ceremony; the API reads sym directly. May revisit if a polyrepo split
  ever happens.
- **Client-data module in scope** (NAV, financing rates, reconciliations, fund
  structure, share classes). **Remains out** — separate project with its own
  tenancy/auth/isolation. QRP only loads portfolio *weights* and runs analytics.
- **Multi-tenant client switcher + RLS.** Out for now — single operator. A
  client/portfolio selector exists as ordinary navigation, not security isolation.
- **Names considered:** umbrella — Meridian, Vantage, Sextant, Helix, Lattice, Atlas,
  Tessera, Praxis, Keystone. Modules — `forge`/`crucible` (backtest), `edge`/`optic`/
  `lens` (analytics), `echo`/`lore`/`fathom` (alt data). **Settled:** platform
  *QRP* (provisional); modules `sym` · `macro` · `altdata` · `signal` · `backtest` ·
  `optimiser` · `portfolios` · `analytics`.

- **`backtest` vs `optimiser`.** `backtest` = run a *defined* strategy/portfolio over
  history → a track record (period/event simulation). `optimiser` = search an objective +
  constraints over a universe → optimal weights (solver). `backtest` is foundational;
  `optimiser` depends on it (uses backtests to score candidate allocations). Both emit
  paper Portfolios consumed by `analytics`.

- **`macro` vs `altdata` vs `signal` boundary (three-way).**
  - `macro` = traditional macroeconomic / official public-sector data (central-bank
    rates, FOMC/ECB/BoE releases, balance sheets, monetary aggregates, projections).
    Indicator time series, not keyed by sym_id.
  - `altdata` = *raw* alternative data (card transactions, satellite, web-scraping,
    geolocation, social sentiment, shipping, job postings). Keyed to sym_id where it
    attaches to securities.
  - `signal` = *derived* signals/features/factors/alpha computed from sym + macro +
    altdata. The "NLP sentiment of FOMC speeches" type derived series lives here, NOT in
    macro or altdata. `signal` is the derivation/identification module; `macro` and
    `altdata` are the raw-data modules that feed it. Signals feed `backtest`/`optimiser`
    (strategy inputs) and `analytics` (factors).

## C. Portfolios — weights-first data shape (for the portfolios module's later design)

- A **portfolio** is a time series of effective-dated **weight vectors** over sym_id
  constituents (weights sum to ~1; cash/residual handled explicitly).
- Analytics derive portfolio returns by weighting sym's per-constituent returns —
  no share quantities, no transaction cash flows in the first cut.
- Later enhancements (not first cut): share-quantity holdings, a transactions/trades
  ledger for realized cash PnL, multi-currency contribution, corporate-action handling
  beyond what sym's return series already bake in.
