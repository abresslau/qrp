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

### Story Q4.5 — Weight history over time (multi-date)  `[BUILT 2026-06-11]`
As the Operator, I want a portfolio's full effective-dated weight history, not just the latest.
**AC (met):** multi-date upload already worked; detail view (API `?as_of_date=` + console picker)
serves any stored vector (`shown_as_of_date`; 422 for a date with no vector); analytics applies
the THEN-effective vector per date (step function over `read_weight_history` — the new
portfolios seam). Verified live on the 12-vector backtest portfolio. **(FR-14 complete.)**

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

### Story Q5.2 — Return & PnL across Return Windows  `[BUILT 2026-06-11]`
**AC (met, decision recorded):** time-weighted Return = compounded effective-dated daily series
per analytics window (the `returns` block: cumulative TWR + n_days); **PnL defined as cumulative
TWR**, expressed in money via an OPTIONAL `portfolio.notional` (base_currency; migration
`portfolio_notional`; create + PATCH) — `pnl = notional × cumulative_return`, null without a
notional, never fabricated. `portfolios.returns` kept as an honestly-labelled current-holdings
attribution snapshot (`semantics` field). Cross-check: analytics' TWR on the backtest-saved
portfolio reproduces the engine's result (+41.8%/Sharpe 2.04 vs +44.7%/2.18, monthly-snapshot
gap). **(FR-15 complete.)**

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

### Story Q6.3 — Parameterised strategy definition  `[BUILT 2026-06-11]`
As the Operator, I want to define a strategy (selection rule, weighting, rebalance cadence,
universe, window) — not just the hard-coded factor-quintile.
**AC (met):** a strategy spec (factor = ANY signals-package factor incl. cross-module ·
top_pct XOR top_n · equal/cap weighting · monthly/quarterly rebalance · date range) drives
the engine and persists whole on `backtest.run.spec` (reproducible); the engine's bespoke
factor SQL is GONE — it delegates to `signals.compute.raw_factor` (single definition source;
the drifted un-annualised vol reconciled). Cap-weighting drops (and counts) capless names,
never zero-weights. **(FR-18 "defined strategy".)**

### Story Q6.4 — Backtest output as a paper Portfolio (analytics-consumable)  `[BUILT 2026-06-08]`
**AC (met):** a backtest with `save_portfolio=true` materialises its equal-weight holdings-over-time
as a `portfolios` Portfolio (persisted via the portfolios package's own writer — ownership
respected; sym package reused for figi resolution); `analytics` then measures it vs a benchmark.
Console: a "Save as portfolio" checkbox + link. Verified: mom_12_1/sp500 → portfolio #3 (12
rebalances) → analytics computes. **First research-loop link closed (backtest→portfolios→analytics).**
**Refinement (RETIRED 2026-06-11):** ~~analytics uses the latest weight vector held constant~~ —
Q4.5/Q5.2 landed effective-dated weighting; analytics now applies the vector in force on each
date. **(FR-18 "consumable by analytics".)**

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

### Story Q7.3 — General objective + constraints (+ optional signal inputs)  `[BUILT 2026-06-11]`
As the Operator, I want to express an objective and constraints (sector caps, max position,
turnover, optional `signal` tilts), not just unconstrained long-only MV.
**AC (met):** **max-position cap** shipped as the constraint archetype (exact capped-simplex
projection inside the PGD solver; infeasible cap → named error; cap respected exactly — live
5% cap → max weight 5.0000%); **signal tilts** = any signals factor biases the objective
(−strength·wᵀz, favourable-oriented cross-sectional z via the `raw_factor` seam at the
covariance end date; unscored names neutral); full spec persisted (`solution.spec` JSONB,
migration `solution_spec`). Sector caps + turnover ledgered as follow-ons. **(FR-22.)**

### Story Q7.4 — Optimiser output as a Portfolio; scored via backtest  `[BUILT 2026-06-11]`
**AC (met):** `save_portfolio` persists the allocation via the portfolios package's writer
(live: solution #7 → portfolio #4); **candidate scoring via backtest** = train/holdout split —
the covariance window excludes the trailing holdout, and the solution + EW baseline are scored
OUT-OF-SAMPLE there through the new public `backtest.engine.score_weights` seam. Cross-check:
analytics independently measured portfolio #4 at +16.2185% over the holdout — matching the
backtest scorer to 13 decimal places. **(FR-22 + PRD §4.9.)**

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

### Story Q8.3 — Broaden alt-data sources  `[BUILT 2026-06-11]`
As the Operator, I want more than one alt-data source (the PRD lists card transactions,
satellite, web-scraping, geolocation, social sentiment, shipping, job postings).
**AC (met):** wiki-shaped tables replaced by a generic entity-keyed `altdata.series`/`observation`
model (PK `(composite_figi, source, metric)`; Wikimedia data migrated in losslessly); second
archetype = **SEC EDGAR regulatory-filing activity** (daily Form 4 + 8-K counts per company,
ticker→CIK→figi, probe-verified contracts); provenance per series (`detail` = article/CIK);
honest sparse-series window rates (sum/days, per-series anchor); 10 wiki + 20 EDGAR series live;
first altdata test suite (20 tests). Probed-and-blocked: GDELT/IMF/FRED; job-board/GitHub probes
denied by env policy — re-probe when a third archetype is wanted. **(FR-19 breadth.)**

### Story Q8.4 — Broaden macro coverage  `[BUILT 2026-06-11]`
**AC (met):** three sources added beyond World Bank + ECB — **US Treasury FiscalData** (daily
debt outstanding + monthly avg interest rates Bills/Notes/Bonds), **OECD** (monthly CPI YoY ×
USA/GBR/JPN/BRA), **Eurostat** (monthly EA HICP + EU27 unemployment); 13 → 23 series / 453 →
12k obs, each source-attributed; daily+monthly handled. Restatement visibility folded in
(`observation.last_changed_at` bumped only on value change + `restated` ingest counter).
FRED stays out (still needs an API key — adapter when one exists on deploy). **(FR-20 breadth.)**

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

### Story Q9.2 — Signals from macro + altdata inputs  `[BUILT 2026-06-11]`
As the Operator, I want signals derived from `macro` and `altdata`, not just sym returns
(e.g. an attention-spike factor from altdata, a rate-regime factor from macro).
**AC (met):** `compute_universe` reads each input module over its OWN read-only connection
(AR-R2; missing connection = attributed skip, never silent zero); two cross-module factors
live — **`wiki_attention`** (altdata 7d/30d pageview ratio, sparse-by-honesty 10-name coverage)
and **`fiscal_sens`** (1Y OLS beta of sym daily returns to macro UST:DEBT daily %-changes,
502 names scored on sp500); all reads bounded at as_of_date (no look-ahead). **(FR-21 core.)**

### Story Q9.3 — Input + method traceability  `[BUILT 2026-06-11 — folded into Q9.2]`
**AC (met):** `signals.factor.inputs` (JSONB module-qualified refs) + `factor.method` for ALL
five factors (definition choices and vintage caveats stated in the method text); served on both
API models; console shows per-module input chips + the method line. **(FR-21 traceability.)**

### Story Q9.4 — Signals consumable by optimiser / backtest  `[BUILT 2026-06-11]`
**AC (met):** a signal's scores drive BOTH consumers through the one public `raw_factor` seam
(recomputed at-date — no look-ahead, no stored-score reads; module connections opened only
when `required_modules(factor)` demands, AR-R2): backtest selection rules (Q6.3 spec; live
`fiscal_sens` cap-weighted quarterly run) and optimiser objective tilts (Q7.3; live
`fiscal_sens` tilt in the loop-closing solve). **(FR-21 complete.)**

---

## Epic QH: Production Hardening (cross-cutting)
The caveats that separate the spikes from production, plus migration follow-ups. Not new
capability — quality/operability.

### Story QH.1 — Close the Brazil GICS gap  `[BUILT 2026-06-11]`
**AC (met):** `B3GicsSource` classifies from B3's own published sector taxonomy
(`GetPortfolioDay` segment=2, IBOV+IBXX) via an explicit normalised B3→GICS sector mapping
(`source='b3'`, sector level only — depth honesty; "Explor Imóveis"→Real Estate exception;
unmapped segments reported, never guessed); fill-only pass in `sym classify` (financedatabase
always wins). Live: all 49 unclassified BVMF names classified, 0 unmapped; ibov/ibx
`missing gics` FAILs 43+49 → **0**; the ibov heatmap's Unclassified group is GONE (72/72
sectored). Remaining gics FAILs are non-Brazil (ftse100 69, US 34, others) — ledgered with
the SEC SIC fallback lead.

### Story QH.2 — Live quote source (live-PnL)  `[NEW, deferred]`
**AC:** a real-time quote source (none in-env) feeds a `GET /api/sym/quotes`; live-PnL reuses the
EOD engine with the price source swapped; labelled live/delayed, not persisted. **(Engine ready;
deferred until a source exists on deploy.)**

### Story QH.3 — Read-only DB role for sym reads  `[BUILT 2026-06-14]`
**AC (met):** consumer reads of the sym package go through a least-privilege **`qrp_readonly`**
Postgres role (CONNECT on sym + `SELECT` on the AR-R3 read surface only — no write, no DDL, no
sym-internal relations); a write through a read connection is **physically refused** by Postgres
(the psycopg analogue of the DuckDB `READ_ONLY` attach, proven by a live-gated test). Routed
centrally in the `connect()` helpers (`connect("sym")` → read-only, own-DB → full creds);
provisioned by `tools/provision_readonly.py` (rides `deploy_all`), grants single-sourced from
`qrp_api.sym_contract.SYM_READ_SURFACE` (shared with the topology gate). Op-execution keeps full
creds via the `uv run sym` subprocess — the dual-credential model realised. 786 tests pass.
Cross-module reads beyond sym (signals→macro/altdata) and the offline `lineage` introspection
generator (reads sym-internal relations across all DBs) stay full-cred — both ledgered as
deliberate exceptions to the role discipline. **(NFR hardening; serving-path consumers covered;
architecture-qrp dual-credential follow-up CLOSED.)**

### Story QH.4 — Operate live progress via SSE  `[NEW]`
**AC:** the Operate job panel streams via SSE instead of 2s polling; status still derived from
`pipeline_run_log` + heartbeat. **(FR-8 nice-to-have, deferred in v1.)**

### Story QH.5 — Migration finish-off: meta-orchestration + invariant guard  `[BUILT 2026-06-11]`
**AC (met):** `tools/deploy_all.py` — the DSN registry (8 projects incl. the sym/operate
irregulars) + one-command create-missing-DBs/deploy/verify (`--status`/`--only` modes; proven
8/8 live AND from-nothing on a scratch DB); its first full run caught + fixed 12 ROTTEN verify
scripts (sym 11, operate 1 — stale `asof`/`first_session`/`variant`/dropped-table references
invisible since the renames). The "CI check" is a SUITE gate (`test_topology_discipline.py`,
4 tests: cross-schema DDL ban, the AR-R3 sym read-surface allowlist, a vocabulary guard that
makes silent contract growth impossible, no-sym-imports). DuckDB live-attach spike RUN (the
env blocker is gone): extension installs, cross-DB join correct, writes physically refused —
finding recorded in architecture-qrp.md; serving-path adoption stays its own story.
**(DB-per-package migration follow-ups closed.)**

### Story QH.6 — Generic module framework + command palette (FR-2)  `[NEW]`
**AC:** now that 8 modules exist (the "build module #2 first" trigger is long past), extract the
generic module-registry / per-module bundle loader and ship the command palette (FR-2, deferred
in v1). **(NFR-10 just-in-time framework + FR-2.)**

## FR Coverage Map
- FR-13 → Q4.3 **(Client entity `[BUILT]` — model + API + UI)** + Q4.1/Q4.4 (portfolio CRUD `[BUILT]`) ✅ complete
- FR-14 → Q4.1, Q4.2 `[BUILT]`, Q4.5 `[BUILT 2026-06-11]` (multi-date history + as-of picker) ✅ complete
- FR-15 → Q5.1 `[BUILT]`, Q5.2 `[BUILT 2026-06-11]` (TWR + PnL = cumulative TWR × optional notional) ✅ complete
- FR-16 → Q5.3 `[BUILT]` (Sharpe/alpha/beta/TE/IR) + **Q5.4 `[BUILT]`** (hit/batting/slugging) ✅ complete
- FR-17 → Q5.5 `[BUILT]`
- FR-18 → Q6.1/Q6.2 `[BUILT]` + Q6.4 `[BUILT]` + Q6.3 `[BUILT 2026-06-11]` (strategy spec) ✅ complete
- FR-19 → Q8.2 `[BUILT]` + Q8.3 `[BUILT 2026-06-11]` (breadth: generic series model + SEC EDGAR)
- FR-20 → Q8.1 `[BUILT]` + Q8.4 `[BUILT 2026-06-11]` (breadth: +FiscalData/OECD/Eurostat)
- FR-21 → Q9.1 `[BUILT]` + Q9.2/Q9.3/Q9.4 `[BUILT 2026-06-11]` ✅ complete
- FR-22 → Q7.1/Q7.2 `[BUILT]` + Q7.3/Q7.4 `[BUILT 2026-06-11]` ✅ complete

## Build status summary (2026-06-08)
All seven roadmap modules are **built + live** (spikes), each in its own database post-migration.
The outstanding work, by value:
- **v2 completion: ✅ DONE (2026-06-11).** FR-16 skill metrics (Q5.4), FR-13 Client entity (Q4.3),
  and the final polish pair — FR-15 TWR/PnL (Q5.2) + multi-date weight history (Q4.5) — all
  complete. FR-13…FR-17 are fully built: v2 ("run clients' portfolios") is closed.
- **The research loop — ✅ CLOSED (2026-06-11, same day it was un-parked):** every link live
  and cross-verified — signals (cross-module factors, Q9.2) → backtest (strategy specs over
  the `raw_factor` seam, Q6.3+Q9.4) → optimiser (constraints + signal tilts, Q7.3; holdout
  scoring via `backtest.engine.score_weights`, Q7.4) → portfolios (saved allocations) →
  analytics (effective-dated TWR). The closing cross-check: analytics measured the optimiser's
  saved portfolio at +16.2185% over its holdout — matching the backtest scorer to 13 decimal
  places (two independent computations of the same series). FR-13…FR-22: **all complete.**
- **➡️ NEXT FOCUS — develop the databases (operator priority):** deepen the per-package data stores
  before building research on them: ✅ **Q8.3** (altdata: generic series model + SEC EDGAR, 2026-06-11),
  ✅ **Q8.4** (macro: +FiscalData/OECD/Eurostat, 2026-06-11), ✅ **QH.1** (Brazil GICS via B3,
  2026-06-11), remaining: real ingestion/coverage depth. The signal module's FR-21 inputs
  (macro/altdata) only become worthwhile once those sources are real — both raw modules now
  carry multi-source data.
- **Breadth + hardening (medium):** ✅ Q8.3/Q8.4 done (multi-source altdata + macro, 2026-06-11); ✅ QH.1 done (Brazil GICS via B3 — non-Brazil gaps ledgered); ✅ QH.5 done (deploy-all + topology gate + DuckDB spike, 2026-06-11). Remaining hardening: non-Brazil GICS, QH.3 read-only role, QH.6 framework trigger.
- **Deferred-by-design:** live quotes (QH.2), SSE (QH.4), generic framework/palette (QH.6).
- **Console (ad-hoc, 2026-06-11):** Story C.1 — sidebar submenus (chevron expand/collapse
  decoupled from navigation + open-down animation, per operator change request); sym static
  sub-items + macro data-driven categories (`macro.series.category`, `/api/macro/categories`,
  `/macro/<category>` routes; +10 WB population series). Story C.2 — category comparison view
  (same-indicator/same-unit series overlaid, toggleable countries), gated to `population` per
  operator instruction; rollout = extend `COMPARISON_CATEGORIES`. QH.6's generic module
  framework deliberately NOT built (bespoke providers; extract at module #3).
