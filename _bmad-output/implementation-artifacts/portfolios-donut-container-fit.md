# Story: Donut sizes to its card (container query), so expanding the sidebar doesn't grow the card

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst on a laptop,
I want the sector donut to size itself to the **card it lives in** (not the browser window),
so that when I expand the left sidebar — which narrows the content without changing the window width — the donut shrinks to keep fitting beside its legend, and the card's height stays the same instead of growing.

## Background (what exists today — and why it regresses)

The previous story (`portfolios-donut-responsive`, in review) made the donut in `apps/web/components/portfolio-pizza.tsx` grow on large screens using **viewport media queries**: the SVG is `h-60 w-60 lg:h-72 lg:w-72 xl:h-[22rem] xl:w-[22rem] 2xl:h-[25rem] 2xl:w-[25rem]`, sitting in `<div className="mt-2 flex flex-wrap items-center gap-6">` beside a `min-w-[13rem] flex-1` legend. The label cutoff also drops on large viewports via `useIsLargeScreen()` (a `matchMedia` hook).

The sidebar (`apps/web/components/sidebar.tsx`) is an `<aside class="shrink-0 … transition-[width]">` that toggles **`w-16` (collapsed, 64px) ↔ `w-60` (expanded, 240px)** (persisted in `localStorage` `qrp-sidebar-collapsed`, read via `useSyncExternalStore`). The main content is its flex sibling, so **expanding the rail narrows the content area — and the donut card — by ~176px while the viewport width is unchanged.**

Because the donut size is keyed to the **viewport** (Tailwind `lg:`/`xl:`), it does **not** react to the sidebar: on a laptop (~1366px) the donut stays e.g. 352px even after the card loses 176px → the donut + `min-w-13rem` legend no longer fit on one line → the `flex-wrap` row wraps the legend **below** the donut → the **card grows taller**. Andre's report: expanding the menu changes the card height; it should instead shrink the donut to keep the same height.

The fix is to size the donut relative to its **container** (the card), not the window. Tailwind v4 ships **container queries** natively (`@container` + `@sm/@md/@lg/@xl/@2xl/@3xl/…` variants keyed to the nearest `@container` ancestor's width) — no plugin needed.

## Acceptance Criteria

1. **Donut sizes to its container, not the viewport.** The donut's responsive size is driven by **container-query variants** (`@container` on the donut card / its flex row + `@md:`/`@xl:`/`@3xl:`-style size classes on the `<svg>`), replacing the viewport `lg:`/`xl:`/`2xl:` size classes. As the card's own width changes, the donut grows/shrinks accordingly.
2. **Expanding the sidebar shrinks the donut, not the card.** At a laptop width (~1280–1440px), toggling the sidebar from collapsed (`w-16`) to expanded (`w-60`) makes the donut **smaller** so the donut + legend stay on one line — and the **donut card's height is unchanged** (the legend does NOT wrap below). Collapsing the sidebar lets it grow back.
3. **Still fills the card on large screens.** On a wide window with the sidebar collapsed (large card), the donut is still large and fills the card (the win from the previous story is preserved) — now because the *container* is wide, not the window.
4. **Label-density also follows the container.** The "more in-chart labels when big" behaviour now keys off container size too (so a big donut in a wide card shows more labels; a shrunk donut in a narrow card uses the tighter cutoff to avoid collisions). Prefer driving this from the same container signal rather than the viewport `matchMedia` hook — see Dev Notes for options.
5. **No regression.** Small/mobile (narrow container) keeps a sensible small donut + 6%-ish cutoff; heat colors, per-sector P&L contribution math, legend + total, center gross %, hover tooltip, dark/light, and accessibility are unchanged. `tsc`, `eslint`, and the pizza/portfolio vitest suites stay green.
6. **Tests.** Assert the container-query setup is present: the card/row carries `@container` and the `<svg>` carries `@`-prefixed (container) size variants rather than `lg:`/`xl:` viewport ones. Keep the existing pizza tests green (adjust the "responsive size class" assertion from `lg:` to the container variant). If label-density is moved off `matchMedia`, update/replace those tests accordingly.

## Tasks / Subtasks

- [x] Task 1: Make the donut card a container & size the donut by container width (AC: #1, #2, #3)
  - [x] Added `@container` to the pizza root `<div>` (its width = the card's inner width, which is what changes when the rail toggles).
  - [x] SVG size classes are now CONTAINER variants: `h-52 w-52 shrink-0 @sm:h-60 @sm:w-60 @lg:h-64 @lg:w-64 @xl:h-72 @xl:w-72 @2xl:h-80 @2xl:w-80 @3xl:h-[24rem] @3xl:w-[24rem]` (no `lg:`/`xl:` viewport variants). viewBox/geometry unchanged.
  - [x] Verified the `flex-wrap` row no longer wraps when the rail expands at 1366px — the donut steps down to fit beside the `min-w-[13rem]` legend.
- [x] Task 2: Container-driven label density (AC: #4)
  - [x] Pure-CSS (no JS): render labels for all slices ≥ `LABEL_MIN_MINOR` (3.5%); minor slices (3.5–6%) get `hidden @2xl:block` so they appear only once the container is wide; majors (≥6%) always show. Removed the `useIsLargeScreen()` matchMedia hook (and its `useEffect` import) — sizing AND label density are now container-driven, smooth across the rail's width transition.
- [x] Task 3: Tests (AC: #6)
  - [x] `portfolio-pizza.test.tsx`: replaced the matchMedia stub/tests with container-query assertions — the pizza root carries `@container`, the `<svg>` carries `@`-variant size classes (and no plain viewport `lg:`), minor-sector label `<g>` carries `hidden` while major labels don't. 7/7 pizza green.
- [x] Task 4: Verify (AC: #2, #3, #5)
  - [x] `tsc` + `eslint` clean; `vitest` 7/7 pizza + full portfolio suites green. Real-Chrome CDP at 1366px, toggling the rail: **expanded** → donut 240px, card **397px**; **collapsed** (wider card) → donut grows to 256px, card **still 397px**. So the donut tracks the card and the **card height holds** when the rail toggles (the regression is fixed). On a wide window the card is wide → donut hits the larger `@2xl/@3xl` steps (the prior story's win is kept).

## Dev Notes

### Where this fits

Frontend-only refinement of `portfolio-pizza.tsx` (and possibly one `@container` class on the live page's donut card). No API/data change. This corrects the viewport-keyed sizing from `portfolios-donut-responsive` to be **container-keyed**.

### Why container queries (the crux)

The sidebar changes the **content width**, not the **window width**. Viewport media queries (`lg:`/`xl:`) only see the window, so they can't respond to the rail toggling. **Container queries** (`@container` + `@…:` variants) respond to the nearest container ancestor's width — exactly the card that narrows when the rail expands. Tailwind v4 has these built in (the project is on `tailwindcss: ^4`): mark an ancestor `@container`, then use `@sm/@md/@lg/@xl/@2xl/@3xl` (container-width thresholds, in rem) on descendants. **Do NOT** reach for a JS window-width listener for sizing — that's the bug being fixed.

### Reuse / current state being modified

- `portfolio-pizza.tsx` (current): SVG `h-60 w-60 shrink-0 lg:… xl:… 2xl:…`; `useIsLargeScreen()` (matchMedia, `(min-width:1024px)`) → `labelMin = isLarge ? 0.035 : LABEL_MIN_FRAC`; the `flex flex-wrap items-center gap-6` donut+legend row; viewBox `0 0 300 300` (`S/R/RI/LABEL_R`, fontSizes) — **unchanged** here. Swap the *viewport* size/label signals for *container* ones; keep everything else.
- `sidebar.tsx`: `<aside class="shrink-0 … transition-[width]" + (collapsed ? "w-16 px-2" : "w-60 px-4")>`; state in `localStorage['qrp-sidebar-collapsed']` via `useSyncExternalStore`. You don't modify the sidebar — you just need the donut to react to the resulting card width.
- `useIsDark` / `rgbFor` / `textInk` (from `portfolio-heatmap.tsx`) — keep.
- If you use a `ResizeObserver` for label density, mirror the SSR-safe pattern of `useIsDark` (guard for absence, default to small, subscribe in `useEffect`, clean up). jsdom has no `ResizeObserver` → stub it in tests.

### Critical conventions (regressions if violated)

- **No new dependency** — Tailwind v4 container queries are built in; `ResizeObserver` is a browser API. Don't add a lib.
- **SSR/hydration safety** — same as before: default small on first render, upgrade on mount; never read layout during render; respect the `react-hooks/set-state-in-effect` lint (set state inside the effect/observer callback).
- **Don't change the SVG geometry** (`viewBox`/`S`/`R`/`RI`/fontSize) — only the rendered size and the label-cutoff signal.
- **Keep heat-map semantics + math** (color=daily move, size=Σ|weight|, label=daily P&L contribution; legend totals to Daily P&L).
- **Verify both sidebar states via headless Chrome** at laptop width (set `localStorage['qrp-sidebar-collapsed']` before navigation; value matches how `sidebar.tsx` reads it). Don't ask Andre to toggle. Dev server: console :3000, API :8001; frontend hot-reloads.

### Files to touch

- MOD `apps/web/components/portfolio-pizza.tsx` (container-query size variants; container-driven label density; possibly drop `useIsLargeScreen`)
- POSSIBLY MOD `apps/web/app/portfolios/[id]/live/page.tsx` (add `@container` to the donut card cell if that's the cleanest container boundary)
- MOD `apps/web/__tests__/portfolio-pizza.test.tsx` (assert container variants; adjust label-density test signal)

### References

- [Source: apps/web/components/portfolio-pizza.tsx] — current viewport-keyed donut size + `useIsLargeScreen` + `labelMin` + the flex-wrap donut/legend row.
- [Source: apps/web/components/sidebar.tsx:140-145] — the `<aside> shrink-0 w-16/w-60 transition-[width]` rail + `localStorage['qrp-sidebar-collapsed']` via `useSyncExternalStore`.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx:157-165] — the `lg:grid-cols-2` donut+movers card row (the donut card is the left cell).
- [Source: _bmad-output/implementation-artifacts/portfolios-donut-responsive.md] — the prior story this refines (viewport→container).
- [Source: memory feedback_minimize_dev_churn] — verify via headless Chrome (both sidebar states), not by asking Andre.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- RED first: container-query tests failed against the viewport (`lg:`) code. After implementing, the
  size test still "failed" on a regex bug — `/\blg:[hw]-/` matched the `lg:h-` inside `@lg:h-64`
  (word boundary after `@`); fixed with a negative lookbehind `/(?<!@)\blg:[hw]-/`.
- Real-browser verification: localStorage+`Page.reload` did NOT flip the rail reliably (both states read
  expanded) — switched to **clicking the collapse toggle** via CDP `Input.dispatchMouseEvent` (toggles
  live, no reload), which worked. Also had to target the donut by `svg[aria-label*="donut"]` — the first
  `<svg>` on the page is the sidebar's 16px collapse icon.

### Completion Notes List

- **Root cause fixed:** the prior story sized the donut by **viewport** media queries, so expanding the
  sidebar (which narrows the card, not the window) didn't shrink it → the legend wrapped below → the card
  grew taller. Now the donut sizes by its **container** (Tailwind v4 `@container` on the pizza root +
  `@sm/@lg/@xl/@2xl/@3xl` size variants on the SVG), so it tracks the card width and the card height holds.
- **Pure CSS, no JS hooks:** removed `useIsLargeScreen` (matchMedia). Label density is also container-
  driven via CSS — minor slices render with `hidden @2xl:block` (shown only on a wide container). This
  updates smoothly during the rail's 200ms width transition with zero re-renders (a JS ResizeObserver
  would have fired every frame).
- **No regression:** small/mobile (narrow container) → small donut + only major labels; heat colors,
  contribution math, legend + total, center gross %, hover tooltip, dark/light, accessibility all
  unchanged. No new dependency.
- **Verified in real Chrome (CDP, 1366px):** rail expanded → donut 240px / card 397px; rail collapsed
  (wider card) → donut 256px / card **still 397px**. tsc + eslint clean; 7/7 pizza + portfolio suites green.

### File List

- MOD `apps/web/components/portfolio-pizza.tsx` (`@container` root; container-query SVG size variants; CSS-gated minor labels; removed `useIsLargeScreen`)
- MOD `apps/web/__tests__/portfolio-pizza.test.tsx` (container-query assertions; dropped matchMedia stub)

## Open Questions (for Andre — do not block implementation)

1. **Container thresholds.** I'll pick container-width breakpoints so the donut is large when the card is wide and shrinks a step when the rail expands at laptop width. If after seeing it you want it to shrink more/less aggressively, the thresholds are a quick tune.
2. **Continuous vs stepped sizing.** Container-query variants give a few discrete sizes (simplest, no JS). A `ResizeObserver` could size the donut *continuously* to the card (perfectly smooth, never wraps) at the cost of a little JS. Default: container-query steps; say if you want the continuous version.
3. **Label density signal.** If I keep discrete container steps, the label cutoff steps with them. If you want labels to appear/disappear smoothly as the donut grows, that pairs with the `ResizeObserver` option in Q2.

## Review Findings (code-review 2026-06-20)

3 adversarial layers (Blind, Edge, Acceptance) on the combined donut diff (this story + the superseded
`portfolios-donut-responsive`). All ACs of BOTH stories verified met in the final state; no correctness
bugs in the production logic (threshold consistency, gating boundary, geometry, keys, SSR-safety all
clean; `useIsLargeScreen`/matchMedia confirmed fully removed). 2 patches, 4 dismissed.

- [x] [Review][Patch] First grow step causes a narrow "grow-then-wrap" band (FIXED 2026-06-20) — dropped the `@sm` size step; the base 208px (`h-52 w-52`) now holds until `@lg` (512px), so the donut never grows to a size that can't sit beside the legend. Removes the 384–471px wrap band; genuinely narrow cards still stack gracefully via `flex-wrap`.
- [x] [Review][Patch] Minor-label test hardened (FIXED 2026-06-20) — the test now also asserts the minor `<g>` carries the exact `@2xl:block` show-variant (catches a typo'd variant jsdom can't evaluate), and the dead `"Information Technology"` lookup was replaced with `"Tech"` (the fixture's literal sector).

Dismissed (4): the `@2xl` minor-label gate controls *when* a label shows, not whether it fits the (fixed-geometry) wedge — acceptable heuristic, labels have a `paintOrder` stroke halo; `labelGroupFor` `textContent.includes` + `.find()` is fine here (label `<g>`s are flat siblings, paths/center-texts aren't `<g>`s, no ancestor aggregation); the `/(?<!@)\blg:[hw]-/` lookbehind regex is correct for the inputs (the `\b` is redundant but harmless); "couldn't verify `useIsLargeScreen` removal" (Blind, diff-scope only) — the Acceptance Auditor confirmed it's fully gone (only `useState` + `useIsDark` remain).

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: size the sector donut by its CONTAINER (Tailwind v4 container queries) instead of the viewport, so expanding the sidebar (which narrows the card, not the window) shrinks the donut to keep it beside the legend and holds the card height constant — fixing the regression from `portfolios-donut-responsive`. Frontend-only. Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): `@container` on the pizza root + `@sm/@lg/@xl/@2xl/@3xl` SVG size variants (dropped viewport `lg:`/`xl:`); CSS-gated minor labels (`hidden @2xl:block`); removed `useIsLargeScreen`/matchMedia. Real-Chrome CDP (1366px, toggling the rail): donut tracks the card (240↔256px), card height holds at 397px. 7/7 pizza + portfolio suites green; tsc + eslint clean. Status → review. |
| 2026-06-20 | Code-review (3 adversarial layers): all ACs of both donut stories met, no correctness bugs. 2 patches applied: dropped the `@sm` grow step (removes a 384–471px grow-then-wrap band); hardened the minor-label test (assert exact `@2xl:block`, drop dead lookup). 31 portfolio tests green; tsc + eslint clean. Status → done. |
