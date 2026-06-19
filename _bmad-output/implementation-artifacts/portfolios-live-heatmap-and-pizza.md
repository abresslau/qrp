# Story: Live portfolio page — heatmap by position size + sector/position pizza

Status: done

<!-- Created via bmad-create-story (2026-06-19). Operator: "I should be able to see a live portfolio
page with Live Risk and Analytics, Heatmap by position size, and Pizza by sector and position size."
Standalone console-enhancement artifact (not in an epic decomposition), like portfolios-exposure-and-
layout.md and the other Q-module console stories — tracked inline here, NOT enumerated in sprint-status.yaml
(per its DERIVATION NOTE). -->

## Story

As the **operator of QRP**,
I want **the portfolio detail page to be a live cockpit — the existing Live Risk & Analytics panel,
plus a heat map of the book sized by position size and recolored by each holding's live return, plus
two "pizza" (pie/donut) charts breaking the book down by sector and by position size**,
so that **I can read a single portfolio the way I read a universe heat map — see at a glance where the
weight sits (by sector and by name) and how each position is moving intraday, honestly labelled
live/delayed with uncovered names neutral, never persisted**.

## Why (current state)

The portfolio detail page (`apps/web/app/portfolios/[id]/page.tsx`) already delivers the **Live Risk &
Analytics** half of this request: the `<AnalyticsPanel>` (top of the page since
`portfolios-exposure-and-layout.md`) shows TWR/PnL, the full risk-metric grid (Sharpe, beta, alpha,
tracking error, …), AND a **Live PnL** strip (QH.2: live quotes vs prior close, honest
live/delayed/unavailable badge, on-demand refresh, not stored — `analytics-panel.tsx:175-204`). Net/gross
exposure sit in the header.

What's **missing** is the *visual composition* of the book:

- **No heat map of the portfolio.** The universe heat map (`heatmap-view.tsx` + QH.9 LIVE recolor) shows
  a treemap sized by market cap / colored by return — but only for a *universe*, never for a *portfolio*.
  An operator can't see their own book as a treemap.
- **No breakdown by sector or by position.** The holdings table is a flat list. There's no "where is my
  weight" view — no sector pie, no position pie.

The data is all in hand and the patterns are all built:

- The portfolio's latest weight vector is read through the A.1 seam `read_latest_weights(conn, pid)` →
  `(as_of_date, {composite_figi: Decimal})` (`packages/portfolios/src/portfolios/gateway.py:19-40`).
  Weights are **signed** (longs +, shorts −), so position *size* = `abs(weight)`.
- The analytics module already reaches those weights without importing the portfolios package (it imports
  the standalone `read_latest_weights` function and opens its own `portfolios` + `sym` connections —
  `analytics/router.py:17-28`, `analytics/gateway.py` imports), and already fans figis out to live quotes
  in `live_pnl()` (`analytics/gateway.py:208-322`).
- Sector/industry (`gics_scd`), ticker/MIC (`security_symbology`, `securities.mic`) and name
  (`security_names`) are all reachable on the `sym` read connection by `composite_figi` — exactly the
  joins the universe heat map uses (`services/api/src/qrp_api/modules/sym/gateway.py:396-438`).
- The live-quote source, the two-tier degradation, the freshness/coverage rollup, the `live_return`
  ratio and the bounded `ThreadPoolExecutor` fan-out all exist (QH.2 + QH.9) and just need to be aimed at
  a portfolio's holdings instead of a universe's members.

So this is a **surfacing + visualization** story: one new analytics endpoint that enriches the shown
weight vector with sector + live return, and two new hand-rolled-SVG console components (heatmap + pizza)
added to the portfolio page. No migration, no schema change, nothing persisted.

## Acceptance Criteria

1. **API — portfolio composition with live returns.** A new endpoint
   `GET /api/analytics/portfolios/{pid}/composition` returns the portfolio's **shown** (latest) weight
   vector enriched per holding with `sector`, `industry`, `name`, `ticker`, `currency`, the **signed**
   `weight`, the live `live_return` (live price / prior close − 1, the QH.2 convention) and per-holding
   `freshness ∈ {live,delayed,unavailable}`; PLUS a top-level `as_of` (oldest priced quote, ISO-8601 UTC),
   `freshness` (worst priced), `weights_as_of`, `n_holdings`, `n_priced`, `total_weight` (Σ|weight|), and a
   `sectors` rollup (one entry per sector: `sector`, `weight` = Σ|weight| in sector, `n`, weighted
   `live_return`). Mirrors `live_pnl()`'s assembly — NOT a reimplementation. Reuses the A.1
   `read_latest_weights` seam (no `portfolios` package import beyond the existing standalone functions).
2. **Honest degradation (reuse the QH.2 two-tier pattern).** A per-holding miss (unmapped MIC, no quote,
   HTTP 4xx) → that holding is `freshness:"unavailable"`, `live_return:null`, `price:null` (renders
   neutral, never a fake 0%). A wholly-unreachable provider (EVERY attempted symbol network-errors) → the
   `503` envelope (`QuoteSourceUnreachable` → `HTTPException(503)`, same as `live_pnl`), and the console
   shows the badge/Retry, not a blank panel. A missing portfolio → `404`. **Writes nothing**
   (grep-assert: no INSERT/UPDATE on the live path).
3. **Bounded fan-out.** Quotes for the holdings are fetched via the **bounded `fetch_quotes_batch`**
   (capped workers + overall wall-clock budget) — ported into the `analytics/quotes.py` twin from the
   `sym/quotes.py` copy (QH.9) so the documented twin stays in sync. The serial per-name loop that
   `live_pnl` uses today is NOT acceptable for a whole-book recolor. A soft cap (`COMPOSITION_MAX`, e.g.
   400 holdings) → a clear `422` over-cap (operator portfolios are small; the cap is a Yahoo-rate-limit
   backstop). The bound + rationale documented.
4. **UI — heatmap by position size.** A new `<PortfolioHeatmap pid=… />` renders a treemap (d3-hierarchy,
   like `heatmap-view.tsx`) of the holdings: **each tile sized by `abs(weight)`** (NOT market cap — this
   is position size), **grouped by sector**, **colored by the holding's live return** on the existing
   ±3% diverging scale (`rgbFor`), uncovered holdings neutral grey. It shows the QH.2/QH.9 live/delayed/
   unavailable badge, `as_of`, `n_priced/n_holdings` coverage, an on-demand **↻ refresh**, and a "not
   stored" note. A hover tooltip shows ticker · name · sector · weight% · live return. Shorts (negative
   weight) are sized by `abs(weight)` and visibly flagged (e.g. a "short" tag / hatched border) so a long
   and a short of equal size aren't indistinguishable.
5. **UI — pizza by sector and by position size.** A new `<PortfolioPizza pid=… />` renders **two**
   hand-rolled-SVG pie/donut charts side by side (responsive: stack on narrow widths): (a) **By sector** —
   one slice per sector sized by Σ|weight|, categorical colors, a legend with sector · share% · weight%;
   (b) **By position** — one slice per holding sized by |weight|, **top-N by size with the tail collapsed
   into an "Other" slice** (a book can have many names), legend with ticker · share% · weight%. Center
   label shows gross (Σ|weight|) and net (Σ weight). No charting library (hand-rolled SVG arcs, the
   `heatmap-view.tsx` / `price-volume-chart.tsx` convention). Both charts may reuse the `composition`
   response (one fetch feeds heatmap + both pizzas).
6. **UI — placement (the "live portfolio page").** On `apps/web/app/portfolios/[id]/page.tsx`, the new
   blocks slot **directly under `<AnalyticsPanel>`** so the live cluster reads together at the top:
   Header (+ net/gross exposure) → **Live Risk & Analytics** (`AnalyticsPanel`, unchanged) → **Heatmap by
   position size** → **Pizza (sector + position)** → Snapshot attribution → Contributions → Upload →
   Holdings → footer. The existing blocks/logic are unchanged — only insertion + surrounding margins.
   A portfolio with no stored vector (`shown_as_of_date == null`) shows a quiet "no weights yet" state in
   each new block, not an error.
7. **Typed contract, tested, no regressions.** The new Pydantic `PortfolioComposition` /
   `CompositionHolding` / `SectorSlice` models added to `analytics/router.py`; `gen:types` regen is a
   pre-deploy step (it needs the running API), and the new components use **local** types (like
   `heatmap-view.tsx`) so nothing blocks on it — ledger it. New tests: **API** — composition assembly
   from a mock weights read + mock quotes (holding shape, signed weight preserved, per-holding freshness,
   sector rollup sums to gross), partial coverage, whole-source-down → 503, per-holding miss → unavailable
   cell, no-vector → empty, over-cap → 422, writes-nothing; **batch** — the ported `fetch_quotes_batch`
   twin tests (partial+dedup, all-network→raise, budget). **Console** — heatmap renders tiles sized by
   weight + LIVE badge + neutral-uncovered + 503→error-not-blank; pizza renders sector slices + position
   slices with an "Other" tail + the sector rollup share. `uv run pytest` (analytics/api), `npm test`,
   `eslint`, `tsc --noEmit`, `next build` all green. No new dependency (`concurrent.futures`/`urllib`
   stdlib; d3-hierarchy already present; pies are hand-rolled SVG).

## Tasks / Subtasks

- [x] **Task 1 — Port the bounded fan-out into the analytics twin** (AC: 3) — copy
  `fetch_quotes_batch` + its constants (`_BATCH_WORKERS`, `_BATCH_BUDGET_S`) from
  `services/api/src/qrp_api/modules/sym/quotes.py` into `packages/analytics/src/analytics/quotes.py`
  (the documented twin — keep them identical, same two-tier contract: per-symbol miss → None, all
  completed network-error → `QuoteSourceUnreachable`). Add the 3 batch tests (partial+dedup,
  all-network→raise, budget) to the analytics quotes test.
- [x] **Task 2 — `DbAnalyticsGateway.composition(pid)`** (AC: 1,2,3) — new gateway method in
  `analytics/gateway.py`. Read the shown vector via `read_latest_weights(self._conn, pid)` (A.1 seam) →
  `{figi: Decimal}`; `portfolio_exists` for the 404. Query the `sym` read conn ONCE for per-figi
  `(ticker, mic, sector, industry, name, currency)` — extend `live_pnl`'s sym metadata query
  (`gateway.py:237-251`) with `gics_scd` (sector/industry, latest by `valid_to`/`valid_from`),
  `security_names` (name), and the currency from `fundamentals` or `securities` (mirror the universe
  heatmap joins, `sym/gateway.py:396-438`). Build Yahoo symbols (`yahoo_symbol_for`), fan out via Task 1's
  `fetch_quotes_batch`, set each holding `price`/`live_return`/`freshness`; roll up `as_of` (oldest
  priced) / worst `freshness` / `n_priced` / `total_weight` (Σ|weight|) and the `sectors` aggregate
  (Σ|weight| + weighted live_return per sector). `COMPOSITION_MAX` over-cap → `ValueError`. NO share-class
  collapse (explicit positions). Writes nothing.
- [x] **Task 3 — Route + models** (AC: 1,2) — `GET /api/analytics/portfolios/{pid}/composition` in
  `analytics/router.py` + `PortfolioComposition`/`CompositionHolding`/`SectorSlice` Pydantic models.
  Error mapping mirrors the live route (`router.py:121-130`): `LookupError`→404, over-cap
  `ValueError`→422, `QuoteSourceUnreachable`→503 (the app-wide `{error:{type:"unavailable"}}` envelope).
- [x] **Task 4 — `<PortfolioHeatmap>`** (AC: 4,6) — new `apps/web/components/portfolio-heatmap.tsx`.
  Adapt `heatmap-view.tsx`: drop the universe/window selectors; fetch `/api/analytics/portfolios/{pid}/
  composition`; group by `sector`; tile `value = Math.abs(weight)`; reuse `rgbFor`/`textInk`/`useIsDark`/
  the ±3% legend, coloring by `live_return` (null → neutral). Live badge + `as_of` + `n_priced/n_holdings`
  + ↻ refresh (nonce) + "not stored"; 503 → error banner above the map (map stays). Flag shorts. Hover
  tooltip (ticker · name · sector · weight% · live return).
- [x] **Task 5 — `<PortfolioPizza>`** (AC: 5,6) — new `apps/web/components/portfolio-pizza.tsx`.
  Hand-rolled SVG donut arcs (no lib). Chart A: slices per `sectors[]` entry sized by `weight` (Σ|weight|).
  Chart B: slices per holding sized by `abs(weight)`, top-N + "Other". Categorical palette, legends with
  share% + weight%, center label = gross/net. Reuse the `composition` response (lift the fetch to the
  page or share via a small hook so heatmap + pizza don't double-fetch — your call, document it).
- [x] **Task 6 — Wire into the page** (AC: 6) — `[id]/page.tsx`: render `<PortfolioHeatmap>` then
  `<PortfolioPizza>` immediately after `<AnalyticsPanel>` (line 126). No-vector → quiet empty state. Keep
  every existing block/logic unchanged; adjust `mt-*` so spacing stays consistent.
- [x] **Task 7 — Tests + verify** (AC: 7) — API: new `services/api/tests/test_portfolio_composition.py`
  (assembly/shape/signed-weight/freshness/sector-rollup/partial/503/unavailable/no-vector/over-cap/
  writes-nothing) mirroring `test_analytics_live_pnl.py`'s monkeypatch pattern; +3 batch tests (Task 1).
  Console: `apps/web/__tests__/portfolio-heatmap.test.tsx` + `portfolio-pizza.test.tsx` (mocked fetch).
  Run `uv run pytest`, `npm test`, `eslint .`, `npx tsc --noEmit`, `npm run build`. Ledger the `gen:types`
  pre-deploy step. Update this story's Dev Agent Record.

### Review Findings (code review 2026-06-19)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Auditor confirmed AC1, AC3,
AC6, the AR-R3 contract handling, the one-fetch promise, signed-weight preservation, short flagging, and
the no-vector empty state are MET. The actionable items:

- [x] [Review][Decision] AC5 legend "share% · weight%" largely duplicate — RESOLVED (option 1, keep ONE
  percentage): the two values are mathematically identical for these donuts (each chart total == gross
  Σ|weight|), so the slice labels now carry only the name and the legend's right column shows the single
  share% (computed once in `Donut`). Removes the duplicate AND the two-denominators drift risk.
- [x] [Review][Patch] All-zero / non-finite weight vector bypasses the empty-state guards — FIXED:
  `composition()` drops non-finite weights (`math.isfinite`); the heatmap + pizza now treat
  `total_weight <= 0` as the empty state [packages/analytics/src/analytics/gateway.py + portfolio-heatmap.tsx / portfolio-pizza.tsx]
- [x] [Review][Patch] Heatmap tooltip left-clamp has no lower bound — FIXED: `Math.max(0, Math.min(…))` [apps/web/components/portfolio-heatmap.tsx]
- [x] [Review][Patch] Pizza slice percentage computed two ways — FIXED as part of the AC5 decision: a single share% from the `Donut` `frac` (one denominator) [apps/web/components/portfolio-pizza.tsx]
- [x] [Review][Patch] Missing console test for the 503 / error path — FIXED: added `portfolio-live.test.tsx` (happy path + a 503 → error-banner-not-blank case on the new Live page) [apps/web/__tests__/portfolio-live.test.tsx]

- [x] [Review][Defer] Route `ValueError`→422 catch is over-broad — any unrelated `ValueError` on the path would be mislabeled an over-cap 422 (only the cap raises `ValueError` today) [packages/analytics/src/analytics/router.py portfolio_composition] — deferred, low-risk robustness.
- [x] [Review][Defer] `test_composition_writes_nothing` only inspects the sym conn — the portfolios conn is `object()` (monkeypatched), so a hypothetical portfolios-side write wouldn't be caught; code is SELECT-only so the property holds [services/api/tests/test_portfolio_composition.py] — deferred, test-coverage caveat.
- [x] [Review][Defer] Net center can render "−0.0%" for a tiny negative net that rounds to 0 [apps/web/components/portfolio-pizza.tsx] — deferred, cosmetic.
- [x] [Review][Defer] First-load 503 shows the error banner but no map (AC4 "map stays" only holds on a failed REFRESH after a good load, where the last-good `comp` is retained); the refresh affordance is also hidden when `n_holdings === 0` [apps/web/app/portfolios/[id]/page.tsx] — deferred, acceptable degradation (matches heatmap-view's last-good behavior); revisit if a first-load retry button is wanted.

#### Dismissed (noise / confirmed-handled)

`classify_freshness(None) → "delayed"` verified (timeless priced quote never paints "live"); div-by-zero
all guarded (`total||1`, `wsum>0`, `sec_cov.get`); `ThreadPoolExecutor` shutdown in `finally` +
AbortController aborted in cleanup (no leaks); SQL parameterized; single-100%-slice donut + zero-value
slice render correctly; top-N/"Other" boundary correct; all-unmapped book → no spurious 503; single-holding
network-error → 503 is intentional (matches `live_pnl` contract); budget biased-subset can't false-raise;
currency mixing in the |weight|-weighted RETURN rollup is sound (returns are unitless); cross-language
API shape (TS `Composition` ↔ Pydantic `PortfolioComposition`) matches field-for-field; `gics_scd` set
move keeps the disjoint invariant.

## Dev Notes

### Current state of files being touched (read in story prep — exact anchors)

- **`apps/web/app/portfolios/[id]/page.tsx`** (UPDATE) — client component, `max-w-4xl`. Order today:
  header + net/gross exposure `100-123`; **`<AnalyticsPanel pid=… />` at line 126** (Live Risk &
  Analytics — keep, this IS the "Live Risk and Analytics" requirement); snapshot attribution `128-158`;
  contributions `160-193`; upload `195-226`; holdings `228-272`; footer `274-277`. `pct`/`retClass`
  helpers `14-20`. Insert the two new blocks right after line 126. `id` from `useParams`; pass
  `String(id)`.
- **`apps/web/components/analytics-panel.tsx`** (READ — no change) — already self-contained Live Risk &
  Analytics incl. the Live PnL strip (`175-204`) with the `FRESH_STYLE` badge idiom (`11-15`) to mirror in
  the new components. Leave it untouched.
- **`apps/web/components/heatmap-view.tsx`** (READ — the template to adapt, NOT edit) — d3-hierarchy
  treemap; `rgbFor(ret,isDark)` (`57-67`) renders `null`→neutral; `textInk` (`84-89`); `useIsDark`
  (`70-81`); `LIVE_STYLE` badge (`39-43`); ±3% legend (`431-454`); the live badge/coverage/refresh block
  (`245-287`). Copy these idioms into `portfolio-heatmap.tsx`; **swap `value: market_cap_usd` →
  `Math.abs(weight)` and drop the universe/window selectors**.
- **`apps/web/components/price-volume-chart.tsx`** (READ — SVG convention) — confirms hand-rolled SVG, no
  chart lib (`32`: "Hand-rolled SVG — consistent with the heatmap (no chart lib)"). The pizza follows this.
- **`packages/analytics/src/analytics/gateway.py`** (UPDATE) — `live_pnl()` `208-322` is the template:
  `read_latest_weights` `219`, the sym metadata query `237-251` (extend with gics/name/currency), the
  per-name quote loop `260-296` (replace the **serial** loop with `fetch_quotes_batch`), the rollup
  `308-321`. `analytics()` (`324-477`, risk metrics) is unrelated — don't touch.
- **`packages/analytics/src/analytics/quotes.py`** (UPDATE) — the twin: has `fetch_raw_quote`,
  `yahoo_symbol_for`, `live_return`, `classify_freshness`, `now_epoch`, `QuoteSourceUnreachable`, `RawQuote`
  — but **NOT `fetch_quotes_batch`** (Task 1 ports it from the sym copy).
- **`packages/analytics/src/analytics/router.py`** (UPDATE) — `_gateway()` `17-28` opens `portfolios` +
  `sym` conns; the live route `121-130` is the error-mapping template; add the new route + models here.
- **`services/api/src/qrp_api/modules/sym/gateway.py`** (READ — the join template) — `live_heatmap`
  `383-513`; the constituent assembly query `396-438` (gics_scd / security_names / fundamentals /
  symbology joins by composite_figi) is exactly what the composition sym query needs (minus the universe
  filter, plus signed weight from the portfolio side).
- **`services/api/src/qrp_api/modules/sym/quotes.py`** (READ — source of the batch) — `fetch_quotes_batch`
  `132-171` (`_BATCH_WORKERS=24`, `_BATCH_BUDGET_S=20.0`, `wait(timeout=budget)` + `shutdown(wait=False,
  cancel_futures=True)`, 503 only when all completed network-errored). Port verbatim into the twin.
- **`packages/portfolios/src/portfolios/gateway.py`** (READ — the A.1 seam) — `read_latest_weights`
  `19-40` returns `(as_of_date|None, {composite_figi: Decimal})`; weights are **signed NUMERIC** (no sign
  constraint). `portfolio_exists` for the 404.
- **`services/api/tests/test_analytics_live_pnl.py`** (READ — test pattern) — monkeypatches
  `read_latest_weights` / `read_portfolio_terms` / `portfolio_exists` / `fetch_raw_quote`; mirror it (and
  monkeypatch `fetch_quotes_batch`) for the composition tests.

### Key constraints

- **Position size = `abs(weight)`, not market cap.** Weights are signed; the heatmap tile size and BOTH
  pizza slice sizes use `abs(weight)`. Net = Σ weight (signed), gross = Σ|weight|. Coloring is by the
  holding's live return; shorts are sized by |weight| but must be visibly distinguishable (tag/border) so
  a long and a short of equal magnitude don't look identical.
- **No share-class collapse for a portfolio.** The universe heat map collapses ISIN-issuer share classes
  (it sizes by market cap). A portfolio holds *explicit positions* — render one tile/slice per stored
  holding; do NOT collapse.
- **Live, not persisted.** No writes to any quote/price table; composition is fetched on demand, returned,
  discarded — same hard boundary as QH.2/QH.9 (test-assert no INSERT/UPDATE).
- **Live return base = the quote's own `previousClose`** (QH.2 convention; FX-naive ratio, no sym price
  read). Uncovered holdings → `live_return` null → neutral grey, never a fake 0%.
- **Honest two-tier degradation:** per-holding miss → `unavailable` cell; whole-source down (all attempted
  network-error) → 503 envelope. Per-holding freshness from `regularMarketTime`; the panel badge is the
  worst priced cell; `as_of` = oldest priced quote.
- **Topology stays clean.** The endpoint lives in the **analytics** module (it already reaches portfolio
  weights via the A.1 standalone `read_latest_weights` and connects read-only to `sym` — `router.py:17-28`,
  QH.3 `qrp_readonly` role). Do NOT import the portfolios package beyond the existing standalone gateway
  functions. Sector/symbology/name come from the `sym` read connection by `composite_figi`.
- **Next.js 16** (`apps/web/AGENTS.md`): read `node_modules/next/dist/docs/` before writing components;
  these are client components (`"use client"`), like the existing viz components.
- **No new dependency.** d3-hierarchy is already a dep (treemap); the pizza is hand-rolled SVG arcs;
  the fan-out is stdlib `concurrent.futures`.
- **One fetch feeds three views.** The `composition` response carries everything the heatmap and both
  pizzas need — avoid three separate fetches (lift the fetch to the page or a shared hook; document the
  choice). Newest-wins / AbortController like the analytics-panel live fetch (`analytics-panel.tsx:52-72`)
  if you add a refresh.

### Testing standards

- **API:** analytics gateways are DB-backed; mirror `services/api/tests/test_analytics_live_pnl.py` —
  monkeypatch `read_latest_weights` / `portfolio_exists` and the quote fetch (`fetch_quotes_batch`), use a
  recording/fake conn for the sym metadata query. Assert: holding shape + signed weight preserved; sector
  rollup Σ|weight| equals gross; per-holding freshness vocabulary; partial coverage; all-unreachable → 503;
  per-holding miss → unavailable + null return; no-vector → empty; over-cap → 422; the live path issues no
  INSERT/UPDATE (scan `conn.seen`). Port the 3 `fetch_quotes_batch` tests into the analytics quotes test.
- **Console:** vitest + @testing-library, mocked fetch (`apps/web/__tests__/heatmap-view.test.tsx` /
  `portfolio-detail.test.tsx` patterns). Heatmap: tiles present + sized by weight, LIVE badge, neutral
  uncovered tile, 503 → error banner not blank. Pizza: sector slices match the rollup, position slices +
  an "Other" tail when over top-N, share% rendered. Use DOM queries; no new dependency.

### Project Structure Notes

- Surfacing + viz only: `analytics/quotes.py` (+`fetch_quotes_batch`), `analytics/gateway.py`
  (+`composition`), `analytics/router.py` (+route/models), two new web components, the page wire-up,
  regenerated `api-types.ts` (pre-deploy), tests. **No migration, no schema change, nothing persisted.**
- This is a standalone console-enhancement artifact — like `portfolios-exposure-and-layout.md` it is NOT
  added to `sprint-status.yaml`'s `development_status` (per that file's DERIVATION NOTE: additional
  delivered stories outside the epic decompositions are tracked inline in their artifacts, not enumerated).
- Deferred / ledger: SSE/auto-refresh of the portfolio heatmap (QH.9 added an auto-refresh interval to the
  universe heatmap — could mirror it here later), drill-down from a pizza slice to the holdings, factor/
  geography pizzas, an intraday sparkline per holding, per-as-of composition history (composition currently
  reflects the latest vector only), `gen:types` regen.

### References

- [Source: apps/web/app/portfolios/[id]/page.tsx:100-277] — page order; insert new blocks after line 126.
- [Source: apps/web/components/analytics-panel.tsx:11-15,175-204] — Live Risk & Analytics (keep) + the
  FRESH_STYLE live badge idiom to mirror.
- [Source: apps/web/components/heatmap-view.tsx:57-89,245-287,431-454] — rgbFor/textInk/useIsDark, live
  badge/coverage/refresh, ±3% legend — adapt, swap mcap→abs(weight), drop universe/window selectors.
- [Source: apps/web/components/price-volume-chart.tsx:32] — hand-rolled-SVG convention (no chart lib) for
  the pizza.
- [Source: packages/analytics/src/analytics/gateway.py:208-322] — `live_pnl()`: the read_latest_weights
  seam, the sym metadata query (extend), the quote loop (replace serial→batch), the rollup — the template.
- [Source: packages/analytics/src/analytics/router.py:17-28,121-130] — `_gateway()` conns + the live route
  error mapping to mirror for `/composition`.
- [Source: packages/analytics/src/analytics/quotes.py] — the twin missing `fetch_quotes_batch` (port it).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py:396-438] — the gics/name/fundamentals/symbology
  join template (per composite_figi).
- [Source: services/api/src/qrp_api/modules/sym/quotes.py:132-171] — `fetch_quotes_batch` to port into the
  twin (bounded workers + wall-clock budget + two-tier 503).
- [Source: packages/portfolios/src/portfolios/gateway.py:19-40] — `read_latest_weights` (A.1 seam); signed
  weights.
- [Source: services/api/tests/test_analytics_live_pnl.py] — the API test monkeypatch pattern to mirror.
- [Source: _bmad-output/implementation-artifacts/portfolios-exposure-and-layout.md] — the sibling
  standalone portfolio-page story (layout + exposure), and why these aren't in sprint-status.
- [Source: _bmad-output/implementation-artifacts/qh-9-live-heatmap.md] — the live-recolor + fan-out
  precedent this reuses; SSE/auto-refresh deferral.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]` (Amelia / bmad-dev-story)

### Debug Log References

- `uv run pytest` (services/api) → **137 passed** (was 136+1; +14: 4 batch fan-out + 10 composition
  gateway/route), incl. `test_topology_discipline.py` and `test_readonly_role.py` green after the
  AR-R3 surface extension.
- `npm test` (apps/web, vitest) → **66 passed** (+8: 4 portfolio-heatmap + 4 portfolio-pizza); the
  existing `portfolio-detail.test.tsx` updated to stub the new `/composition` fetch.
- `eslint .` 0/0, `tsc --noEmit` clean, `next build` ✓ 20/20 routes.

### Completion Notes List (2026-06-19)

- **Batched fan-out ported into the twin (Task 1).** `analytics/quotes.py` gained `fetch_quotes_batch`
  + `_BATCH_WORKERS`/`_BATCH_BUDGET_S`, identical to the `sym/quotes.py` copy (the documented twin
  stays in lock-step): bounded `ThreadPoolExecutor` + a `wait(timeout=budget)` wall-clock budget +
  `shutdown(wait=False, cancel_futures=True)`, raising `QuoteSourceUnreachable` only when EVERY
  completed symbol network-errors. The serial `live_pnl` loop is untouched.
- **`composition()` reuses the `live_pnl` assembly (Task 2).** Reads the shown vector via the A.1
  `read_latest_weights` seam, then ONE sym query for per-figi (ticker, mic, sector, industry, name,
  currency) — `live_pnl`'s sym query extended with `gics_scd` + `security_names` + `fundamentals`. Fans
  out via the batch, computes per-holding live return + freshness, rolls up `as_of`/worst-freshness/
  coverage and a per-sector Σ|weight| aggregate (with a |weight|-weighted sector return). Position size
  is `abs(weight)` (signed weights preserved on each holding); NO share-class collapse (explicit
  positions); `COMPOSITION_MAX = 400` over-cap → ValueError(422); writes nothing.
- **Route + models (Task 3).** `GET /api/analytics/portfolios/{pid}/composition` →
  `PortfolioComposition`/`CompositionHolding`/`SectorSlice`; 404/422/503 mapping mirrors the live route.
- **AR-R3 contract extension (deliberate).** The sector pizza needs GICS, so `gics_scd` moved from
  `SYM_INTERNAL_RELATIONS` into `SYM_READ_SURFACE` in `qrp_api/sym_contract.py` (the single source of
  truth). This widens BOTH the topology gate AND the `qrp_readonly` grant. **Deploy step:** re-run
  `tools/provision_readonly.py` so the role is physically granted SELECT on `gics_scd` — otherwise the
  live composition query 500s with InsufficientPrivilege when analytics connects via `qrp_readonly`
  (the live `test_readonly_role.py` check is gated/skips when the role isn't provisioned, so CI won't
  catch a missed grant). Ledgered.
- **Components are presentational; the page owns ONE fetch.** `<PortfolioHeatmap data>` and
  `<PortfolioPizza data>` take the composition response (no double-fetch); the page fetches once with an
  AbortController (newest-wins) + a refresh nonce, and renders the shared live/delayed/unavailable badge
  + coverage + as_of + ↻ refresh + "not stored". This deviates from the AC's `pid=…` prop wording
  (documented latitude in Task 5) to honor the "one fetch feeds three views" constraint and keep each
  chart testable with mock props.
- **Heatmap:** treemap (d3-hierarchy) grouped by sector, tiles sized by `abs(weight)`, colored by live
  return on the ±3% diverging scale (uncovered → neutral grey). Shorts get a dashed amber border + a ▼
  marker + "short" in the tooltip so a long/short of equal size are distinct.
- **Pizza:** two hand-rolled-SVG donuts (no chart lib) — by sector (Σ|weight| slices) and by position
  (|weight|, top-12 + an "Other" tail), legends with share%, centers showing gross / net.
- **`gen:types` NOT run** — it needs the running API (`openapi-typescript` hits 127.0.0.1:8001), and the
  components use LOCAL `Composition` types (the heatmap-view convention), so nothing consumes the
  generated `PortfolioComposition`. Pre-deploy step, ledgered (alongside the QH.9 `gen:types` ledger).
- **No live-app verification** — a live composition needs a running API + DB + the `qrp_readonly` grant;
  per the minimize-dev-churn rule the dev server wasn't restarted. Covered by the unit suites + a green
  production build. A post-deploy smoke (load a portfolio with the role provisioned) is the open check.

### File List

- `packages/analytics/src/analytics/quotes.py` (UPDATE) — `fetch_quotes_batch` + batch constants + `concurrent.futures` import.
- `packages/analytics/src/analytics/gateway.py` (UPDATE) — `composition()` + `COMPOSITION_MAX`.
- `packages/analytics/src/analytics/router.py` (UPDATE) — `/composition` route + `PortfolioComposition`/`CompositionHolding`/`SectorSlice` models.
- `services/api/src/qrp_api/sym_contract.py` (UPDATE) — moved `gics_scd` into `SYM_READ_SURFACE` (AR-R3 extension).
- `apps/web/components/portfolio-heatmap.tsx` (NEW) — treemap sized by |weight|, colored by live return; exports the `Composition` types.
- `apps/web/components/portfolio-pizza.tsx` (NEW) — sector + position donut charts (hand-rolled SVG).
- `apps/web/app/portfolios/[id]/live/page.tsx` (NEW) — the dedicated Live cockpit page (Live Risk & Analytics + heat map + pizza); owns the single composition fetch + shared live badge. **(Post-review design change — see below.)**
- `apps/web/app/portfolios/[id]/page.tsx` (UPDATE) — reverted to its pre-story state + a "● Live view →" link to the new page (the composition cluster moved OFF the detail page).
- `services/api/tests/test_portfolio_composition.py` (NEW) — 10 composition gateway/route tests.
- `services/api/tests/test_analytics_quotes_batch.py` (NEW) — 4 `fetch_quotes_batch` twin tests.
- `apps/web/__tests__/portfolio-heatmap.test.tsx` (NEW) — 4 heatmap tests.
- `apps/web/__tests__/portfolio-pizza.test.tsx` (NEW) — 4 pizza tests (updated for the single-percentage legend).
- `apps/web/__tests__/portfolio-live.test.tsx` (NEW) — 2 Live-page tests (one-fetch happy path + 503→error-not-blank).
- `apps/web/__tests__/portfolio-detail.test.tsx` (UPDATE) — reverted the `/composition` stub (detail page no longer fetches it).

### Change Log

- 2026-06-19: Story created (ready-for-dev).
- 2026-06-19: Implemented. New `GET /api/analytics/portfolios/{pid}/composition` enriches the shown
  weight vector with GICS sector + live returns (bounded fan-out ported into the analytics quotes twin,
  not persisted); two new presentational console components — a treemap sized by position size + colored
  by live return (shorts flagged) and a sector/position donut pair (hand-rolled SVG) — slot under the
  Live Risk & Analytics panel on the portfolio page (one fetch, newest-wins, shared live badge).
  Deliberate AR-R3 extension: `gics_scd` added to the sym read surface (re-run the readonly provisioner
  at deploy). 14 api + 8 console tests; pytest 137, vitest 66, eslint 0/0, tsc + build green. Status → review.
- 2026-06-19: Code review (3 layers; no High-severity bugs). 4 patches applied + 1 decision resolved:
  (1) AC5 — single share% in the pizza legend (the two were identical; also kills the drift risk);
  (2) all-zero/non-finite weight guard (gateway drops non-finite; FE treats `total_weight<=0` as empty);
  (3) heatmap tooltip left-clamp `Math.max(0,…)`; (4) added the missing 503/error console test. 4 low/
  cosmetic findings deferred (→ deferred-work.md). **Design change requested by the operator mid-review:
  the heat map + pizza moved OFF the detail page to a NEW dedicated `/portfolios/[id]/live` cockpit page**
  (Live Risk & Analytics + heat map + pizza), reached via a "● Live view →" link on the detail page; the
  detail page was reverted to its pre-story layout. (Supersedes AC6's "slot under AnalyticsPanel on the
  detail page".) pytest 137, vitest 68, eslint 0/0, tsc + build green (new route compiled). Status → done.
