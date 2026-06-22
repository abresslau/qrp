# Story: WEI — World Equity Indices monitor (Bloomberg-WEI-style board)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want a **World Equity Indices** monitor — a single board of the major global equity indices grouped
by region, each showing last level, net change, % change, and YTD, colour-coded up/down — like the
Bloomberg **WEI** screen,
so that I can scan world markets at a glance from QRP's own data.

## Background / research (what the BBG WEI screen is)

Bloomberg's **WEI** ("World Equity Indices") is a non-security monitor: dozens of headline equity
indices on one screen, **grouped by region — Americas, EMEA, Asia/Pacific** — with per-index columns
roughly: **index name · last value · net change · % change · time/as-of · (local) currency**, plus a
YTD/range column in fuller views, and **green = up / red = down** colour coding. (Sources: Bloomberg
WEI is documented as the index-menu monitor across public university Bloomberg guides; we are
reproducing the FUNCTIONAL layout only — NOT Bloomberg's proprietary visual design, branding, or any
screenshot. This is a QRP-native board over our own `index_levels`.)

**We can't access a Bloomberg Terminal** — so "reproduce" = build a QRP page with the same *function*
(regional board of indices with last / net-chg / %-chg / YTD, up-down colour), styled in our own
console design, sourced from our warehouse.

## What QRP already has (reuse — do NOT reinvent)

- **`index_levels`** (sym): immutable EOD level series for ~25 world equity indices, keyed on `sym_id`,
  loaded by the benchmark registry (`packages/sym/src/sym/benchmarks/levels.py` `BENCHMARKS`) +
  `sym msci-pull`. Present today (live-verified): S&P 500 (+Total Return / MidCap 400 / SmallCap 600),
  Nasdaq Composite, Dow Jones Industrial Average, Russell 2000, IBOVESPA; EURO STOXX 50, FTSE 100, DAX
  (Total Return), CAC 40, IBEX 35, FTSE MIB, AEX, SMI; Nikkei 225; and the MSCI globals
  (World/ACWI/EAFE/EM/Europe/USA). Each `instrument` has a `currency_code` + name + yahoo/msci xref.
- **Indexes API** (`services/api/src/qrp_api/modules/sym/{gateway,router}.py`, story
  `indexes-msci-eod-pull-and-page`): `GET /api/sym/indexes` (list: sym_id, name, currency, msci_code,
  variant, n_levels, first/last_date, last_level) + `GET /api/sym/indexes/{sym_id}/levels` (series +
  trailing returns). The WEI board needs last + PRIOR level (1D net/%) + YTD per index in ONE call —
  extend the gateway (don't N+1 the per-index endpoint).
- **Indexes console page** (`apps/web/app/sym/indexes/page.tsx`) + the sym subnav (`apps/web/lib/nav.ts`).
- **Colour + format conventions:** the Indexes page's `Ret`/`fmtPct`/`fmtLevel`; the heatmap/movers
  use emerald/rose for up/down. The shared date axis (`lib/date-axis.ts`) for any sparkline.
- **Live quotes machinery** (QH.2): exists for equities by FIGI; indexes are EOD here. v1 WEI is EOD
  (1D = last vs prior session) — clearly labelled "EOD"; a LIVE index mode is a follow-up (Open Q#3).

## Acceptance Criteria

1. **A WEI board endpoint.** `GET /api/sym/indexes/board` returns, in ONE call, every equity-index
   instrument that has levels, each with: `sym_id`, `name`, `region`, `currency`, `last` (latest
   level), `last_date`, `prev` (the prior session's level), `chg` (last−prev), `chg_pct` ((last/prev)−1),
   `ytd` (vs prior year-end, reusing the `_trailing_returns` logic), and `spark` (a small recent level
   series, e.g. last ~30 points, for an inline sparkline). Read-only; mirror the existing sym
   gateway+router pattern. Nulls where a series is too short (no prior session / no prior year-end).
2. **Region grouping (data-driven, not hardcoded in the page).** Each index resolves to a region —
   `Americas` | `EMEA` | `Asia-Pacific` | `Global` — derived in the warehouse layer. Add a `region`
   to the benchmark registry (`Benchmark` dataclass + a `region` per entry; MSCI globals → `Global`),
   surface it on the instrument read (e.g. join or a small `index_region` lookup), and return it in
   the board payload. Do NOT hardcode the region list in the React page.
3. **The WEI page.** A new console route (added to the sym subnav, e.g. `/sym/wei`, label "WEI" or
   "World indices") rendering a board **grouped by region** (Americas, EMEA, Asia-Pacific, Global —
   each a labelled section), each a table: **Index · Last · Net Chg · %Chg · YTD · Ccy · As of**,
   sorted within region (by |%chg| desc, or name — pick one, document it). **Up = emerald, down =
   rose** on Net Chg / %Chg / sparkline. Inline sparkline per row (reuse the SVG line approach;
   coloured by the spark's own direction). SSR-safe, dark-mode aware, no new dependency.
4. **MSCI variant handling.** The board shows ONE row per market index; for MSCI globals show the
   **Net Return** variant only (not PR/GR triplets) so the board isn't cluttered — filter to NETR (or
   the canonical variant) for the Global section. Exchange indices (S&P 500 etc.) are one row each.
5. **Honest freshness.** Header shows the board is **EOD** with the latest `as_of` date; rows whose
   `last_date` lags the board's max date are visibly marked stale (per `freshness_per_market` —
   markets close on different calendars, so don't imply a single global "today"). Never invent a live
   quote.
6. **No regression.** Existing Indexes page, the indexes API, `index_levels` immutability, the benchmark
   seed, and all suites stay green. `ruff`/`tsc`/`eslint`/`vitest` clean.
7. **Tests.** (a) gateway `board()` computes last/prev/chg/chg_pct/ytd + region from a fake conn
   (DB-free, mirror `test_indexes_route.py`); (b) route exists + shape; (c) web: the WEI page renders
   the regional sections + rows + up/down colour from a fixture (vitest), SSR-safe; (d) region mapping
   unit (e.g. S&P 500 → Americas, FTSE 100 → EMEA, Nikkei → Asia-Pacific, MSCI World → Global).

## Tasks / Subtasks

- [x] Task 1: Region on the benchmark registry (AC: #2, #7d) — added `region` to `Benchmark` (set per
  entry: Americas/EMEA/Asia-Pacific; MSCI World → Global) + `region_for(name, currency)` (MSCI-prefix →
  Global; registry name map; currency fallback). DB-free unit tests (S&P→Americas, FTSE→EMEA,
  Nikkei→Asia-Pacific, MSCI→Global, currency fallback, every-benchmark-has-a-region).
- [x] Task 2: Gateway `index_board()` + `GET /api/sym/indexes/board` (AC: #1, #4, #5) — TWO queries
  (no N+1): a ranked CTE for last + prior session per index, and one recent-levels query for YTD base +
  30-pt sparkline. Computes chg/chg_pct/ytd; region via `region_for`; **MSCI filtered to NETR only**.
  `IndexBoardRow` model. Fake-conn test: chg/chg_pct/ytd, region, Net-only filter (GRTR dropped).
- [x] Task 3: WEI page `app/sym/wei/page.tsx` + "World indices" subnav entry (AC: #3, #5) — region
  sections (Americas/EMEA/Asia-Pacific/Global), per-row table (Index/Last/Net-chg/%chg/YTD/30d-spark/
  Ccy/As-of), emerald/rose up-down, inline sparkline coloured by direction, EOD "as of" header + per-row
  stale marker (●), honest empty state. 3 vitest tests.
- [x] Task 4: Verify (AC: #6) — 814 sym + 150 api + 113 web tests green; ruff/tsc/eslint clean.
  Real-Chrome CDP `/sym/wei`: 4 region sections in order, 23 rows, 27 sparklines, "EOD · as of
  2026-06-19", 31 green/38 red cells, 17 per-market stale markers.

### Review Findings (code-review of the Monitor arc, 2026-06-22 — Blind/Edge/Acceptance layers)
- [x] [Review][Patch] Stale ● tooltip asserted "(market holiday)" as fact — a lagging `last_date` can be a data gap, not a holiday (3 layers flagged; honesty). Reworded to "No session on {boardDate} — showing the last close, {last_date} (this market's calendar lags the board date)" [apps/web/app/monitor/wei/page.tsx]. 7 wei-page tests green.
- [x] [Review][Defer] "1D" net/chg can silently span a multi-day/multi-year gap for a dormant/sparse index — `prev` is the 2nd-newest session ≤ anchor regardless of how far back; such a row is also stale-flagged + has empty spark/52w. Real indices are daily; gate `prev` to an adjacent session if a sparse index ever appears [services/api/.../sym/gateway.py `index_board`].
- [x] [Review][Defer] Pre-history as-of date shows the "Seed indices with sym msci-pull" empty state (implies the warehouse is empty when it just has no data ≤ that date) — recoverable via Latest; copy-only fix when picked up [apps/web/app/monitor/wei/page.tsx].
- [x] [Review][Defer] MSCI single-country names (e.g. "MSCI Japan") resolve region/country → "Global" — only USA/Europe are special-cased; latent (only MSCI World Net is seeded today) [packages/sym/src/sym/benchmarks/levels.py `region_for`/`country_for`].
- [x] [Review][Defer] `d5` uses 7 calendar days so it drifts vs "5 trading sessions" across holidays; `compareRows` sinks nulls regardless of sort direction while the header arrow flips (cosmetic, untested null-descending path) [services/api/.../sym/gateway.py; apps/web/app/monitor/wei/page.tsx].
- Dismissed: region_for/REGION_ORDER latent-drop (already ledgered round 1); the as-of YTD fake-conn test can't catch a `_trailing_returns` "today" anchor (accepted DB-free unit convention); scope-bleed of sibling FX/reconcile code into the arc diff (arc-review artifact).

## Dev Notes

### Where this fits
Frontend page + one read endpoint + a registry field. No new data ingestion — the indices are already
in `index_levels` (extend coverage later via `sym msci-pull` / the benchmark seed). Reuses the indexes
gateway/router, the console module/subnav pattern, the up/down colour + format helpers, and the shared
sparkline/axis. Sibling of the `indexes-msci-eod-pull-and-page` story (same data, different view).

### Critical conventions (regressions if violated)
- **Region is data-driven** (warehouse layer), never a hardcoded map in the React page.
- **EOD honesty** — 1D = last vs prior session; mark per-market staleness (`freshness_per_market`,
  per-member recency, never a global max-date "today"); never fabricate a live quote.
- **One row per market index**; MSCI globals = NETR only (no PR/GR clutter).
- **Up/down colour** = emerald/rose (match heatmap/movers/Indexes `Ret`).
- **Immutable `index_levels`**, read-only API (`qrp_readonly`), `as_of_date` naming, no new dependency,
  SSR-safe + `react-hooks` lint.
- **Verify via headless Chrome/CDP**; never `npm --prefix` (per `feedback_minimize_dev_churn`). The date
  axis / sparkline must use the shared `lib/date-axis` (per `feedback_chart_date_axis`) if it has a time axis.
- **No Bloomberg IP** — functional reproduction in QRP's own design; no Bloomberg branding, colours-as-copied,
  or screenshots.

### References
- [Source: packages/sym/src/sym/benchmarks/levels.py] — `BENCHMARKS` registry (add `region`).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — `indexes()`/`index_levels()`/`_trailing_returns` to extend.
- [Source: services/api/src/qrp_api/modules/sym/router.py] — index endpoints + response-model pattern.
- [Source: apps/web/app/sym/indexes/page.tsx] — list/chart/format/colour conventions to mirror.
- [Source: apps/web/lib/nav.ts] — `SYM_SUBNAV` (add the WEI entry).
- [Source: memory feedback_freshness_per_market, feedback_chart_date_axis, feedback_minimize_dev_churn].
- Bloomberg WEI (functional reference only): public Bloomberg index-menu guides (Xavier/Stevens/Baker
  Library Bloomberg tutorials) — regional board of indices with last/net-chg/%-chg, up/down colour.

## Open Questions (for Andre — defaults chosen, do not block)
1. **Sort within region:** default = by |%chg| desc (biggest movers first). Alt: alphabetical, or by
   market cap/importance. Say which.
2. **Columns:** default Last / Net Chg / %Chg / YTD / Ccy / As-of + sparkline. Add 1W/1M/range/volume? (volume isn't stored for indices.)
3. **LIVE mode:** v1 is EOD. A live index board (intraday via the Yahoo chart REST for `^GSPC` etc.,
   like QH.2 quotes) is a clear follow-up — flag if you want it now.
4. **Which indices / regions:** default = all equity indices in `index_levels`, MSCI globals as NETR
   under "Global". Want more single-country indices seeded (e.g. Hang Seng, KOSPI, ASX, TSX, Sensex) via
   `sym msci-pull`/benchmark seed first? They'd need Yahoo symbols or MSCI codes.

## Dev Agent Record

### Completion Notes
- **Task 1 — region on the registry.** Added `region: str` to the `Benchmark` dataclass and set it on
  every `BENCHMARKS` entry (US/Brazil → Americas; European → EMEA; Nikkei → Asia-Pacific; MSCI globals →
  Global). `region_for(name, currency)` resolves any index not in the registry: MSCI-name prefix → Global,
  then a name map, then a currency fallback (`_AMER`/`_EMEA`/`_APAC` sets), default Global. 8 sym
  benchmark tests pass; ruff clean.
- **Task 2 — board endpoint.** `DbSymGateway.index_board()` runs TWO queries (no N+1): (a) a ranked CTE
  (`row_number() OVER (PARTITION BY sym_id ORDER BY session_date DESC)` with `FILTER (WHERE rn=1/2)`) for
  last + prior session per index; (b) one recent-levels query (`session_date >= max - 420d`) for the YTD
  base + the 30-pt sparkline. Computes chg/chg_pct/ytd, region via `region_for`, and **filters MSCI to the
  NETR variant only** (Net Return — no PR/GR clutter). `IndexBoardRow` response model; route registered
  before the `{sym_id}` path. 5 api tests (chg/chg_pct/ytd, region, Net-only filter, route exists); ruff clean.
- **Task 3 — WEI page.** `app/sym/wei/page.tsx` renders region sections in fixed order
  (Americas/EMEA/Asia-Pacific/Global), each a table (Index/Last/Net-chg/%chg/YTD/30d-spark/Ccy/As-of),
  sorted within region by |%chg| desc (biggest movers first — documented in AC #3 / Open Q#1). Emerald/rose
  up-down via `upDown()`; inline `Spark` SVG coloured by its own direction; EOD "as of {max date}" header;
  per-row amber ● stale marker when `last_date < boardDate` (per-market calendars, `freshness_per_market`);
  honest empty state pointing at `sym msci-pull`. Added the "World indices" entry to `SYM_SUBNAV`. SSR-safe
  (no SSR-only globals); 3 vitest tests; tsc + eslint clean.
- **Task 4 — verify.** 814 sym + 150 api + 113 web tests green. Real-Chrome CDP at `/sym/wei`: 4 region
  sections in order, 23 rows (Americas 8 / EMEA 8 / Asia-Pacific 1 / Global 6 — MSCI shown as Net only),
  27 sparklines, header "EOD · as of 2026-06-19", 31 emerald / 38 rose cells, 17 per-market stale markers.
- **No regression.** Existing Indexes page, indexes API, `index_levels` immutability, and the benchmark
  seed untouched; the board reuses `_trailing_returns`-style YTD logic and existing colour/format idioms.

### File List
- `packages/sym/src/sym/benchmarks/levels.py` (modified — `region` field + `region_for`)
- `packages/sym/tests/test_benchmarks.py` (modified — region tests)
- `services/api/src/qrp_api/modules/sym/gateway.py` (modified — `index_board()`)
- `services/api/src/qrp_api/modules/sym/router.py` (modified — `IndexBoardRow` + `/indexes/board`)
- `services/api/tests/test_indexes_route.py` (modified — board fake-conn test + route assert)
- `apps/web/app/sym/wei/page.tsx` (new — WEI board page)
- `apps/web/__tests__/wei-page.test.tsx` (new — 3 web tests)
- `apps/web/lib/nav.ts` (modified — "World indices" subnav entry)

## Change Log
| Date | Change |
|---|---|
| 2026-06-21 | Dev complete → review. region on the benchmark registry + `region_for`; `index_board()` gateway (ranked-CTE last/prev + recent-levels YTD/spark, MSCI→NETR only) + `GET /api/sym/indexes/board` + `IndexBoardRow`; `/sym/wei` page (regional board, up/down colour, sparkline, EOD/stale freshness) + subnav. 814 sym + 150 api + 113 web tests green; ruff/tsc/eslint clean; real-Chrome CDP verified (4 regions, 23 rows, sparklines, EOD as-of, stale markers). |
| 2026-06-21 | Created story: WEI World Equity Indices monitor — a Bloomberg-WEI-style regional board (Americas/EMEA/Asia-Pacific/Global) over QRP's `index_levels`, each row last/net-chg/%-chg/YTD + sparkline, up/down colour. New `GET /api/sym/indexes/board` (last+prior session+ytd+region in one call) + region on the benchmark registry + new `/sym/wei` page. Functional reproduction (no Bloomberg IP); EOD honesty; reuses the indexes gateway/page/conventions. Status → ready-for-dev. |
