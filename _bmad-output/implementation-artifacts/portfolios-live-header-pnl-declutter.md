# Story: Live page — lift Daily/MTD/YTD P&L into the header next to the title, drop the risk/exposure stats, tighten card spacing

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst watching a book live,
I want the **P&L figures up in the header beside the portfolio title** (not in a separate panel below it), the **risk/exposure stats removed**, and **less air between the cards**,
so that the **stats + donut + winners/losers + heat map all fit in one full-screen view without scrolling** — the most-watched number (today's P&L) sits with the title at a glance and the live cockpit reads as a single dashboard.

### Driving goal (Andre's clarification)

The point of this story is a **fit-to-viewport cockpit**: on a full-screen laptop, the **header P&L stats, the donut card, the winners/losers (movers) card, and the heat map** should all be visible **at once, with no vertical scroll**. Moving P&L into the header reclaims a whole panel's worth of vertical space, and tightening the inter-card gaps closes the rest — together they're what makes the above-the-fold cockpit fit. The pivot **grid** is the long element and may remain below the fold (it has its own scroll/extent).

## Background (what exists today)

The live page is `apps/web/app/portfolios/[id]/live/page.tsx`. Its current top-to-bottom layout (page root `<div className="w-full space-y-4">`):

1. **Header row** — `flex flex-wrap items-start justify-between gap-2`:
   - left: `<h1>` `{name} · Live` + a `<p>` sub-line (client · base_currency · N holdings + a freshness badge + "N/M priced · as of … · not stored");
   - right (`flex shrink-0 items-center gap-2`): a `← Portfolio` link and a `↻ refresh` button.
2. **`<PortfolioRiskPnl>`** (`apps/web/components/portfolio-risk-pnl.tsx`) — a section titled **"Risk & P&L analytics"** rendered as a bordered card. It holds **two groups separated by a vertical divider**:
   - **P&L** (keep): `Daily P&L`, `MTD P&L`, `YTD P&L` — each a % return (`pct`/`tone`) with an optional signed-currency sub-line (`money`, shown only when the portfolio has a `notional`).
   - **Risk / exposure** (remove): `Long`, `Short`, `Net`, `Gross`, `L/S` — derived from `portfolio.long_exposure/short_exposure/net_exposure/gross_exposure`.
3. Error banner (composition fetch failure).
4. Donut + Movers — a `grid gap-4 lg:grid-cols-2` of two bordered cards.
5. `<PortfolioHeatmap>`.
6. `<PortfolioPivot>` (the grid; it already has its own `Daily P&L` column header).

The three P&L numbers are computed on the page via `weightedPnl(comp, …)` from the **same** live composition (`/api/analytics/portfolios/{id}/composition`) that feeds the heat map, donut and grid — `dailyReturn = Σ weight·live_return`, MTD/YTD from each holding's `window_returns`. These match the grid's grand totals by construction (see the comments at the top of the page and in `portfolio-risk-pnl.tsx`). They render as `—` until `comp` arrives.

**`PortfolioRiskPnl` is used only on this live page** (verified). The non-live portfolio page (`apps/web/app/portfolios/[id]/page.tsx`) shows a *different* component — `analytics-panel.tsx`, titled **"Risk & return analytics"** — which is **out of scope and must not be touched**.

## What Andre asked for

> for the portfolio live page. remove Risk & P&L analytics; move the card with daily PNL to be on the top, along with portfolio title; reduce padding btw cards.

Interpretation (the directives together — see Open Question #1):
- **Remove the risk/exposure half** of the "Risk & P&L analytics" panel (Long/Short/Net/Gross/L/S) and the "Risk & P&L analytics" section heading + its standalone card.
- **Keep the P&L** (Daily/MTD/YTD) and **lift it into the header row, beside the portfolio title** as a compact inline strip — no longer a separate panel below the header.
- **Tighten the vertical spacing** between the page's cards.

## Acceptance Criteria

1. **No more "Risk & P&L analytics" panel.** The bordered section titled "Risk & P&L analytics" no longer renders on the live page, and the **exposure/risk stats (Long, Short, Net, Gross, L/S) are gone** from this page entirely.
2. **Daily/MTD/YTD P&L move into the header.** The three live P&L stats render in the **top header row, alongside the portfolio title** (same visual band as `{name} · Live`), as a compact inline strip — not as a card below the header. Each keeps its current semantics: signed % with up/down color (`tone`) and, when the portfolio has a `notional`, the signed-currency sub-line (`money`). Labels stay `Daily P&L` / `MTD P&L` / `YTD P&L`.
3. **Same data, same correctness.** The P&L values are still `weightedPnl(comp, …)` off the one composition fetch — Daily = `live_return`, MTD/YTD from `window_returns` — so they continue to equal the grid's grand totals. Before `comp` loads they show `—`; the existing freshness badge / "N/M priced · as of …" sub-line is preserved (it may stay under the title or sit with the strip — keep it on the page).
4. **The `← Portfolio` link and `↻ refresh` button stay** in the header and keep working (refresh still bumps `nonce`, disabled while loading, spinner on the glyph).
5. **Tighter card spacing.** The vertical gap between the page's stacked cards is reduced from the current `space-y-4`, and the donut/movers row gap from `gap-4`, to a tighter default — following the two-tier responsive-density convention (tight by default, roomier at `2xl:`). Cards must not touch or overlap; the page must not introduce horizontal overflow.
6. **Fit-to-viewport (the goal).** On a full-screen laptop (verify at ~1366×768 and a typical ~1440×900), the **header P&L stats + donut card + winners/losers (movers) card + heat map are all visible at once with no vertical scroll**. The pivot grid below may extend past the fold. Removing the P&L panel + tightening the gaps is what buys this; if it still doesn't fit, tighten the donut/movers/heat-map internal sizing as needed (note any such change). Use real-Chrome CDP to confirm the heat map's bottom edge is within the viewport height at full screen.
7. **No layout regression.** Header still wraps gracefully on a narrow width (`flex-wrap`), the error banner still shows on a 503 (not a blank page) with page chrome intact, and the heat map / donut / movers / pivot grid are unchanged in behavior. `tsc`, `eslint`, and the web vitest suites stay green.
8. **Tests updated.** `portfolio-live.test.tsx` no longer asserts the removed exposure stats (`Long`, `L/S`, `4.00×`) and instead asserts the P&L labels render in the header region; the 503 error-banner test still passes. `portfolio-risk-pnl.test.tsx` is updated to match the repurposed P&L-only component (drop the exposure-stat assertions) — or removed if the component is inlined/deleted (see Task 2).

## Tasks / Subtasks

- [x] Task 1: Drop the risk/exposure stats + the "Risk & P&L analytics" section (AC: #1)
  - [x] Removed the Long/Short/Net/Gross/L/S `Stat`s, the vertical divider, and the `<h2>Risk & P&L analytics</h2>` heading.
  - [x] Removed the now-unused exposure plumbing (`long`/`short`/`ls`, `expPct`/`signedExpPct`); kept `pct`/`tone`/`money`/`Stat`.
- [x] Task 2: Repurpose the panel into a compact header P&L strip (AC: #2, #3)
  - [x] Renamed the component to `PortfolioPnlStrip` (new file `apps/web/components/portfolio-pnl-strip.tsx`); chrome-less (no card border/`bg-surface`, no heading) — three `Stat`s in a tight `flex flex-wrap` row. Deleted the old `portfolio-risk-pnl.tsx`. Same props (`dailyReturn`/`mtdReturn`/`ytdReturn` + `portfolio`).
  - [x] Rendered in the header beside the title: grouped title block + `PortfolioPnlStrip` in a left `flex flex-wrap items-center` cluster, with the `← Portfolio`/`↻ refresh` cluster kept on the right (outer row `justify-between`, wraps on narrow widths).
- [x] Task 3: Tighten inter-card spacing for the fit-to-viewport goal (AC: #5, #6)
  - [x] Page root `space-y-4` → `space-y-3 2xl:space-y-4`; donut/movers grid `gap-4` → `gap-3 2xl:gap-4`; donut & movers cards `p-4` → `p-3 2xl:p-4`.
  - [x] Drive toward fit: the row1 height is pinned by the 10+10 Top-Movers list, so the lever was the heat map — its SVG height was locked to its width via `viewBox 0 0 1000 460` (height ≈ 0.46×width), which only grows on wider screens. Flattened the heat-map `viewBox` H **460 → 300** in `portfolio-heatmap.tsx` to buy back vertical space across all widths. Verified empirically (CDP) — see Completion Notes.
- [x] Task 4: Update tests (AC: #8)
  - [x] `portfolio-live.test.tsx`: dropped the `Long` / `L/S` / `4.00×` assertions; assert all three P&L labels via `getAllByText` (each appears in the header strip AND as a grid column) + `queryByText("L/S"/"Long")` are gone; 503 banner test kept.
  - [x] Replaced `portfolio-risk-pnl.test.tsx` with `portfolio-pnl-strip.test.tsx` — P&L formatting + notional-amount cases against the new component, plus an assertion the exposure stats are gone.
- [x] Task 5: Verify (AC: #5, #6, #7)
  - [x] `tsc` clean; `eslint` 0 errors (1 pre-existing warning in `fx-matrix-page.test.tsx`, not mine). Targeted vitest (portfolio-live, portfolio-pnl-strip, portfolio-pivot, portfolio-detail, analytics-panel, portfolio-heatmap) all green. Full-suite flakes are load-induced in unrelated files (fx-matrix/indexes) that pass in isolation; clean-tree full run = 135/135. Real-Chrome CDP at 1366×768 / 1536×864 / 1920×1080 — see Completion Notes for the fit measurements.

## Dev Notes

### Where this fits

Frontend-only, live-page-only. No API/data/schema change — the P&L values already exist on the page (`weightedPnl` off the composition fetch). This is a relayout + a delete of the exposure block.

### Reuse / current state being modified

- `apps/web/app/portfolios/[id]/live/page.tsx`:
  - header row at lines ~100–141 (`flex flex-wrap items-start justify-between gap-2`; title `<h1>` + sub-`<p>` with the freshness badge; right cluster with `← Portfolio` + refresh);
  - `<PortfolioRiskPnl …>` at lines ~143–148 (delete from the body; its P&L props move to the header strip);
  - page root `space-y-4` (line ~99) and the donut/movers `grid gap-4 lg:grid-cols-2` (line ~158) — the two spacings to tighten.
- `apps/web/components/portfolio-risk-pnl.tsx`: `Stat` helper + `pct`/`tone`/`money` (keep); `expPct`/`signedExpPct` + the Long/Short/Net/Gross/L/S block + the `<h2>` heading + the card chrome (`rounded-xl border bg-surface px-4 py-3`) (remove). The P&L `Stat`s already use the right format; you're just removing the rest and stripping the chrome.
- **Do NOT touch** `apps/web/components/analytics-panel.tsx` or `apps/web/app/portfolios/[id]/page.tsx` — that's the separate "Risk & **return** analytics" on the non-live page, with its own tests (`portfolio-detail.test.tsx`, `analytics-panel.test.tsx`).

### Critical conventions (regressions if violated)

- **Two-tier responsive density** ([[feedback-responsive-density-two-tier]]): dense pages are tight by default to fit a laptop full-screen with no scroll, roomier at `2xl:`. Apply that to the new spacing; verify no overflow via CDP.
- **This is NOT the Next.js you know** — see `apps/web/AGENTS.md`; read the relevant `node_modules/next/dist/docs/` guide before any Next-API change (none expected here — this is component/layout only).
- **Verify via headless Chrome, not by asking Andre** ([[feedback-minimize-dev-churn]]); reuse one Chrome instance and kill it by CommandLine match when done ([[feedback-headless-chrome-cleanup]]). Dev server: console :3000, API :8001; the frontend hot-reloads — **never** `npm --prefix` in this workspace (it broke lightningcss) and avoid needless dev-server restarts (stales Andre's open tab).
- **P&L honesty** — keep the EOD/live freshness badge and the "not stored" wording; the P&L is derive-at-view, not persisted. Don't drop the "N/M priced · as of …" sub-line.
- Keep the P&L math exactly: Daily = `Σ weight·live_return`, MTD/YTD from `window_returns`; these must keep matching the grid grand totals. You're moving the display, not recomputing.

### Files to touch

- MOD `apps/web/app/portfolios/[id]/live/page.tsx` (remove `<PortfolioRiskPnl>` from body; render the P&L strip in the header; tighten `space-y-*` and the donut/movers `gap-*`).
- MOD (or rename/inline + delete) `apps/web/components/portfolio-risk-pnl.tsx` (strip risk/exposure + heading + card chrome → compact P&L strip).
- MOD `apps/web/__tests__/portfolio-live.test.tsx` (drop exposure assertions; assert P&L in header).
- MOD or DEL `apps/web/__tests__/portfolio-risk-pnl.test.tsx` (P&L-only, or removed if inlined).

### References

- [Source: apps/web/app/portfolios/[id]/live/page.tsx:99-172] — page root `space-y-4`, header row, `<PortfolioRiskPnl>` placement, donut/movers `gap-4` grid.
- [Source: apps/web/components/portfolio-risk-pnl.tsx] — the panel being split: P&L `Stat`s (keep) vs exposure `Stat`s + heading + card chrome (remove); `pct`/`tone`/`money`/`Stat` helpers.
- [Source: apps/web/__tests__/portfolio-live.test.tsx:62-85] — current assertions (Long / L/S / 4.00× to drop; Daily P&L + 503 banner to keep).
- [Source: apps/web/__tests__/portfolio-risk-pnl.test.tsx] — dedicated component test to update/remove.
- [Source: apps/web/app/portfolios/[id]/page.tsx:133 + apps/web/components/analytics-panel.tsx:128] — the *other* "Risk & return analytics" — DO NOT touch.
- [Source: apps/web/AGENTS.md] — "This is NOT the Next.js you know"; read the bundled docs before Next-API changes.
- [Source: memory feedback-responsive-density-two-tier, feedback-minimize-dev-churn, feedback-headless-chrome-cleanup] — density + verification conventions.

## Open Questions (for Andre — do not block implementation)

1. **"Remove Risk & P&L analytics" + "move the card with daily PNL up" — I read these together** as: keep the Daily/MTD/YTD **P&L** (lift it to the header), and drop only the **risk/exposure** stats (Long/Short/Net/Gross/L/S) and the section heading. If you actually meant remove the *whole* panel including P&L, say so and I'll just delete it (the grid still has a Daily P&L column).
2. **Header placement of the P&L strip.** Default: title (left) → P&L strip → nav buttons (right), wrapping on narrow widths. If you'd rather have it tuck directly under the title, or sit far-right next to the buttons, that's a quick swap.
3. **Spacing amount.** I'll go `space-y-3` / `gap-3` (with a `2xl:` step back to 4). Say if you want it tighter (`space-y-2`).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- The heat map height is **width-driven** (`viewBox 0 0 1000 460` + `class="block w-full"` → rendered height ≈ 0.46 × card width). That's why it never fit: on wider screens the heat map gets *taller*, not shorter. Flattening the `viewBox` H is the only knob that buys vertical space at every width without distorting the SVG (treemap is recomputed to the new aspect, no `preserveAspectRatio` stretch).
- Full-suite vitest is flaky **under heavy machine load** (I ran it repeatedly): different unrelated files fail per run — `fx-matrix-page` once, `fx-matrix-page` + `indexes-page` the next — always with `await screen.findByText(<heading>)` racing ahead of the async-rendered table (`querySelectorAll("thead")[0]` undefined). Clean-tree full run = 135/135 green; all three suspect files pass 20/20 in isolation. Not caused by this story (flagged below for the owning stories).

### Completion Notes List

- **Done, all three asks:** (1) removed the "Risk & P&L analytics" panel incl. the Long/Short/Net/Gross/L/S exposure stats; (2) lifted Daily/MTD/YTD P&L into the header as a chrome-less `PortfolioPnlStrip` beside the title (same `weightedPnl` off the one composition fetch — values unchanged, still match the grid grand totals); (3) tightened inter-card spacing (`space-y`/`gap`/card `p-*`, two-tier `2xl:` density) + flattened the heat map.
- **Fit-to-viewport (CDP-measured, raw viewport heights, portfolio 5, sidebar expanded):** heat-map bottom edge — **1366×768 → 823px** (≈55px over), **1536×864 → 890px** (≈26px over), **1920×1080 → 1051px → FITS** (29px margin; pivot grid starts right at the fold). So the full cockpit (header P&L + donut + movers + heat map) fits with no scroll at a **1080-tall viewport and larger** (the real "cockpit monitor" case), and is close on smaller laptops. No horizontal overflow at any width; header wraps cleanly.
- **Residual / honest limitation:** because the heat-map height is fundamentally tied to its width, no amount of padding fully fits a small **1366×768** laptop (worse once real browser chrome eats ~85px). Guaranteeing fit on every laptop needs the heat map to size to the *remaining viewport height* (e.g. a `ResizeObserver`-driven treemap or a `max-h` cap), which is a redesign of the (separately-owned) heat-map component — left as a follow-up decision rather than over-squishing the tiles here. Flattening further (H<300) hurts tile readability for diminishing returns.
- **Verification:** `tsc` clean; `eslint` 0 errors; targeted vitest green (portfolio-live 2/2, portfolio-pnl-strip 4/4, portfolio-pivot 16/16, portfolio-detail 2/2, analytics-panel 8/8, portfolio-heatmap green). The non-live "Risk & **return** analytics" page was not touched.

### File List

- ADD `apps/web/components/portfolio-pnl-strip.tsx` (chrome-less Daily/MTD/YTD P&L strip; P&L-only)
- DEL `apps/web/components/portfolio-risk-pnl.tsx` (replaced by the above; exposure stats removed)
- MOD `apps/web/app/portfolios/[id]/live/page.tsx` (P&L strip in the header beside the title; removed the body panel; `space-y`/`gap`/card-padding tightened)
- MOD `apps/web/components/portfolio-heatmap.tsx` (heat-map `viewBox` H 460 → 300 — flatter, to reclaim vertical space)
- ADD `apps/web/__tests__/portfolio-pnl-strip.test.tsx` (replaces the risk-pnl test)
- DEL `apps/web/__tests__/portfolio-risk-pnl.test.tsx`
- MOD `apps/web/__tests__/portfolio-live.test.tsx` (drop exposure asserts; assert header P&L via getAllByText)

## Change Log

| Date | Change |
|---|---|
| 2026-06-21 | Created story: on the live portfolio page, lift Daily/MTD/YTD P&L into the header beside the title, remove the risk/exposure stats + "Risk & P&L analytics" heading/card, and tighten inter-card spacing (two-tier density). Frontend + tests only; `PortfolioRiskPnl` is live-page-only so no cross-page regression; the non-live "Risk & return analytics" is out of scope. Status → ready-for-dev. |
| 2026-06-21 | Implemented: new chrome-less `PortfolioPnlStrip` (replaces `PortfolioRiskPnl`) rendered in the header beside the title; removed the exposure/risk stats + panel; tightened `space-y`/`gap`/card padding (two-tier `2xl:`); flattened the heat-map `viewBox` H 460→300 to reclaim vertical space. CDP-verified: full cockpit fits no-scroll at a 1080-tall viewport (1051px heat-map bottom); ~26–55px over on smaller laptops (documented residual — width-driven heat-map height needs a viewport-cap redesign to fully fit small laptops). tsc clean, eslint 0 errors, targeted vitest green. Status → review. |
