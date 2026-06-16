# Story QH.7: Console test harness (vitest + @testing-library)

Status: done

<!-- Promoted from Epic QH retrospective Action #1 (held 2026-06-15, re-affirmed 2026-06-16). -->

## Story

As the **operator-developer of the QRP console**,
I want **a unit-test harness in `apps/web` (vitest + @testing-library/react) with tests backfilled
for the highest-logic frontend surfaces, and the RED lint baseline cleared**,
so that **the command palette, the subnav-provider registry, and the live-PnL badge are guarded by
fast tests rather than `tsc` + `eslint` + manual checking — the gap flagged in QH.4, QH.6, and QH.2**.

## Scope decision (read first)

The console is the only part of QRP with **no automated test layer**. Three stories in a row
(QH.4 SSE, QH.6 palette/registry, QH.2 live badge) shipped frontend logic verified only by
`tsc --noEmit` + `eslint` + `next build` + manual. The retro headline action across two QH retros
is the same: stand up a real test harness and backfill the logic that unit tests should guard.

**In scope:**
- `vitest` + `@testing-library/react` + `jsdom` wired into `apps/web` (config, `npm test` script).
- Tests for the three surfaces below (pure-logic + render/interaction, **no network** — mock `fetch`).
- Clear the pre-existing RED lint baseline (the `react-hooks/set-state-in-effect` errors, incl. the
  `analytics-panel` one QH.2 left untouched) via derive-don't-sync, so the console starts green.

**Out of scope (defer):** Playwright/e2e (manual operator pass stays the pre-deploy check), visual
regression, MSW (plain `fetch` mocks are enough at this scale), backend test changes.

## Acceptance Criteria

1. **Harness runs.** `npm test` in `apps/web` executes vitest against `jsdom`, green, with the new
   tests collected. A watch script exists. No change to `next build` / `tsc` / `eslint` behavior.
2. **Command palette (⌘K) covered.** Tests for: substring filtering, ↑/↓ selection (clamped at
   the ends — the palette does not wrap), Enter-to-navigate, read-only-launch vs writer-route, and result/`msg` surfacing
   (the AC5 issue the QH.6 review caught) — all with a mocked registry + `fetch`.
3. **Subnav-provider registry covered.** Tests for the fail-safe state machine: a provider that
   throws does not crash the sidebar; the `loadedRef`/retry latch behaves (no infinite refetch on a
   failing async provider — the QH.6 review's empty-submenu loop).
4. **Live-PnL badge covered (QH.2).** Tests for `analytics-panel`: `freshness` → `FRESH_STYLE`
   mapping (live/delayed/unavailable, and the `?? unavailable` fallback for an unknown value), the
   `n_priced > 0` render gating, and the `as_of` null-guard (no "Invalid Date").
5. **RED lint baseline cleared.** `eslint` over `apps/web` reports **0 errors** (not just on touched
   files) — the `set-state-in-effect` baseline is fixed by derive-don't-sync, not suppressed.
6. **No regressions.** `tsc --noEmit` clean, `next build` all routes, the Python suites untouched.

## Tasks / Subtasks

- [x] **Task 1 — Wire the harness** (AC: 1) — added `vitest@3` + `@vitejs/plugin-react` +
  `@testing-library/react@16` + `@testing-library/user-event@14` + `@testing-library/jest-dom@6` +
  `jsdom@25` + `vite-tsconfig-paths@5` to devDeps; `vitest.config.ts` (jsdom env, `@/*` alias via
  vite-tsconfig-paths, `vitest.setup.ts` for jest-dom + auto-cleanup); `test`/`test:watch` scripts.
  (`node_modules/next/dist/docs/` is not shipped in this install; followed standard Next 16 / React
  19 conventions — vitest config is independent of the Next build.)
- [x] **Task 2 — Palette tests** (AC: 2) — `__tests__/command-palette.test.tsx` (7): ⌘K open,
  substring filter, ↓-selection, Enter-navigate+close, read-only-op launch→Operate, rejection
  surfaced inline (QH.6 AC5), writer-op routes without POSTing /run.
- [x] **Task 3 — Registry tests** (AC: 3) — `__tests__/sidebar.test.tsx` (3): a throwing provider
  doesn't crash the sidebar; a FAILED load retries on route change; a SUCCESSFUL load is latched
  (no refetch across routes).
- [x] **Task 4 — Live-PnL badge tests** (AC: 4) — `__tests__/analytics-panel.test.tsx` (5):
  live/delayed/unknown→`FRESH_STYLE` mapping, `n_priced===0` hides the block, `as_of` null-guard.
- [x] **Task 5 — Clear the lint baseline** (AC: 5) — all 12 errors fixed (no suppressions):
  4 unescaped-entities (`&apos;`), 5 `set-state-in-effect` (theme-toggle→`useSyncExternalStore`;
  portfolios→async-only fetch + initial loading; explorer→setState in the debounce timer;
  analytics-panel & heatmap→async IIFE), 3 `refs` (heatmap tooltip clamp reads `pos.w` captured on
  mouse-move, not `containerRef.current` during render). `eslint .` → 0 errors.
- [x] **Task 6 — Verify** (AC: 6) — `npm test` 16/16, `tsc --noEmit` clean, `next build` 18/18
  routes, Python suites untouched. Palette a11y deferral (prior Action #3) left ledgered.

## Dev Notes

- **References:** [epic-qh-retro-2026-06-15.md] Action #1/#2/#3; [epic-qh-retro-2026-06-16.md]
  Action #7; QH.6 story (palette + `SUBNAV_PROVIDERS` registry); QH.2 story
  (`apps/web/components/analytics-panel.tsx` live badge, `FRESH_STYLE`).
- **Files of interest:** `apps/web/components/analytics-panel.tsx` (badge), the command-palette
  component + the `SUBNAV_PROVIDERS` registry from QH.6, `apps/web/lib/api.ts` (Schemas types).
- **Pairs with the palette a11y deferral** (prior Action #3) — not in this story's ACs, but the
  same files; do it here if cheap, else leave ledgered.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- `npm install --save-dev vitest@^3 @vitejs/plugin-react@^5 jsdom@^25 @testing-library/react@^16 @testing-library/user-event@^14 @testing-library/jest-dom@^6 vite-tsconfig-paths@^5` → added 115 packages.
- `npm test` → 4 files, **16 tests passed** (smoke 1, command-palette 7, sidebar 3, analytics-panel 5).
- `npx eslint .` → exit 0, **0 errors** (baseline was 12).
- `npx tsc --noEmit` → exit 0. `npm run build` → compiled + 18/18 routes generated.
- One iteration: the sidebar "latched" test initially raced the success microtask (2 fetches vs 1); fixed by waiting on the committed submenu (`findByLabelText("Expand Macro")`) before the route change rather than the call count.

### Completion Notes List

- **Harness is independent of the Next build.** `node_modules/next/dist/docs/` (per `apps/web/AGENTS.md`) is not present in this install; vitest.config.ts + jsdom + RTL follow standard Next 16 / React 19 conventions and don't touch `next.config.ts`. Tests live in `apps/web/__tests__/` (`**/*.test.tsx`), excluded from the route graph.
- **Component tests mock the seams, not the logic:** `next/navigation` (router/pathname via `vi.hoisted`), `next/link`/`ThemeToggle` (sidebar), and a URL-routed `fetch` stub. No network, no DB — true to AC1's DB-free mandate.
- **Lint baseline cleared by real fixes, never `eslint-disable`.** The `set-state-in-effect` cases use derive-don't-sync where it fit (theme-toggle→`useSyncExternalStore` with a server snapshot, so no hydration mismatch; portfolios→initial-loading + async-only sets) and async-flow restructuring elsewhere (the loading flip moves out of the synchronous effect body into an async IIFE / the debounce timer — idiomatic async effects, not suppressions). The `refs` rule is fixed by capturing the container width into `pos` on mouse-move instead of reading `containerRef.current` during render.
- **Deferred (ledgered):** the palette a11y pass (focus trap/restore/scroll-lock/auto-scroll, prior retro Action #3) — same files, but out of this story's ACs.

### File List

- `apps/web/package.json` (UPDATE) — test devDeps + `test`/`test:watch` scripts.
- `apps/web/package-lock.json` (UPDATE) — lockfile for the new devDeps.
- `apps/web/vitest.config.ts` (NEW) — jsdom + react + tsconfig-paths, setup file, `**/*.test.{ts,tsx}`.
- `apps/web/vitest.setup.ts` (NEW) — jest-dom matchers + RTL auto-cleanup.
- `apps/web/__tests__/harness.smoke.test.tsx` (NEW) — harness proof (AC1).
- `apps/web/__tests__/command-palette.test.tsx` (NEW) — 7 tests (AC2).
- `apps/web/__tests__/sidebar.test.tsx` (NEW) — 3 tests (AC3).
- `apps/web/__tests__/analytics-panel.test.tsx` (NEW) — 5 tests (AC4).
- `apps/web/components/theme-toggle.tsx` (UPDATE) — `useSyncExternalStore` (AC5).
- `apps/web/components/analytics-panel.tsx` (UPDATE) — async-IIFE fetch effect (AC5).
- `apps/web/components/heatmap-view.tsx` (UPDATE) — async-IIFE fetch effect + `pos.w` tooltip clamp (AC5).
- `apps/web/app/portfolios/page.tsx` (UPDATE) — derive-don't-sync loading (AC5).
- `apps/web/app/portfolios/[id]/page.tsx` (UPDATE) — `&apos;` escapes (AC5).
- `apps/web/app/sym/explorer/page.tsx` (UPDATE) — setLoading in debounce timer (AC5).
- `apps/web/app/sym/attention/page.tsx` (UPDATE) — `&apos;` escape (AC5).
- `apps/web/app/sym/validation/page.tsx` (UPDATE) — `&apos;` escape (AC5).

### Change Log

- 2026-06-16 — Implemented QH.7: stood up the `apps/web` console test harness (vitest +
  @testing-library + jsdom) and backfilled 16 tests across the command palette, the subnav-provider
  registry fail-safe/latch, and the QH.2 live-PnL badge; cleared the 12-error RED lint baseline
  (no suppressions). `npm test` 16/16, eslint 0 errors, tsc clean, `next build` 18/18. Status → review.
- 2026-06-16 — Code review (3 adversarial layers): 5 patches applied (theme-toggle render-crash
  guard; palette test mocks the registry + ArrowUp/clamp coverage; analytics as_of/Live-PnL positive
  assertions; palette nav `waitFor`; explorer immediate-loading restored), 7 pre-existing component
  issues deferred to deferred-work.md, 6 dismissed. `npm test` 17/17, eslint 0, tsc clean,
  `next build` 18/18. Status → done.

## Review Findings (code review 2026-06-16)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor), uncommitted diff on `qh-7-console-test-harness`.

### Patch (unchecked = open)

- [x] [Review][Patch] `theme-toggle` `getSnapshot` reads `localStorage` during render with no guard — render crash in private mode [apps/web/components/theme-toggle.tsx:21-23] — FIXED: `getSnapshot` wrapped in try/catch → `"dark"` on throw. — `useSyncExternalStore` calls `getSnapshot` during render; an unguarded `localStorage.getItem` throws `SecurityError` in private/sandboxed contexts → uncaught render error crashing the toggle (and parent). The writer already try/catches; the reader must too. Fix: wrap in try/catch → `"dark"` on throw.
- [x] [Review][Patch] Palette tests use the REAL `SUBNAV_PROVIDERS` — brittle ordering coupling, violates AC2 "mocked registry" [apps/web/__tests__/command-palette.test.tsx] — FIXED: `vi.mock("@/lib/nav")` with a 3-item fixture; selection asserted explicitly via the active row; added an ArrowUp/clamp test (8 palette tests now); AC2 wording corrected (clamp, not wrap). — the filter/selection tests depend on `SYM_SUBNAV` having exactly 7 entries with "Overview first"; a registry reorder breaks them for the wrong reason. Fix: `vi.mock("@/lib/nav")` with a small controlled fixture; assert the selected item explicitly. Also add an **ArrowUp** assertion (only ArrowDown is exercised) and correct AC2 wording ("↑/↓ selection", clamped — the palette does NOT wrap; "wrap" in the AC was wrong).
- [x] [Review][Patch] `as_of` null-guard / live-block tests are one-sided [apps/web/__tests__/analytics-panel.test.tsx] — FIXED: the live-render test now positively asserts "Live PnL" + `/as of/` are present, so the gating/null-guard tests guard a real regression. — the suite asserts "as of" is ABSENT when `as_of` is null but never positively proves it RENDERS when present (same for the "Live PnL" block marker). Fix: assert "Live PnL" + `/as of/` present in the live-render test, so the negative assertions guard a real regression.
- [x] [Review][Patch] Palette read-only-op success test relies on click-microtask timing for `nav.push` [apps/web/__tests__/command-palette.test.tsx] — FIXED: both op tests now `waitFor(() => expect(nav.push)…)`. — `push` fires in the `/run` fetch `.then`; asserting synchronously after `userEvent.click` is flake-prone. Fix: `await waitFor(() => expect(nav.push)…)` (the rejection test already awaits via `findByText`).
- [x] [Review][Patch] `explorer` lost immediate loading feedback (lint-fix UX regression) [apps/web/app/sym/explorer/page.tsx:60-63] — FIXED: `setLoading(true)` added to the query `onChange` (event handler — lint-safe); immediate feedback on type restored, effect stays lint-clean. — moving `setLoading(true)` into the 250ms debounce timer means typing shows stale results with no "Loading…" for the debounce window. Fix: also flip `setLoading(true)` in the `onChange` handler (an event handler — lint-allowed) so feedback is immediate; the timer keeps it lint-clean for the offset path.

### Deferred (pre-existing — surfaced by review, not introduced by QH.7)

- [x] [Review][Defer] `analytics-panel` `loadLive` (and the benchmarks effect) lack an `alive`/pid guard — stale-pid overwrite / setState-after-unmount [components/analytics-panel.tsx loadLive] — pre-existing QH.2 code; the QH.7 analytics-fetch effect WAS hardened.
- [x] [Review][Defer] `command-palette` `loadedRef` latches on ops success, so a FAILED async submenu (macro) never retries for the session — asymmetric with the sidebar's retry-on-route-change [components/command-palette.tsx:56-73] — pre-existing QH.6.
- [x] [Review][Defer] `command-palette` op-run resolution has no open/alive guard — closing the palette mid-run can still `router.push("/sym/operate")` [components/command-palette.tsx:132-149] — pre-existing QH.6.
- [x] [Review][Defer] `heatmap` tooltip clamp uses a captured `pos.w` that goes stale on a resize-without-mousemove (cosmetic; the `containerRef.current` read it replaced was itself the lint violation) [components/heatmap-view.tsx].
- [x] [Review][Defer] `sidebar` empty-but-successful macro load is latched, so categories populated later in the session never appear without a reload — documented trade-off [components/sidebar.tsx:55-57].
- [x] [Review][Defer] `sidebar` `loadSub` doesn't catch a SYNCHRONOUS throw from `p.load()` (only the returned promise's rejection) — theoretical; the only fetch provider is `async` so it can't throw sync [components/sidebar.tsx:51-66].
- [x] [Review][Defer] `portfolios` mount-fetch `.catch` swallows errors silently (empty list indistinguishable from a real failure) — pre-existing [app/portfolios/page.tsx].

### Dismissed (false positives / handled / verified clean)

- "Hides live block" / `as_of` assertions vacuous (Blind) — the Auditor confirmed `<span>Live PnL</span>` is the real marker; the present/absent pair is valid (strengthened by the P3 patch anyway).
- `fireEvent.change` + sync Enter race (Blind) — the filtered list is derived in `useMemo` (synchronous during render), so Enter acts on the committed filter. No race.
- `vitest include` sweeps `node_modules` (Blind) — vitest's default exclude covers it.
- jest-dom matcher types break `tsc` (Blind) — `tsc --noEmit` ran clean (the `/vitest` augmentation in `vitest.setup.ts` is picked up).
- `stubFetch` assumes string URL (Blind) — every call site passes a string `fetch(url, opts)`.
- AC3 tests rejection not a "synchronous throw" (Auditor) — for an `async` fetch provider a throw IS a rejection; the real failure mode is covered (the sync-throw gap is deferred above).
