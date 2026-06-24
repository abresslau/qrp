# Story: Commodities store — Tier-A daily commodity prices + `/commodities` monitor page

Status: done

<!-- Built autonomously from the v1 Build Spec decided in the 2026-06-23 brainstorm
(_bmad-output/brainstorming/brainstorming-session-2026-06-23-224317.md, "v1 Build Spec (decided)"),
which paused with "Andre → build the monitor page autonomously". No prior bmad-create-story step;
this artifact records the build + the code-review outcome retrospectively. The NEW `commodities`
peer package is the second instantiation of the per-package direction after `rates`. -->

## Story

As a researcher/backtester on QRP,
I want **a trustworthy PIT store of daily commodity prices** across all the major sectors, with a
**Bloomberg-style monitor page**,
so that commodities become a first-class, point-in-time-correct asset class alongside equities,
indices, FX and rates — ready for downstream signal/backtest work.

## Scope (v1, Tier-A only)

- **NEW peer package** `packages/commodities/` modeled on `rates` (standalone, library-first, own
  `commodities` DB; PG* env DSN; no `qrp_api` import).
- **Tier A only:** vendor continuous front-month series per commodity. NO dated-contract matrix /
  roll / expiry / open-interest logic in storage (deferred Tier B).
- **Source:** yfinance continuous `=F` tickers — daily OHLCV+Volume, `Close`≈settlement, no
  `Adj Close`, no OI (probe-confirmed 2026-06-23).
- **Canonical model:** `commodity_code` controlled vocab + `sector`; mandatory explicit
  `unit`/`currency`/`exchange`; canonical `as_of_date` (= vendor trading date); raw-only storage;
  PIT = immutable `first_settle` + restated `settle`; change/returns/vol derived on read.
- **Universe:** 22 codes across all six sectors (energy / precious metals / base metals / grains /
  softs / livestock).
- **Pipeline:** source-adapter protocol (`PriceSource`), `price load` / `price coverage` /
  `validate` verbs, four light data-quality checks, Dagster `commodities` job + schedule.
- **Console:** `/commodities` — sector-grouped board (last / Δ / %Δ / sparkline), sector heatmap,
  click-through history chart via `lib/date-axis`.

## Build

- `packages/commodities/`: `db.py` (own-DB DSN), `sources/{base,yfinance_src}.py`, `universe.py`
  (22 commodities), `ingest.fill_prices` (per-day atomic upsert; immutable first_settle + restated
  settle; opt-in plausibility band), `validate/checks.py` (coverage/recency/settle-sanity/staleness),
  `gateway.py` (board/history/coverage, derive-on-read), `router.py` (`/api/commodities/board`,
  `/history/{code}`, `/coverage`), `cli.py`.
- `db/deploy/price_daily.sql` (schema: `price_daily` + `price_review` queue).
- `apps/web/app/commodities/page.tsx`: sector-grouped board + heatmap + history chart.
- Wiring: `platform.toml` module (enabled), `pyproject.toml` + `services/api/pyproject.toml`
  workspace member, `services/api/.../main.py` router mount (entitlement-gated).

## Verification

- 9 commodities tests green (`test_universe`, `test_ingest`, `test_gateway`); ruff clean.
- Dagster `lineage.definitions` loads with `commodities_daily` registered (America/New_York, STOPPED).
- Web tsc/eslint/vitest not runnable locally (see deferred-work caveat) — page logic reviewed by
  inspection; no Next.js API surface touched.

### Review Findings (bmad-code-review, 3 adversarial layers — Blind Hunter / Edge Case Hunter /
### Acceptance Auditor, 2026-06-24)

Triage: 0 decision-needed · 6 patch (applied) · 6 defer · ~9 dismissed. No unresolved High/Med.

- [x] [Review][Patch] Restated OHLC/volume silently dropped when `settle` unchanged — broaden the
      UPSERT `WHERE` guard to all OHLCV columns [ingest.py]
- [x] [Review][Patch] No Sqitch plan/conf/revert/verify (F1) — added `sqitch.conf`+`sqitch.plan`+
      `revert/`+`verify/`, registered in `tools/deploy_all.py`
- [x] [Review][Patch] No Dagster schedule (F2) — added `commodities` job + `commodities_daily`
      schedule (explicit tz America/New_York, STOPPED) + `definitions.py` registration
- [x] [Review][Patch] yfinance silent total-data-loss — warn when a ticker returns rows but keeps
      zero (column-shape change / all-NaN Close) [sources/yfinance_src.py]
- [x] [Review][Patch] CLI cleanup — drop no-op `band` tautology, reject `--band_pct <= 0`, close the
      load conn in `finally` [cli.py]
- [x] [Review][Patch] Page cosmetics — `fmtPrice` decimal tier (natgas ~3) + "Latest as-of" = max
      not first row [page.tsx]
- [x] [Review][Defer] band baseline never advances after a flag — floods review on a real regime
      shift (opt-in, matches `rates`)
- [x] [Review][Defer] 430-day board window can blank 1Y/YTD for a commodity lagging the global max
- [x] [Review][Defer] `validate` uses naive `date.today()` (no tz / no as_of_date param like `rates`)
- [x] [Review][Defer] history 1Y/5Y cutoff uses `365*yrs` (ignores leap days; chart-window cosmetic)
- [x] [Review][Defer] no source-adapter registry module (single source; add with the 2nd source)
- [x] [Review][Defer] universe 22 codes < ~25–30 target; base metals thin (COPPER only)
- Dismissed: DSN override / `.env` quote-strip (byte-identical to `rates`), `audit` verb (=`coverage`,
  mirrors `rates`), 1D = prior-session (the convention), settle-sanity dead NULL arm + sparkline /
  Feb-29 / `_pct` zero-guard / router conn-finally (all verified handled).

## Deferred / follow-ups (Tier B etc.)

- Tier B (full futures curve + vol/OI; paid/alt source) — term structure, carry, calendar spreads,
  our own roll + back-adjustment.
- Pre-2000 deep history + Open Interest (secondary source).
- Liquidity-based roll (vol/OI crossover) once Tier B lands.
