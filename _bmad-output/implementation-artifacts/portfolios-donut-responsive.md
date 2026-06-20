# Story: Sector donut scales up on large screens (fills the card, fits more labels)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst on a large monitor,
I want the sector donut in the live portfolio view to grow with the screen instead of staying small,
so that it fills its card (no wasted whitespace) and the bigger ring has room to label more sectors directly on the chart.

## Background (what exists today)

The sector breakdown is `apps/web/components/portfolio-pizza.tsx` — an SVG donut heat map rendered in the **left card** of the `lg:grid-cols-2` row on `app/portfolios/[id]/live/page.tsx` (the right card is Top Movers). Today the donut is a **fixed size**:
- SVG `viewBox="0 0 300 300"` (constants `S=300`, `R=140` outer, `RI=80` inner) rendered with the fixed Tailwind classes **`h-60 w-60 shrink-0`** (= 240×240 px) inside `<div className="mt-2 flex flex-wrap items-center gap-6">`, beside a `min-w-[13rem] flex-1` legend.
- So on a wide screen the card is ~half the viewport (e.g. ~1100px on a 2560px monitor); the legend (`flex-1`) absorbs the extra width while the donut stays 240px → the donut looks small and the card has a lot of empty space (Andre's report).
- In-chart slice labels render only for slices ≥ `LABEL_MIN_FRAC = 0.06` (6%); smaller sectors rely on the legend (to avoid label collisions on the small ring).

Because the SVG is **viewBox-based**, increasing the rendered px size scales the whole drawing — ring, slices, and label text — proportionally, with **no geometry-constant changes**. That's the lever for "bigger donut." Showing *more* labels is a separate lever: lowering `LABEL_MIN_FRAC` (a fraction, independent of px size), which is only safe once the ring is physically bigger.

## Acceptance Criteria

1. **Donut scales up at large breakpoints.** The donut's rendered size grows responsively — small/mobile unchanged at `h-60 w-60` (240px), then larger at `lg` / `xl` / `2xl` (e.g. ~288 / ~352 / ~400px; pick values that visibly fill the card without overflowing it). Achieved by responsive Tailwind size classes on the `<svg>` (the `viewBox` and the geometry constants `S`/`R`/`RI`/`LABEL_R`/fontSizes stay **unchanged** — the SVG scales as a unit, labels included).
2. **Card whitespace is taken up.** On `lg+`, the donut + legend visibly use the card width — the donut is materially larger and the empty gap that exists today is gone (donut centered/grown; the legend keeps its `min-w` and stays readable beside or below it). The `flex-wrap` row must still wrap gracefully if the card is narrow.
3. **More sectors labelled in-chart on large screens.** On `lg+`, lower the in-chart label threshold (`LABEL_MIN_FRAC`) so more (smaller) sector slices get their label drawn on the ring — the bigger ring has the room. Small/mobile keeps the current `0.06` (no new collisions on the 240px ring). Implement the size-awareness with an **SSR-safe media-query hook** mirroring `useIsDark` (see Dev Notes) — do NOT read `window` during render.
4. **No regression on small/mobile.** At `< lg` the donut is byte-for-byte today's behaviour: 240px, 6% label threshold, legend, center "gross %", hover tooltip, dark/light heat colors, contribution math, legend totals. Resizing across the breakpoint updates live (the hook re-renders).
5. **Everything else preserved.** The heat-map color semantics (`rgbFor` on daily move), per-sector P&L contribution math, the legend attribution table + total, the hover winners/losers tooltip, and accessibility (`role="img"` + aria-label) are unchanged. `tsc --noEmit`, `eslint`, and the pizza/portfolio vitest suites stay green.
6. **Tests.** Extend `apps/web/__tests__/portfolio-pizza.test.tsx`: assert the responsive size classes are present on the SVG; assert that when the "large" media query matches (mock `matchMedia`), more slice labels render than at the small threshold for a fixture with several sub-6% sectors. Keep the existing 5 tests green.

## Tasks / Subtasks

- [x] Task 1: Responsive donut size (AC: #1, #2, #4)
  - [x] SVG class is now `h-60 w-60 shrink-0 lg:h-72 lg:w-72 xl:h-[22rem] xl:w-[22rem] 2xl:h-[25rem] 2xl:w-[25rem]` — 240px small, 288/352/400px at lg/xl/2xl. `viewBox`/`S`/`R`/`RI`/`LABEL_R`/fontSizes untouched (the SVG scales as a unit).
  - [x] The existing `flex flex-wrap items-center gap-6` row needed no change: verified at 1366 (legend wraps neatly below the larger donut) and 2560 (legend sits beside it) — both fill the card with no dead gap.
- [x] Task 2: Size-aware label threshold (AC: #3, #4)
  - [x] Added a local SSR-safe `useIsLargeScreen()` hook mirroring `useIsDark` (`useState(false)` + `useEffect` with `window.matchMedia("(min-width: 1024px)")`, `.matches`, `addEventListener("change")`, cleanup; guards `!window.matchMedia` so it no-ops on SSR/jsdom).
  - [x] `const labelMin = isLarge ? 0.035 : LABEL_MIN_FRAC;` and the in-chart label filter uses `labelMin`. Small/mobile keeps `0.06`.
- [x] Task 3: Tests (AC: #6)
  - [x] `portfolio-pizza.test.tsx`: added a `stubMatchMedia(matches)` helper (jsdom has no matchMedia) + `afterEach(unstubAllGlobals)`; a `COMP_SMALL_SECTOR` fixture with a 4% Energy sector; tests assert (a) the `lg:` responsive size class is on the `<svg>`, and (b) the in-svg "Energy" label is absent when small and present when large. Existing 5 tests still green (the hook's `!window.matchMedia` guard keeps them from crashing).
- [x] Task 4: Verify (AC: #1, #2, #5)
  - [x] `tsc --noEmit` clean; `eslint` clean; `vitest` 7/7 pizza + 26/26 across all portfolio suites; headless Chrome at 1366 and 2560 confirms the donut grows (≈352→400px), fills the card, and labels render (Info Tech / Consumer Disc / Comm Services in-chart). Small/mobile baseline unchanged.

## Dev Notes

### Where this fits

Frontend-only, one client component (`components/portfolio-pizza.tsx`) + its test. No API/data/contract change. The component is rendered on `app/portfolios/[id]/live/page.tsx` (left card of the `lg:grid-cols-2` donut+movers row).

### The key technique — scale the viewBox, don't rewrite the geometry

The SVG draws into a fixed `0 0 300 300` user space (`S=300`, `R=140`, `RI=80`, `LABEL_R=(R+RI)/2`, label `fontSize={11}`, center `fontSize={16}`). Changing only the **rendered** size (the Tailwind `h-*/w-*` on `<svg>`) scales the entire drawing — arcs, strokes, and label text — together, because they're all in viewBox units. So a bigger donut needs **only** bigger size classes; the labels get bigger and more legible for free. **Do not** scale by editing `S/R/RI/fontSize` (that changes proportions and label-to-ring ratio). The ONLY content change for "more labels" is lowering the fraction threshold `LABEL_MIN_FRAC` (it's a fraction of total weight, size-independent), gated on the large breakpoint so the small ring doesn't get crowded.

### Reuse — do NOT reinvent

- **`useIsDark`** (`components/portfolio-heatmap.tsx:75`) is the SSR-safe hook pattern to mirror for the breakpoint hook: `const [v,setV]=useState(false); useEffect(()=>{...; update(); subscribe; return cleanup},[])`. Default `false` on the server/first render (so SSR renders the small variant), then it syncs on mount — same hydration-safe shape. For a media query use `window.matchMedia("(min-width: 1024px)")`, read `.matches`, and listen to its `"change"` event.
- **`rgbFor` / `textInk` / `useIsDark`** are imported from `portfolio-heatmap.tsx` already — keep using them.
- Tailwind v4 responsive variants (`lg:`/`xl:`/`2xl:`) — standard breakpoints (1024 / 1280 / 1536). Match the hook's query to whichever breakpoint you start growing at (1024 = `lg`).

### Critical conventions (regressions if violated)

- **SSR/hydration safety:** never touch `window`/`matchMedia` during render — only inside `useEffect` (the `useIsDark` pattern). First render must match the server (small variant), then upgrade on mount. The project's `react-hooks` lint (`set-state-in-effect`) is enforced — set state inside the effect's subscribe/update, not synchronously in the body.
- **No new dependency** — pure Tailwind classes + a tiny hook; do NOT add a charting/responsive lib.
- **Small-screen behaviour unchanged** — the 240px donut + 6% threshold is the current, deliberate small-ring layout (labels collide if you lower the threshold there).
- **Heat-map semantics untouched** — color = daily move (`rgbFor`), size = Σ|weight|, label = daily P&L contribution; the legend totals to Daily P&L. Don't alter the math.
- **Verify via headless Chrome at multiple widths**, never by asking Andre. Dev servers: API :8001, console :3000 (`npm run dev`); uvicorn has no `--reload` (irrelevant here — frontend-only, hot-reloads). After editing, the running dev server hot-reloads; screenshot at 1280/1920/2560.

### Files to touch

- MOD `apps/web/components/portfolio-pizza.tsx` (responsive SVG size classes; size-aware label threshold via a small media-query hook; optional flex centering)
- MOD `apps/web/__tests__/portfolio-pizza.test.tsx` (matchMedia stub + responsive-size + more-labels-when-large tests)
- Possibly MOD `apps/web/components/portfolio-heatmap.tsx` IF you generalize a `useMediaQuery` hook there to share with the donut (optional; a local hook in pizza is fine too).

### References

- [Source: apps/web/components/portfolio-pizza.tsx] — the donut: fixed `h-60 w-60` SVG, `S/R/RI/LABEL_R`, `LABEL_MIN_FRAC=0.06`, the `flex flex-wrap` donut+legend row, hover tooltip.
- [Source: apps/web/components/portfolio-heatmap.tsx:75] — `useIsDark`, the SSR-safe matchMedia/observer hook pattern to mirror; `rgbFor`/`textInk`.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx:157-165] — the `lg:grid-cols-2` donut+movers card row this sits in.
- [Source: apps/web/__tests__/portfolio-pizza.test.tsx] — existing 5 tests + the `comp(...)` fixture shape.
- [Source: memory feedback_minimize_dev_churn] — verify via headless Chrome at multiple widths, not by asking Andre.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- RED first: the responsive-class + more-labels-when-large tests failed against the fixed donut. After
  implementing, the 5 ORIGINAL tests then failed because the new `useIsLargeScreen` effect called
  `window.matchMedia` which jsdom doesn't provide (only the 2 new tests stub it) → added a
  `!window.matchMedia` guard so it no-ops (stays small) when unavailable. All 7 green.

### Completion Notes List

- **Donut now scales with the viewport.** SVG rendered size grows `240 → 288 (lg) → 352 (xl) → 400 (2xl)`
  via responsive Tailwind classes; because the drawing is viewBox-based, the ring, slices, and labels all
  scale together — no geometry-constant changes. Fixes the "too small / wasted card space on large
  screens" report.
- **More sectors labelled in-chart when large.** A small SSR-safe `useIsLargeScreen()` hook (mirrors
  `useIsDark`) lowers the in-chart label cutoff from 6% → 3.5% at `lg+`, so the bigger ring shows more
  sector labels; small/mobile keeps 6% to avoid collisions on the 240px ring.
- **No regressions.** Small/mobile donut, heat colors (`rgbFor`), per-sector P&L contribution math,
  legend + total, center gross %, and the hover winners/losers tooltip are all unchanged. Frontend-only,
  no new dependency, no API/data change.
- **Verified:** tsc + eslint clean; 7/7 pizza + 26/26 portfolio tests; headless Chrome at 1366 (legend
  wraps below the larger donut) and 2560 (legend beside a ~400px donut) — both fill the card.

### File List

- MOD `apps/web/components/portfolio-pizza.tsx` (responsive SVG size classes; `useIsLargeScreen` hook; size-aware `labelMin`)
- MOD `apps/web/__tests__/portfolio-pizza.test.tsx` (matchMedia stub + responsive-size + more-labels-when-large tests)

## Open Questions (for Andre — do not block implementation)

1. **How big at the top end?** Default grows to ~400px (`25rem`) at `2xl`. If you want it to fill even more of an ultra-wide card (or LESS, to keep the legend prominent), say so — it's a one-line cap.
2. **Legend placement on large screens.** Default keeps donut + legend side-by-side (they just get more room). Alternative: on `xl+`, put the legend *below* a centered, larger donut so the donut dominates the card. Flag if you prefer that.
3. **Label threshold when large.** Default lowers the in-chart label cutoff from 6% → ~3.5% on `lg+` (more sectors labelled). If you want ALL sectors labelled on big screens (with leader lines for tiny slices to avoid overlap) that's a bigger change — separate story.

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: make the live-view sector donut scale up at lg/xl/2xl (viewBox-based, so labels scale too) to fill its card on large screens, and lower the in-chart label threshold when large so more sectors are labelled on the ring. Small/mobile unchanged. Frontend-only; SSR-safe breakpoint hook mirroring `useIsDark`. Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): responsive SVG size (240→288→352→400 at lg/xl/2xl); `useIsLargeScreen` hook (matchMedia, guarded for jsdom/SSR); `labelMin` 6%→3.5% when large. 2 new tests + matchMedia stub; 7/7 pizza + 26/26 portfolio green; tsc + eslint clean; headless-verified at 1366 + 2560. Status → review. |
| 2026-06-20 | SUPERSEDED + folded into `portfolios-donut-container-fit`: the viewport (`lg:`/`xl:`) sizing was replaced with Tailwind container queries (the sidebar-expand fix), and the matchMedia hook removed. This story's INTENT (donut grows / fills the card on large screens; more in-chart labels when big) holds in the final container-query code (confirmed by the combined code-review). Committed together with container-fit. Status → done. |
