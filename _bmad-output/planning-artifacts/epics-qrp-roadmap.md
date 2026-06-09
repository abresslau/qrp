---
stepsCompleted: ["step-01-validate-prerequisites", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/prd.md
  - _bmad-output/planning-artifacts/architecture-qrp.md
  - _bmad-output/planning-artifacts/epics-qrp.md (v1 epics Q1–Q3; this file extends Q4–Q9)
  - C:/Projects/qrp/OVERNIGHT.md (the as-built record of the roadmap modules)
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-06-08.md (DB-per-package topology)
---

# QRP Roadmap (Q4–Q9) — Epic & Story Breakdown

## Overview

This file decomposes QRP's **roadmap** PRD requirements (FR-13…FR-22, PRD §4.6–§4.12) and
the **vision-level epics Q4–Q9** from `epics-qrp.md` into implementable stories. It is
deliberately separate from `epics-qrp.md` (which carries the v1 Q1–Q3 epics + stories).

**The unusual context — these modules are already built.** An overnight session (2026-06-08)
implemented all seven roadmap modules (`portfolios`, `analytics`, `backtest`, `optimiser`,
`altdata`, `macro`, `signal`) as **spikes** — live and number-verified, but with **curated /
sample scope** and **no formal stories**. Since then the **DB-per-package migration**
(2026-06-08) gave each module its own Postgres database. So these stories serve two purposes:

1. **Retroactively formalize** the as-built capability with testable acceptance criteria.
2. **Capture the production-hardening gap** — the honest caveats (curated scope, missing
   metrics, single sources, no inter-module wiring) that separate a spike from production.

**Per-story status tag:** `[BUILT]` (done, prod-ready) · `[BUILT-SPIKE]` (works, needs
hardening) · `[PARTIAL]` (some ACs met) · `[NEW]` (not yet built).

## Requirements Inventory

### Functional Requirements (PRD roadmap)
- **FR-13** — Manage Clients & Portfolios; select a Client/Portfolio context.
- **FR-14** — Load a Portfolio's holdings as effective-dated weight vectors; resolve to sym_id; unresolved flagged.
- **FR-15** — Portfolio time-weighted Return & PnL across Return Windows.
- **FR-16** — Risk & skill metrics vs a Benchmark: Sharpe, alpha, **hit ratio, batting average, slugging ratio**.
- **FR-17** — Benchmark selection (a sym Universe/index).
- **FR-18** — Run a *defined* backtest strategy over a sym Universe + date range → paper Portfolio.
- **FR-19** — Surface a raw alt-data series joined by sym_id.
- **FR-20** — Surface a macro series (indicator time series, source-attributed).
- **FR-21** — Define/surface a derived Signal from **sym + macro + altdata**, inputs+method traceable; consumable by backtest/optimiser/analytics.
- **FR-22** — Optimise an allocation (objective + constraints over a sym Universe, optional `signal` inputs) → Portfolio.

### Non-Functional (cross-cutting; inherited from v1)
- **NFR-1/2** faithfulness/no-reimpl — read sym, never mutate it; never reimplement sym logic.
- **NFR-5** responsiveness (p95 < ~1s reads) · **NFR-7** observability/traceability · **NFR-8** typed contract (Pydantic→TS).

### Additional requirements (architecture-derived — post-migration reality)
- **AR-R1 — DB-per-package.** Each module owns its own Postgres database (`portfolios`,
  `analytics` reads only, `backtest`, `optimiser`, `altdata`, `macro`, `signal`); `qrp` DB
  holds only the Operate job ledger. Supersedes AR-Q4. (Revision log in architecture-qrp.md.)
- **AR-R2 — App-side cross-package reads.** A module reads sym (a read-only upstream peer) over a **separate
  read-only connection** and assembles cross-package data **in the service layer** (Python),
  never a cross-database SQL join. Derived computes use two connections (read sym, write own).
- **AR-R3 — Discipline (the "contract").** `sym_id` value keys, no cross-DB FK, consumers read
  sym's stable views. (No SDK package — solo right-sizing.)
- **AR-R4 — Typed contract.** Every roadmap router exposes `response_model`s; `gen:types` keeps
  the console types in sync (the build cycles already added Pydantic models per module).

## Epic List

> **Sequencing reality:** v2 = Q4 + Q5 (the "run clients' portfolios" capability) — both built,
> needing the FR-16 metric completion + a real Client entity. Q6–Q9 are built spikes whose value
> is hardening + inter-module wiring (signal→optimiser→backtest→analytics is the research loop the
> PRD describes but the spikes don't yet connect).

- **Epic Q4 — portfolios: Clients & Portfolios** `[BUILT, weights-first]` — FR-13, FR-14.
- **Epic Q5 — analytics: Portfolio Analytics** `[BUILT-SPIKE]` — FR-15, FR-16, FR-17.
- **Epic Q6 — backtest: Backtesting** `[BUILT-SPIKE]` — FR-18.
- **Epic Q7 — optimiser: Optimisation** `[BUILT-SPIKE]` — FR-22.
- **Epic Q8 — altdata & macro: Raw Data Modules** `[BUILT-SPIKE]` — FR-19, FR-20.
- **Epic Q9 — signal: Signal Identification** `[BUILT-SPIKE]` — FR-21.
- **Epic QH — Production Hardening (cross-cutting)** — the honest caveats + migration follow-ups.

---

## Epic Q4: portfolios — Clients & Portfolios  `[BUILT, weights-first]`
**Built:** own `portfolios` database; weights-first portfolios; CSV upload with sym_id
resolution; weighted return/PnL (YTD +6.25% verified). **Gap:** a real Client entity + context
(FR-13 is only a `client` TEXT column today).

### Story Q4.1 — Portfolio + effective-dated weight store  `[BUILT]`
As the Operator, I want portfolios stored as effective-dated weight vectors over sym_id, in
their own database.
**AC:** `portfolios.portfolio` + `portfolios.portfolio_weight` (PK `(portfolio_id, as_of_date,
composite_figi)`); weights-first; no FK to sym (value-only `sym_id`); own Sqitch project /
database (AR-R1). **(FR-14 storage half.)**

### Story Q4.2 — Upload weights with sym_id resolution  `[BUILT]`
As the Operator, I want to upload a weight vector and have constituents resolve to sym_id.
**AC:** ticker/FIGI → `composite_figi` resolved against the **sym package** over a read-only
connection (AR-R2); unresolved identifiers reported, never fabricated; weights upserted by
`(portfolio, as_of_date, figi)`. **(FR-14.)**

### Story Q4.3 — Client entity + Client/Portfolio context  `[BUILT 2026-06-08]`
As the Operator, I want first-class Clients and a selectable Client→Portfolio context.
**AC (met):** `portfolios.client` table + `portfolio.client_id` FK (migration `client_entity`,
backfilled from the legacy text column); resolve-or-create on portfolio create;
`GET/POST /api/portfolios/clients` (list with portfolio counts / create); responses keep `client`
as the joined name (no contract break). **Console:** a Clients strip with per-client **filter
chips** (Client→Portfolio context, ordinary navigation), a "+ Client" creator, and a pick-or-type
client datalist on the New-portfolio form. Render-verified. **(FR-13 complete — data model + API +
UI.)**

### Story Q4.4 — Browse & inspect portfolios  `[BUILT]`
**AC:** list portfolios with weight counts + latest as-of; detail view shows the latest weight
vector with ticker/name enriched **in-app** from the sym package (AR-R2). **(FR-13 view half.)**

### Story Q4.5 — Weight history over time (multi-date)  `[PARTIAL]`
As the Operator, I want a portfolio's full effective-dated weight history, not just the latest.
**AC:** upload + view multiple `as_of_date` vectors per portfolio; the detail view can pick an
as-of; analytics uses the appropriate vector per date. **(FR-14 "time series" — storage supports
it; UI/exposure to be completed.)**

---

## Epic Q5: analytics — Portfolio Analytics  `[BUILT-SPIKE]`
**Built:** portfolio daily series = weights × sym `fact_returns` (assembled in-app, AR-R2);
Sharpe / Jensen alpha / beta / tracking-error / information-ratio vs a chosen index benchmark
(β 1.3863 vs S&P 500 verified). **Gap:** FR-16's **hit ratio / batting average / slugging ratio**
are NOT built; PnL is return-based only (weights-first has no notional).

### Story Q5.1 — Portfolio daily return series  `[BUILT]`
**AC:** daily portfolio return = Σ wᵢ·rᵢ over sym 1D `fact_returns`, weights from the
`portfolios` DB and returns from the sym package, assembled in Python (AR-R2); dates below a 99%
coverage floor dropped (no fabricated returns). **(FR-15 basis.)**

### Story Q5.2 — Return & PnL across Return Windows  `[PARTIAL]`
**AC:** time-weighted Return per sym Return Window (built via `portfolios.returns`); **PnL**:
either define it as cumulative return (weights-first) **or** add an optional notional to express
absolute PnL — decide + document. **(FR-15.)**

### Story Q5.3 — Risk metrics vs benchmark (Sharpe / alpha / beta / IR / TE)  `[BUILT]`
**AC:** annualised return/vol, Sharpe, beta, Jensen alpha, correlation, active return, tracking
error, information ratio vs a selected index; rf=0, ANN=252; reproducible from sym inputs;
FX-mismatch warning when portfolio ccy ≠ benchmark ccy. **(FR-16 partial.)**

### Story Q5.4 — Skill metrics: hit ratio, batting average, slugging ratio  `[BUILT 2026-06-08]`
As the Operator, I want the **skill** metrics the PRD names, not just risk metrics.
**AC (met):** hit ratio (% periods portfolio > 0), batting average (% periods out-performing the
benchmark), slugging ratio (avg winning active return ÷ avg losing active magnitude), computed
from the daily series vs the benchmark, added to the `Metrics` response_model + TS types + the
analytics panel. Verified vs S&P 500: hit 0.571 / batting 0.529 / slugging 0.971 (357 days).
**(FR-16 complete.)**

### Story Q5.5 — Benchmark selection  `[BUILT]`
**AC:** benchmarks are sym index instruments with a daily series (17 available); the chosen
benchmark drives alpha/beta/active metrics. **(FR-17.)**

---

## Epic Q6: backtest — Backtesting  `[BUILT-SPIKE]`
**Built:** walk-forward top-quintile factor strategy (factor recomputed per rebalance, **no
look-ahead**; coverage-gated start); equity curve vs equal-weight baseline; persisted to the
`backtest` DB; reads sym package over a 2nd connection (AR-R2). mom sp500 +44.7% (Sharpe 2.18)
verified. **Gap:** only ONE strategy archetype (factor-quintile); FR-18's "defined strategy"
implies a parameterised strategy definition; output isn't yet consumed as a Portfolio by analytics.

### Story Q6.1 — Walk-forward factor-strategy engine (no look-ahead)  `[BUILT]`
**AC:** at each monthly rebalance the factor is recomputed from sym `fact_returns` *as of that
date*; top-quintile equal-weight held to next rebalance; coverage gate (≥50% universe) sets the
effective start; daily returns vs an equal-weight baseline; reads sym read-only, writes the
backtest DB. **(FR-18 basis.)**

### Story Q6.2 — Run config + equity-curve persistence  `[BUILT]`
**AC:** `backtest.run` (config + summary stats: total/ann return, vol, Sharpe, max drawdown) +
`backtest.point` (equity curves, sampled ≤400 pts); idempotent per run; IDENTITY sequences sound
after the DB-per-package move. **(FR-18.)**

### Story Q6.3 — Parameterised strategy definition  `[NEW]`
As the Operator, I want to define a strategy (selection rule, weighting, rebalance cadence,
universe, window) — not just the hard-coded factor-quintile.
**AC:** a strategy spec drives the engine (factor or signal input, top-N/quintile, EW/cap-weight,
rebalance freq); reproducible from the spec. **(FR-18 "defined strategy".)**

### Story Q6.4 — Backtest output as a paper Portfolio (analytics-consumable)  `[BUILT 2026-06-08]`
**AC (met):** a backtest with `save_portfolio=true` materialises its equal-weight holdings-over-time
as a `portfolios` Portfolio (persisted via the portfolios package's own writer — ownership
respected; sym package reused for figi resolution); `analytics` then measures it vs a benchmark.
Console: a "Save as portfolio" checkbox + link. Verified: mom_12_1/sp500 → portfolio #3 (12
rebalances) → analytics computes. **First research-loop link closed (backtest→portfolios→analytics).**
**Refinement:** analytics uses the latest weight vector held constant; time-varying-weight
analytics is Q4.5. **(FR-18 "consumable by analytics".)**

---

## Epic Q7: optimiser — Optimisation  `[BUILT-SPIKE]`
**Built:** pure-Python projected-gradient mean-variance over the simplex (min-variance,
max-Sharpe), long-only; covariance/mean from sym daily returns (top-N by mcap); ticker
denormalised; persisted to the `optimiser` DB; reads sym over a 2nd connection. min-var vol
7.0% ≤ EW 15.6% verified. **Gap:** only long-only/simplex; no general objective+constraints; no
`signal` inputs; output not wired to backtest/analytics.

### Story Q7.1 — Mean-variance solver (min-var / max-Sharpe, long-only)  `[BUILT]`
**AC:** projected-gradient solver on the probability simplex (Σw=1, w≥0); min-variance and
max-Sharpe; annualised exp return/vol/Sharpe + equal-weight benchmark vol; covariance ties to
sym daily returns; in-sample optimism stated in the UI. **(FR-22 basis.)**

### Story Q7.2 — Solution + weights persistence  `[BUILT]`
**AC:** `optimiser.solution` (config + expected stats) + `optimiser.weight` (long-only
allocation); own database; IDENTITY sequence sound post-migration. **(FR-22.)**

### Story Q7.3 — General objective + constraints (+ optional signal inputs)  `[PARKED — data-layer first]`
As the Operator, I want to express an objective and constraints (sector caps, max position,
turnover, optional `signal` tilts), not just unconstrained long-only MV.
**AC:** constraints applied + respected; optional `signal` factor inputs (Q9) bias the objective;
reproducible from objective+constraints+universe+inputs. **(FR-22 "objective + constraints",
"optional signal inputs".)**

### Story Q7.4 — Optimiser output as a Portfolio; scored via backtest  `[PARKED — data-layer first]`
**AC:** the solution's weights persist as a `portfolios` Portfolio; the optimiser can score
candidates via `backtest` (Q6) — the optimiser-uses-backtests loop the PRD describes. **(FR-22 +
PRD §4.9 "uses backtests to score candidates".)**

---

## Epic Q8: altdata & macro — Raw Data Modules  `[BUILT-SPIKE]`
**Built:** `macro` DB (World Bank + ECB, 13 series / 453 obs, source-attributed); `altdata` DB
(Wikimedia pageviews, 10 names / 1210 obs, mapped to sym_id; attention-spike metric). **Gap:**
each is a single source with a curated set; the PRD envisions a breadth of alt-data sources and
fuller macro coverage (FRED was blocked in-env).

### Story Q8.1 — Macro series store + ingest  `[BUILT]`
**AC:** `macro.series` + `macro.observation` (own DB); World Bank annual indicators + ECB rate;
source attribution + as-of dating; empty series dropped (never faked); read API + console chart.
**(FR-20.)**

### Story Q8.2 — Alt-data series store + ingest (sym_id-joined)  `[BUILT]`
**AC:** `altdata.wiki_map` (figi↔article) + `altdata.pageview` (own DB); ingest resolves figis
from the sym package over a 2nd connection (AR-R2); read API + sparkline + 7d/30d attention spike.
**(FR-19.)**

### Story Q8.3 — Broaden alt-data sources  `[NEW]`
As the Operator, I want more than one alt-data source (the PRD lists card transactions,
satellite, web-scraping, geolocation, social sentiment, shipping, job postings).
**AC:** the altdata schema/ingest generalises to ≥1 additional source archetype keyed by sym_id;
source provenance recorded; probe-before-build per the env-source rule. **(FR-19 breadth.)**

### Story Q8.4 — Broaden macro coverage  `[NEW]`
**AC:** add indicators/sources beyond World Bank + ECB (e.g. a FRED adapter when reachable, US
Treasury); each source-attributed; monthly/daily frequencies handled. **(FR-20 breadth; FRED was
env-blocked at spike time.)**

---

## Epic Q9: signal — Signal Identification  `[BUILT-SPIKE]`
**Built:** `signal` DB; 3 cross-sectional factors (12-1 momentum, 1Y volatility, size) over
sp500/ibov/ibx, winsorised 1/99; z-score/rank/percentile; compute reads the sym package, writes the
signal DB (AR-R2). AAPL 12-1 momentum hand-verified. **Gap:** signals derive **only from sym**
— FR-21's defining feature is signals from **sym + macro + altdata**, and consumption by
optimiser/backtest. Neither is wired yet.

### Story Q9.1 — Factor catalog + cross-sectional scoring (sym-derived)  `[BUILT]`
**AC:** `signal.factor` + `signal.score` (own DB); favourable-oriented z-score/rank/pctile;
winsorised; membership from current roster; reads sym read-only. **(FR-21 basis, sym inputs.)**

### Story Q9.2 — Signals from macro + altdata inputs  `[PARKED — data-layer first]`
As the Operator, I want signals derived from `macro` and `altdata`, not just sym returns
(e.g. an attention-spike factor from altdata, a rate-regime factor from macro).
**AC:** a signal can name inputs across modules (sym + macro + altdata), read each from its own
DB (app-side, AR-R2), and compute a derived score; this is the FR-21 differentiator vs the raw
modules. **(FR-21 — the unbuilt core.)**

### Story Q9.3 — Input + method traceability  `[PARTIAL]`
**AC:** each signal records its named inputs and method so it's reproducible and never
fabricated; surfaced in the UI. **(FR-21 traceability.)**

### Story Q9.4 — Signals consumable by optimiser / backtest  `[PARKED — data-layer first]`
**AC:** a signal's scores are selectable as inputs to `optimiser` (Q7.3 tilts) and `backtest`
(Q6.3 selection rule). **(FR-21 "consumable by backtest/optimiser".)**

---

## Epic QH: Production Hardening (cross-cutting)
The caveats that separate the spikes from production, plus migration follow-ups. Not new
capability — quality/operability.

### Story QH.1 — Close the Brazil GICS gap  `[NEW]`
**AC:** the 43/78 IBOV (and other) names left `Unclassified` get GICS sectors from a source
beyond the financedatabase free tier; the heatmap "unclassified" group shrinks; the
`universe_member_completeness` validate FAIL clears. (Data gap, surfaced honestly today.)

### Story QH.2 — Live quote source (live-PnL)  `[NEW, deferred]`
**AC:** a real-time quote source (none in-env) feeds a `GET /api/sym/quotes`; live-PnL reuses the
EOD engine with the price source swapped; labelled live/delayed, not persisted. **(Engine ready;
deferred until a source exists on deploy.)**

### Story QH.3 — Read-only DB role for sym reads  `[NEW]`
**AC:** consumer reads of the sym package use a least-privilege **read-only** Postgres role (the
DuckDB `READ_ONLY` attach proved the pattern; the API still uses full creds per package). **(NFR
hardening; architecture-qrp dual-credential follow-up.)**

### Story QH.4 — Operate live progress via SSE  `[NEW]`
**AC:** the Operate job panel streams via SSE instead of 2s polling; status still derived from
`pipeline_run_log` + heartbeat. **(FR-8 nice-to-have, deferred in v1.)**

### Story QH.5 — Migration finish-off: meta-orchestration + invariant guard  `[NEW]`
**AC:** one command deploys all per-package Sqitch projects + brings up all DBs (a DSN registry);
a CI check forbids cross-DB FKs and asserts consumers read only sym's stable views (AR-R3). The
DuckDB live-attach spike is re-run in a network-enabled env to finalise live-vs-materialised per
surface. **(DB-per-package migration follow-ups.)**

### Story QH.6 — Generic module framework + command palette (FR-2)  `[NEW]`
**AC:** now that 8 modules exist (the "build module #2 first" trigger is long past), extract the
generic module-registry / per-module bundle loader and ship the command palette (FR-2, deferred
in v1). **(NFR-10 just-in-time framework + FR-2.)**

## FR Coverage Map
- FR-13 → Q4.3 **(Client entity `[BUILT]` — model + API + UI)** + Q4.1/Q4.4 (portfolio CRUD `[BUILT]`) ✅ complete
- FR-14 → Q4.1, Q4.2 `[BUILT]`, Q4.5 `[PARTIAL]` (multi-date history)
- FR-15 → Q5.1 `[BUILT]`, Q5.2 `[PARTIAL]` (PnL definition)
- FR-16 → Q5.3 `[BUILT]` (Sharpe/alpha/beta/TE/IR) + **Q5.4 `[BUILT]`** (hit/batting/slugging) ✅ complete
- FR-17 → Q5.5 `[BUILT]`
- FR-18 → Q6.1/Q6.2 `[BUILT]` + Q6.3/Q6.4 `[NEW]` (defined strategy, analytics loop)
- FR-19 → Q8.2 `[BUILT]` + Q8.3 `[NEW]` (breadth)
- FR-20 → Q8.1 `[BUILT]` + Q8.4 `[NEW]` (breadth)
- FR-21 → Q9.1 `[BUILT]` (sym) + **Q9.2 `[NEW]`** (macro/altdata inputs) + Q9.3 `[PARTIAL]` + Q9.4 `[NEW]`
- FR-22 → Q7.1/Q7.2 `[BUILT]` + Q7.3/Q7.4 `[NEW]` (constraints, signal inputs, portfolio output)

## Build status summary (2026-06-08)
All seven roadmap modules are **built + live** (spikes), each in its own database post-migration.
The outstanding work, by value:
- **v2 completion:** ✅ FR-16 skill metrics (Q5.4) and ✅ FR-13 Client entity (Q4.3, model+API+UI)
  both complete. Remaining v2 polish: FR-15 PnL definition (Q5.2) + multi-date weight history (Q4.5).
- **The research loop — ⏸️ PARKED (operator decision 2026-06-08):** Q6.4 (backtest→portfolios→
  analytics) is done, but the remaining links — **Q9.2/Q9.4** (signals from macro/altdata; signals→
  optimiser/backtest) and **Q7.3/Q7.4** (optimiser constraints+signal inputs; optimiser→portfolio) —
  are **parked**. Rationale: wiring signal→optimiser→backtest on top of spike-grade data is premature;
  **develop the databases first** (see next bullet). Resume the loop once the data layer is deeper.
- **➡️ NEXT FOCUS — develop the databases (operator priority):** deepen the per-package data stores
  before building research on them: **Q8.3** (broaden altdata beyond Wikimedia), **Q8.4** (broaden
  macro beyond WB/ECB), real ingestion/coverage, and **QH.1** (Brazil GICS gap). The signal module's
  FR-21 inputs (macro/altdata) only become worthwhile once those sources are real.
- **Breadth + hardening (medium):** more alt-data/macro sources (Q8.3/Q8.4), GICS gap (QH.1), migration finish-off (QH.5).
- **Deferred-by-design:** live quotes (QH.2), SSE (QH.4), generic framework/palette (QH.6).
