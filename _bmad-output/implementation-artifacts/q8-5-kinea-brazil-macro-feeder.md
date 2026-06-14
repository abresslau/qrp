# Story Q8.5: Open-source Brazilian / central-bank macro feeders (Kinea-inspired)

Status: done

<!-- Created via bmad-create-story from the directive: "investigate all macro datasets used
on kinea.com.br/blog, catalog the necessary data, and create an open-source feeder." The
operator then directed live implementation overnight; this file is both the story spec and
its build record. -->

## Story

As the Operator,
I want the macro store fed from the **central banks and official statistics offices** that
Brazilian/EM sell-side research (Kinea, BTG "Brazil Macro Scenario") actually builds its
views on — via **free, key-less, open APIs** — and the macro console to present them the way
a research desk would,
so that QRP's macro layer is a real research surface (Selic, IPCA, fiscal, FX, activity,
labour, external) rather than a thin World-Bank-only panel, with every series source-attributed
and never fabricated.

## Investigation — what Kinea/sell-side macro research uses

Read directly: the Kinea blog (`kinea.com.br/blog`) "Cartas do Gestor" (6 letters) + the BTG
Pactual *Brazil Macro Scenario, June 2026* deck (92 pp; sections Global · Activity · Inflation ·
Monetary Policy · Fiscal · External — the canonical sell-side macro structure). The recurring
inputs, by theme:

| Theme | Indicators they track | Authoritative source | Free API |
|------|----------------------|---------------------|----------|
| Monetary/Rates | Selic (target + effective), DI curve, real rate | BCB (Copom) | **BCB SGS** ✓ |
| Inflation | IPCA (m/m, 12m, cores, YTD), IGP-M, Focus expectations | IBGE / BCB | **BCB SGS + IBGE SIDRA + BCB Focus** ✓ |
| FX | BRL/USD (PTAX) | BCB | **BCB SGS / Olinda PTAX** ✓ |
| Activity | IBC-Br, PIB (quarterly) | BCB / IBGE | **BCB SGS + IBGE SIDRA** ✓ |
| Labour | Unemployment (PNAD-C), CAGED | IBGE / MTE | **IBGE SIDRA** ✓ (CAGED deferred) |
| Fiscal | Primary result, Arcabouço, deficit | BCB / Tesouro | **BCB SGS** ✓ |
| Debt | Gross debt DBGG, net debt | BCB | **BCB SGS** ✓ |
| External | Current account, reserves, trade balance | BCB / MDIC | **BCB SGS** ✓ (SECEX trade deferred) |
| Money/Credit | M2/M3/M4, credit/GDP | BCB | **BCB SGS** ✓ |
| US/global | Fed funds, UST 2y/10y/30y, Core PCE/CPI, payrolls, deficit | Fed/BLS/BEA/Treasury | **US Treasury XML + FiscalData**; BLS/BEA deferred (FRED blocked in-env) |
| Commodities | Brent, gold, nat gas, grains | EIA/ICE/USDA | **deferred** (World Bank Pink Sheet candidate) |

Full source dossier (endpoints, series codes, quirks) retained from the research subagents in
the story's working notes; the implemented subset is recorded below.

## Acceptance Criteria

1. At least one **central-bank** source feeds the macro store (the gap the operator flagged). ✓ BCB SGS.
2. Every new source is **free / no API key**, **reachability-probed in-env** before building, and
   **never fabricates** (empty/unserved series dropped, not faked). ✓
3. New sources follow the existing `macro.sources` (fetch → `(meta, obs)`) + `macro.ingest`
   (`_upsert`, per-series failure attribution) contract; categories obey the `^[a-z]+$` CHECK
   and the console submenu picks them up live. ✓
4. DB-free parser unit tests for each new fetcher; ruff clean; `run_ingest` dispatch tests cover
   the new paths. ✓ (41 macro tests pass.)
5. The macro console presents the data **like sell-side research** (cockpit cards, theme-grouped
   change table, proper featured chart). ✓

## Tasks / Subtasks — build record

- [x] **BCB SGS feeder** (`fetch_bcb_sgs`): decade-chunked (≤10yr server cap), labelled-unit
  scaling, step-compression for policy rates, retry+backoff (BCB 429/timeout). 15 series:
  Selic target/effective, IPCA m/m + 12m, IGP-M, BRL/USD PTAX, IBC-Br SA/NSA, primary result,
  DBGG + net debt, current account, reserves, M3, credit/GDP. Codes verified live 2026-06-14.
- [x] **IBGE SIDRA feeder** (`fetch_sidra`): flat-array + legend parsing, period dimension found
  by name (PIB's is D4 not D3), monthly (AAAAMM) + quarterly (AAAA0T) codes, sentinel skipping.
  4 series: PNAD-C unemployment, quarterly PIB, IPCA index + YTD.
- [x] **BCB Focus feeder** (`fetch_bcb_focus_12m`): OData, paged, 12m-ahead IPCA expectation
  (the anchor a desk tracks vs realised inflation).
- [x] **US Treasury par yield** extended to 3M/2Y/10Y/30Y (the 2s10s + long-end tenors).
- [x] **Global panel broadened** (separate same-session work folded in): World Bank 5→15
  economies; OECD CPI 4→12; +GDP level/per-capita, lending rate, govt debt, current account,
  exports/imports, broad money; ECB deposit-facility + marginal-lending rates. New categories
  fx/activity/fiscal/external.
- [x] **Sell-side display**: gateway enriches `/api/macro/series` with 1m/3m/12m/YTD deltas +
  48-pt sparkline (one lateral-join pass, ~40ms); cockpit cards, theme-grouped change table,
  featured chart with gridlines/axes/last-value annotation. Types regenerated.
- [x] Tests (41 pass), ruff clean, typecheck clean, new component lints clean.

## Result

Macro store: **33 series / 12k obs → 235 series / 93k obs**, 12 categories, central banks
included (sources: bcb 15, bcb_focus 1, ibge 4, treasury 4, + worldbank/oecd/ecb/eurostat/
fiscaldata). Live values sanity-check against Kinea's narrative (Selic 14.5%, IPCA 12m 4.72%,
Focus 4.04%, BRL/USD 5.08, unemployment 5.8%, DBGG 80.4% GDP, UST 30y 4.97%).

## Deferred (ledgered)

- **Brazilian sources not yet wired:** IPEADATA (reachable; aggregator), full BCB Focus
  (annual IPCA/Selic by reference-year, Top-5), IBGE PMC/PIM (retail/industrial production),
  SECEX/MDIC trade balance, CAGED formal employment, ANBIMA NTN-B real yields, B3 DI curve.
- **US/global gaps (FRED blocked in-env):** BLS CPI/payrolls, BEA PCE/GDP via their own APIs;
  commodities (Brent/gold/grains) via World Bank Pink Sheet or EIA.
- **Display polish:** realised-vs-expected inflation overlay, forecast columns (we hold only
  realised data), per-category "top movers", hover tooltips on the featured chart.
- **Refresh:** a scheduled Dagster ingest (must set `execution_timezone`) — currently manual
  `python -m macro.ingest` / gateway refresh.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8[1m]

### File List
- `packages/macro/src/macro/sources.py` (UPDATE) — `fetch_bcb_sgs`, `fetch_sidra`,
  `fetch_bcb_focus_12m`, `_get_retry`, Treasury tenors 3M/30Y, `_parse_br_date`, `_sidra_period`
- `packages/macro/src/macro/ingest.py` (UPDATE) — `_BCB`/`_IBGE` catalogs + Focus call;
  categories fx/activity/fiscal/external; broadened WB/OECD/ECB
- `packages/macro/src/macro/gateway.py` (UPDATE) — enriched `series()` (deltas + sparkline)
- `packages/macro/src/macro/router.py` (UPDATE) — `SeriesSummary` change/spark fields
- `packages/macro/tests/test_sources.py` (UPDATE) — parser tests for the new fetchers
- `packages/macro/tests/test_ingest.py` (UPDATE) — dispatch tests neutralize new sources
- `apps/web/components/macro-browser.tsx` (REWRITE) — sell-side research display
- `apps/web/lib/api-types.ts` (REGEN)

### References
- [Source: kinea.com.br/blog — Cartas do Gestor]
- [Source: BTG Pactual, Brazil Macro Scenario, June 2026 (operator-provided)]
- [Source: BCB SGS api.bcb.gov.br/dados; BCB Olinda; apisidra.ibge.gov.br; home.treasury.gov XML]
- [Source: packages/macro — existing source/ingest/gateway contract]
