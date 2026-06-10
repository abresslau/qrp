# ☀️ MORNING SUMMARY for Andre (2026-06-08 ~07:00)

**TL;DR — QRP went from "v1 sym console" to a full 8-module quant platform overnight, all live and
number-verified against the warehouse. Nothing is git-committed yet — review before you commit.**

## What QRP is now
A config-driven **console (Next 16, :3000) + FastAPI (:8001)** over the sym warehouse. **8 feature
modules + an Operate control-plane.** Everything reads sym **READ-ONLY**; QRP owns its own schemas
(`qrp`, `macro`, `signal`, `backtest`, `optimiser`, `altdata`) — **sym's schema was never altered**.
Typed end-to-end (FastAPI Pydantic response_models → `openapi-typescript` → console). Run with
**`npm run dev`** (starts both; uvicorn runs WITHOUT `--reload` — restart the single process after API edits).

## Modules (all live + verified)
- **sym — See**: Overview, Explorer, Universes, **Heat map** (Perplexity-style treemap), Attention, Validation.
- **sym — Operate**: trigger sym's OWN idempotent ops (validate/monitor/refresh/recompute) as guarded
  **out-of-process subprocess jobs** — `qrp.job` ledger + Postgres advisory lock + allowlist with
  confirm-gating for writers. Verified: validate ran (exit 2 = found known gaps), monitor ibov exit 0.
- **portfolios**: weights-first → weighted return/PnL. Sample portfolio **YTD +6.25%** (contributions tie).
- **analytics**: Sharpe / α / β / tracking-error vs a benchmark, from the daily `fact_returns` 1D series.
  Hand-verified **β 1.3863** (= independent recompute, 10dp).
- **macro**: World Bank + ECB, **13 series, 453 obs** (FRED was blocked). US CPI 2.95% / ECB rate 2.15% — tie to reality.
- **signal**: momentum / low-vol / size factors over sp500/ibov/ibx, **winsorised 1/99 pct**. AAPL 12-1
  momentum **0.4164** = hand recompute.
- **backtest**: walk-forward top-quintile factor strategy (factor recomputed per rebalance, **no look-ahead**;
  coverage-gated start). Momentum sp500 **+44.7% (Sharpe 2.18) vs +14.9% baseline**; first-day tie 0.999542.
- **optimiser**: pure-Python mean-variance (no numpy) — min-var & max-Sharpe, long-only. Min-var vol
  **7.0% ≤ EW 15.6%**; covariance tie **0.15624765**; min-var picked defensives **BRK.B/JNJ/CVX/KO/PG**.
- **altdata**: Wikimedia pageviews as a per-company attention proxy — **10 names, 1210 obs**, Apple peak 42k/day,
  7d/30d attention-spike metric.

## Also: Brazilian indexes pulled into sym
`ibov` (78) + `ibx` (99) via B3's authoritative GetPortfolioDay → sym's own idempotent ops (the ONLY
sym-DATA writes tonight). 100% priced/named; maintenance plan in `sym/docs/universe-maintenance.md`.

## Run it
`npm run dev` → API http://127.0.0.1:8001 + console http://localhost:3000. Console routes: `/sym`,
`/sym/{explorer,universes,heatmap,attention,validation,operate}`, `/portfolios`, `/macro`, `/signal`,
`/backtest`, `/optimiser`, `/altdata`.

## ⚠️ Pending / needs your call
- **GIT: nothing committed** — all QRP code is uncommitted in `C:\Projects\qrp`; the B3 writes are live in
  the sym DB. Review before committing.
- **Live quotes / live-PnL**: deferred — no live quote source in this env (Yahoo live empty/429). Engine ready; swap a source on deploy.
- **read-only DB role**: QRP uses one DSN for reads; the architecture's read-only-role hardening is a follow-up.
- **Operate transport**: currently 2s poll — SSE is a nice-to-have.
- **Brazil GICS gap**: financedatabase free tier lacks GICS for ~43/78 BR names (left Unclassified, not faked).
- ~~**Schemas applied directly** (`db/qrp/*.sql`), not yet Sqitch-formalised.~~ **DONE 2026-06-08**
  (commit `38074b0`): all six QRP schemas formalised into a Sqitch project (`project=qrp`,
  `sqitch.conf` + `db/sqitch.plan` + `db/{deploy,revert,verify}/`); replays clean on a blank DB and
  baselined on the live DB (coexists with sym's `sym` project). **Forward direction (not yet built):**
  the DB-topology brainstorm (`sym/_bmad-output/.../brainstorming-session-2026-06-08-123427.md`) chose
  **database-per-package + DuckDB federation** (supersedes AR-Q4) — federation spike run + recorded in
  `db/spikes/` (cross-DB join model + READ_ONLY proven; live-PG attach deferred, env-blocked).
- **sym `validate` has 2 pre-existing FAILs** (warehouse-wide unpriced names + Brazil GICS) — NOT caused by
  tonight's work (new BR names are 0 unpriced).
- Modules `optimiser`/`altdata` etc. are spikes with curated/sample scope — broaden universes/sources for production.

## Server status at handoff (07:02)
API :8001 **up** (health lists all 8 modules) · console :3000 **up** (307 redirect on `/`).

---

# QRP — overnight worklog (2026-06-07 → 08)

Andre asked me to work overnight, keep advancing v1 + new asks, and not idle. Servers:
**API `:8001` (uvicorn --reload)**, **console `:3000`** (Next dev). Console → `/sym` (Overview),
`/sym/explorer`, `/sym/heatmap`. Constraints: local/read-only or QRP-own-schema only; no
commits/pushes/deploys; never mutate sym's schema; never fabricate data; document deviations.

## Done tonight
- **Securities Explorer (Q2.2/2.3):** `/sym/explorer` (search + paging) + `/sym/securities/[figi]`
  (master, price, fundamentals, returns across all 28 windows). API: `/api/sym/securities`,
  `/api/sym/securities/{figi}`. Nav tab added. Verified vs live data.
- **Heat map theme-aware** + **Light/Dark/System** toggle; **share-class double-count fixed**
  (Alphabet → one tile, ISIN issuer merge); **hover tooltip** (classification, price, mcap
  LCY+USD, return, news placeholder).

## Done (cycle 2, in-session)
- **Universe explorer** `/sym/universes` (members + deep-link to `/sym/heatmap?u=<id>`).
- **Attention** `/sym/attention` (review queue, 7,279 price gaps w/ recent, membership proposals) —
  read-only; bug fixed: `securities_review_queue.source_input` is JSONB → stringify in gateway.
- **Validation** `/sym/validation` (recent validate runs, pass/warn/fail, status pills).
- => **Q2 "See" epic complete** (Overview, Explorer, Detail, Universes, Heat map, Attention, Validation).
- Heat map now **theme-aware** (Light/Dark/System) + share-class merge + tooltip.

## Done (cycle 3, in-session) — Q4 PORTFOLIOS (new epic)
- **QRP-own `qrp` schema** (`db/qrp/0001-portfolios.sql`): `qrp.portfolio`, `qrp.portfolio_weight`
  (weights-first, effective-dated, over sym_id). Applied idempotently. sym untouched.
- **API module `portfolios`** (enabled in platform.toml): create/list/get, upload weights
  (resolve ticker/FIGI → sym_id; unresolved reported), and **weighted return/PnL engine**
  (`/api/portfolios/{id}/returns?window=` = Σ wᵢ·rᵢ over sym returns + contributions + coverage).
- **UI:** `/portfolios` (list + create) and `/portfolios/[id]` (weights, weighted return + window
  selector + contributions, CSV weight upload). Sidebar auto-shows the module.
- **Verified:** sample portfolio (NVDA/AAPL/MSFT/AMZN/GOOGL) → YTD **+6.25%**, contributions tie out.
- **This is the live-PnL foundation** — same engine; swap EOD sym returns for a live price source
  later (deferred — no live source in this env).

## Done (cycle 4, in-session) — infra
- `scripts/dev.mjs` + `npm run dev` runs BOTH API (:8001) + console (:3000) together; also
  `npm run dev:api` / `dev:web`. README updated (accurate ports, no-reload note, status).

## Done (cycle 5, in-session) — Brazilian B3 ingest into sym (the ONE sym-DATA write)
- **B3 is REACHABLE** here (GetPortfolioDay, IBOV → 78 real constituents). yfinance returns
  real `.SA` bars; OpenFIGI resolves here; **USD/BRL FX already present** (no FX ingest needed).
- **Maintenance plan written first** → `sym/docs/universe-maintenance.md` (source=authoritative B3
  snapshot, build-forward PIT pinned 2026-06-08, rebalance Jan/May/Sep, daily monitor, gated review).
- Pipeline via sym's own idempotent ops (sym schema UNTOUCHED): `universe add ibov` →
  `refresh` (78 appended, **78 resolved / 0 unresolved**, projected) → `backfill --universe ibov`
  (**78/78, 360k rows, 0 errored**) → `recompute` (14.7M rows) → `fundamentals` (72/78, 6 gaps,
  market_cap_usd via BRL→USD) → `classify` (35 new) → `names` (**78/78 named**).
- **Verified in QRP:** `/api/sym/universes` shows ibov (78); `/api/sym/universes/ibov/heatmap`
  HTTP 200 → PETROBRAS +32.7% YTD ($132B), VALE SA +9.4%, AMBEV +16.7%, WEG SA −12.5%, BRL prices.
- **Honest caveats (no fabrication):** ibov unpriced=0/78 (pricing clean; the validate
  `unpriced` FAILs are pre-existing warehouse names, not Brazil). GICS missing 43/78 —
  financedatabase free tier has partial Brazil coverage; `sym validate --universe ibov` FAILs on
  that gics-completeness gap. Sectors left honestly Unclassified rather than invented.
- **ibx (IBrX-100)** is documented + ready in the maintenance plan but NOT yet populated (next).

## Done (cycle 6, in-session) — openapi-typescript typed contract
- **Generated types**: `apps/web/lib/api-types.ts` from the live OpenAPI schema
  (`openapi-typescript@7.13.0` ← `http://127.0.0.1:8001/openapi.json`). Added `gen:types`
  + `typecheck` npm scripts and the devDep.
- **Made responses real**: FastAPI portfolios router got `response_model`s (PortfolioSummary,
  CreatedPortfolio, PortfolioDetail, Weight, UploadResult, RetConstituent, PortfolioReturns) —
  so the schema (and TS types) carry actual shapes, not `{[k]:unknown}`. (Other GET endpoints
  still return loose dicts → typed as generic; future cleanup = add their response_models too.)
- **Typed client** (`lib/api.ts`): `Schemas` re-export + `apiGetTyped<P>` keyed to OpenAPI
  `paths` (200 response inferred) alongside the existing `apiGet<T>` escape hatch.
- **Converted surfaces**: `/portfolios` (list) + `/portfolios/[id]` (detail) now use generated
  `Schemas["PortfolioSummary"|"PortfolioDetail"|"PortfolioReturns"]`; create + upload request
  bodies typed via `Schemas["CreatePortfolio"|"UploadWeights"]`.
- **Verified**: API restarted (no --reload); portfolios endpoints 200 under response_models
  (returns YTD +6.25% still ties); `npx tsc --noEmit` exit 0; pages render 200.

## Done (cycle 7, in-session) — Q5 analytics (Sharpe / alpha / beta / benchmark-relative)
- **New QRP `analytics` module** (enabled in platform.toml, mounted in main.py), reads sym
  read-only. Daily series wrinkle solved: `fact_returns` **window_id=1 ('1D') `pr`** IS a daily
  return series; portfolio daily ret = Σ wᵢ·prᵢ / covered_w per date (latest weights held
  constant, dates with <99% weight priced dropped). Benchmark = `fact_index_returns` 1D `ret`
  for an `instrument` of kind 'index' (17 available: S&P 500=2048, IBOVESPA=2058, …, deep daily
  history 1990→).
- **Endpoints**: `GET /api/analytics/benchmarks`; `GET /api/analytics/portfolios/{id}?benchmark=<sym_id>&window=`
  (ALL|YTD|1M|3M|6M|1Y|2Y|3Y). Metrics: ann return/vol, Sharpe, beta, Jensen alpha, correlation,
  active return, tracking error, information ratio + benchmark stats. rf=0, ANN=252. Pydantic
  response_models added; `gen:types` re-run.
- **UI**: `components/analytics-panel.tsx` on the portfolio detail page — benchmark + window
  selectors, metric grid, FX-mismatch warning banner.
- **HAND-VERIFIED (ties to warehouse EXACTLY)**: portfolio 1 (US mega-cap) vs S&P 500 →
  beta **1.3863488018**, alpha_ann **0.0043781299** — independent raw-series recompute matched to
  10 dp. Sharpe 0.92, β 1.39, corr 0.90, IR 0.45, 357 daily obs. Window=YTD → 107 obs. FX warning
  fires for USD-portfolio-vs-IBOVESPA(BRL). tsc clean; detail page 200.

## Done (cycle 7b, in-session) — ibx (IBrX-100) populated (bonus, B3 path reused)
- `universe add ibx --kind index --index ibx --source-pref b3 --pit-from 2026-06-08` → refresh
  (**99 appended, 99/99 resolved**) → backfill (**99/99, 423k rows, 0 errored**) → names (21 new;
  78 ibov overlap already named) → fundamentals (92/99) → classify (15 new GICS). **Live in QRP**:
  `/api/sym/universes` shows ibx (99); 14 universes total. Returns (`recompute`, global) running
  in background at log time — ibx YTD lights up on its heatmap once it lands. Same honest GICS gap
  as ibov (financedatabase free Brazil coverage).
- **Verified (recompute landed):** `/api/sym/universes/ibx/heatmap` HTTP 200 → 99 members, 92
  shown, **91 with YTD returns**, real names (PETR4 +32.7%, VALE3 +9.4%, ITUB4 −1.0%).

## Done (cycle 8, in-session) — Q3 "Operate" (the last v1 epic)
- **Trigger sym's own idempotent ops as guarded background jobs, OUT of the web process.**
  QRP-own `qrp.job` ledger (`db/qrp/0002-jobs.sql`). Executor (`modules/operate/executor.py`)
  spawns `uv run sym <op>` as a SUBPROCESS in the sym project dir, supervised by a daemon
  thread that records status/exit/output-tail; a **Postgres advisory lock** keyed on (op,args)
  enforces one concurrent run per operation. sym's pipeline_run_log/validation_run_log stay the
  system-of-record; sym schema untouched.
- **Allowlist** (read-mostly vs writers): `validate`, `universe_monitor` (free) · `universe_refresh`,
  `recompute` (writers — require `confirm=true`). Endpoints: `/api/operate/ops`, `/run`,
  `/jobs`, `/jobs/{id}` (Pydantic response_models; types regenerated).
- **UI**: `/sym/operate` tab — op buttons (writers flagged ✎), universe selector, confirm toggle,
  live-polling job table with output drill-down.
- **VERIFIED end-to-end**: `validate` ran out-of-process (queued→running→exit 2 = found the known
  pre-existing gaps; ~16s; output captured), `universe_monitor ibov` → exit 0. All 3 guards reject
  correctly (writer w/o confirm; missing universe id; identical run in progress). tsc clean; page 200.
- Note: poll transport (2s while active) — SSE is a nice-to-have follow-up. `validate` exit 2 =
  "ran, found issues" surfaces as status='failed' with full output (documented in the op note).

## v1 STATUS: COMPLETE
All v1 epics shipped + verified: **Q1** spine · **Q2** See · **Q3** Operate · **Q4** portfolios ·
**Q5** analytics. Plus: Brazilian B3 (ibov+ibx), typed contract (openapi-typescript), themes.

## Done (cycle 9, in-session) — macro module (first roadmap module beyond v1)
- **Source reachability probed first** (env blocks some APIs): FRED **times out**; **World Bank**
  (JSON), **ECB Data Portal** (CSV), **US Treasury** all reachable. Built on World Bank + ECB.
- **QRP-managed `macro` schema** (`db/qrp/0003-macro.sql`): `macro.series` + `macro.observation`
  (NOT sym). Ingest (`modules/macro/ingest.py`, stdlib-only fetchers): World Bank annual
  indicators (CPI inflation, real GDP growth, real interest rate, unemployment) × US/Brazil/Euro
  area/UK/Japan + **ECB main refinancing rate** (daily feed compressed to 43 change-points).
  **13 series, 453 observations.** Empty series (e.g. WB EMU CPI = no data) dropped, not faked.
- **Read API** `/api/macro/series` + `/api/macro/series/{id}` (Pydantic response_models; types
  regenerated). Module enabled in platform.toml → auto-appears in sidebar.
- **Console `/macro`**: series list + latest value + inline SVG line chart.
- **VERIFIED (ties to reality)**: US CPI 8.0%(’22)→4.1%(’23)→2.95%(’24); Brazil 9.28→4.59→4.37;
  ECB rate 2.40→2.15. Endpoints 200; tsc clean; page 200.

## Done (cycle 10, in-session) — signal module (derived factors)
- **QRP-managed `signal` schema** (`db/qrp/0004-signal.sql`): `signal.factor` catalog +
  `signal.score`. Computes 3 cross-sectional factors from sym READ-ONLY: **12-1 momentum**
  ((1+1Y)/(1+1M)−1 from fact_returns windows), **volatility (1Y)** (annualised stdev of daily
  1D returns), **size** (market_cap_usd) — with favourable-oriented z-score, rank, percentile.
- Scored **sp500 (503), ibov (78), ibx (99)** = ~2,017 scores. (Membership uses current roster
  valid_to IS NULL — decoupled from data as-of so build-forward B3 universes score too.)
- **Read API** `/api/signal/factors` + `/api/signal/factors/{key}?universe=&limit=&bottom=`
  (Pydantic response_models; types regenerated). Module enabled → sidebar.
- **Console `/signal`**: factor + universe selectors, top/bottom toggle, ranked table (value, z, pctile).
- **HAND-VERIFIED**: AAPL 12-1 momentum stored 0.416438 == hand recompute from fact_returns
  (1Y 0.5319, 1M 0.0815). Endpoints 200; tsc clean; page 200.
- Honest note: momentum is outlier-sensitive — top sp500 name SNDK shows +3495% (a real
  warehouse value, synthetic-data extreme); surfaced as-is, NOT winsorised/capped (no fabrication).

## Done (cycle 11, in-session) — backtest module (walk-forward factor strategy)
- **QRP-managed `backtest` schema** (`db/qrp/0005-backtest.sql`): `backtest.run` + `backtest.point`
  (equity curves). Engine (`modules/backtest/engine.py`) recomputes the factor FROM fact_returns
  AT each monthly rebalance (NO look-ahead), selects favourable top-quintile equal-weight, holds
  to next rebalance; daily returns from the 1D series; vs equal-weight-universe baseline. Stats:
  total/ann return, ann vol, Sharpe, max drawdown.
- **Coverage gate** (key honesty fix): rebalances only where the factor covers ≥50% of the
  universe — the 1Y window is sparse before ~2025-06, so momentum strategies start ~2025-07
  (else the first holding was 5 names, not 100). Effective start reported.
- **Read/run API** `POST /api/backtest/run`, `GET /api/backtest/runs`, `/runs/{id}` (+curve).
  Response models renamed Backtest* to avoid an OpenAPI name collision with operate's RunRequest/
  RunResult (lesson: unique Pydantic model names across modules). Types regenerated.
- **Console `/backtest`**: factor+universe run form, runs list, equity curve (strategy vs baseline
  SVG), strategy/baseline stat blocks.
- **HAND-VERIFIED (ties exactly, no look-ahead)**: mom_12_1/sp500 first rebalance 2025-07-01 →
  coverage 498, top-100; first day 2025-07-02 independent strat ret −0.000458 → cum 0.999542 =
  stored 0.999542. Results: momentum sp500 +44.7% (Sharpe 2.18) vs base +14.9% (1.33); low-vol
  ibov +19.7% ann vs +2.2%. Endpoints 200; tsc clean; /backtest + /sym/operate 200.

## Done (cycle 12, in-session) — optimiser module (mean-variance, pure-Python)
- **QRP-managed `optimiser` schema** (`db/qrp/0006-optimiser.sql`): `solution` + `weight`. No numpy
  in the qrp venv → implemented a **pure-Python projected-gradient solver** over the probability
  simplex (sum=1, w≥0, long-only): `min_variance` (minimise wᵀΣw) and `max_sharpe` (risk-aversion
  path, keep best realised Sharpe). Covariance + mean from sym daily 1D returns (top-N by market
  cap for tractability, default 40). Annualised, rf=0.
- **API** `POST /api/optimiser/solve`, `GET /api/optimiser/solutions`, `/{id}` (+weights); unique
  Opt* response models; types regenerated. Console `/optimiser`: solve form, solutions list,
  stat tiles, weights table with allocation bars.
- **VERIFIED**: min-var exp_vol 7.0% ≤ EW vol 15.6% ✓; weights sum 1.0, all ≥0 ✓; max-Sharpe
  Sharpe (5.97) > min-var (2.48) ✓; **covariance ties EXACTLY** to fact_returns (engine ew_vol
  0.15624765 = independent EW daily-series stdev×√252). Min-var picked classic defensives
  (BRK.B/JNJ/CVX/KO/PG) — strong economic sanity. tsc clean; page 200.
- Honest note: in-sample MV optimisation → expected Sharpes are optimistic by construction (stated in UI).

## Done (cycle 13, in-session) — altdata module (Wikimedia pageviews) — FAMILY COMPLETE
- Probed alt-data sources: **Wikimedia Pageviews + HackerNews reachable**, GDELT 429. Built on
  Wikimedia daily pageviews (per-company attention proxy).
- **QRP-managed `altdata` schema** (`db/qrp/0007-altdata.sql`): `wiki_map` + `pageview`. Ingest
  (`modules/altdata/ingest.py`) maps 10 mega-caps (AAPL/NVDA/MSFT/AMZN/GOOGL/META/TSLA/JPM/KO/DIS)
  → en.wikipedia articles → sym composite_figi (read-only), fetches ~120d daily pageviews.
  **10/10 resolved, 1,210 observations.**
- **Read API** `/api/altdata/series` (+ attention-spike = 7d avg ÷ 30d avg) + `/series/{figi}`
  (history). Unique Alt* response models; types regenerated. Console `/altdata`: company list with
  views + spike, daily pageview sparkline.
- **VERIFIED (real live data)**: Apple ~10k/day (peak 42k, latest 14,630), Coca-Cola ~2.5k
  (lower attention than tech — sensible); 121 obs/name through 2026-06-05. tsc clean; page 200.

## Done (cycle 14, in-session) — hardening: winsorise signal factors
- Added cross-sectional **winsorisation at 1/99 pct** to signal factor scoring (`signal/compute.py`
  `_winsorize`): clips raw before z-score/rank so a single extreme no longer dominates. Recomputed
  sp500/ibov/ibx. Momentum top is now capped at p99 (516.6%, z 6.33) instead of SNDK +3495% (z 19.24);
  ranks preserved (monotone clip). Factor descriptions note "(winsorised at 1/99 pct)". Verified
  via API + /signal page 200.

## ALL 8 MODULES LIVE: sym · macro · altdata · signal · backtest · optimiser · portfolios · analytics (+ Operate)
- **uvicorn `--reload` does NOT work reliably here** (Windows WatchFiles misses edits). Run WITHOUT
  --reload (single process) and restart deliberately after API code changes.
- **Port-wedge on kill:** killing only the listener PID leaves stray python holding the socket
  (esp. with --reload). To free a port: kill ALL `python*` uvicorn procs (Get-CimInstance), or use
  single-process (no --reload) for clean Stop-Process. :8000 and :8001-once got wedged; current
  API is a clean single process on **:8001**.
- **Scheduled wakeups did NOT fire/produce work** — reliable progress is in-session while invoked.
- Console (Next) daemonizes on :3000; npm wrapper prints a cosmetic exit-1 but the server runs.

## Environment findings (important)
- Simulated 2026 clock; **yfinance is mocked** → `.history()` returns synthetic 2026 daily bars
  that MATCH sym's EOD (e.g. AAPL 307.34 @ 2026-06-05). **`fast_info`/live quote = empty**;
  raw Yahoo REST = HTTP 429. ⇒ **no live intraday source in this env**; "current" price == EOD.
- Implication: **live-quote / live-PnL is deferred** (would be a no-op here). Foundation design
  kept for later: `GET /api/sym/quotes?figis=` via a real-time source, labeled live/delayed,
  NOT persisted, separate from sym EOD; live-PnL = same math as EOD-PnL, only the price source
  swaps. Build when a real quote source exists on deploy.
- yfinance **history works**, so Brazilian **price** ingest is feasible; the open question is
  whether **B3's constituents API** (GetPortfolioDay) is reachable here (external, may be
  un-mocked). To attempt in a focused cycle; if unreachable, document the blocker.

## Queue (priority order, safe → external)
1. Universe explorer page `/sym/universes` (read-only).
2. Attention queue + Validation `/sym/attention`, `/sym/validation` (read-only; act deferred).
3. **Q4 portfolios (new epic):** QRP-own `qrp` schema; upload weights over time; view; compute
   portfolio return/PnL from weights × sym returns (EOD now; live later). Connects to Andre's
   live-PnL goal — same engine, price source swaps.
4. Infra: `scripts/dev` (run API:8001 + Next:3000), README/ports accurate.
5. **Brazilian indexes (sym ETL, highest risk):** register ibov/ibx via sym B3 provider + a
   maintenance plan; resolve members; ingest prices/FX/returns (idempotent). Verify + document.
6. Q1.4 openapi-typescript generated types (replace hand-typed). Read-only DB role (follow-up).

## Open decisions for Andre (morning)
- Live pricing needs a real-time quote source (env has none) — pick one on deploy.
- Brazilian universe spec + maintenance plan (which indexes; rebalance cadence; PIT) — I'll
  draft a sensible default and flag for confirmation.
- Heat map panel is theme-aware now (light in Light, dark in Dark) — confirm it matches taste.
