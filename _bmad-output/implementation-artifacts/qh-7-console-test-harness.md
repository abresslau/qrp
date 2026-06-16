# Story QH.7: Console test harness (vitest + @testing-library)

Status: ready-for-dev

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
2. **Command palette (⌘K) covered.** Tests for: substring filtering, ↑/↓ selection + wrap,
   Enter-to-navigate, read-only-launch vs writer-route behavior, and result/`msg` surfacing
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

- [ ] **Task 1 — Wire the harness** (AC: 1) — add `vitest`, `@testing-library/react`,
  `@testing-library/user-event`, `jsdom` to `apps/web` devDeps; `vitest.config.ts` (jsdom env, path
  alias parity with `tsconfig`); `test` + `test:watch` scripts. NOTE: `apps/web/AGENTS.md` warns this
  Next.js build has breaking changes from training data — read `node_modules/next/dist/docs/` before
  touching config.
- [ ] **Task 2 — Palette tests** (AC: 2) — render the palette with a mock provider registry; cover
  filter/keyboard/launch-route/surfacing.
- [ ] **Task 3 — Registry tests** (AC: 3) — the fail-safe + retry-latch logic.
- [ ] **Task 4 — Live-PnL badge tests** (AC: 4) — `analytics-panel` freshness/gating/as_of.
- [ ] **Task 5 — Clear the lint baseline** (AC: 5) — derive-don't-sync the `set-state-in-effect`
  errors; confirm `eslint apps/web` → 0 errors.
- [ ] **Task 6 — Verify** (AC: 6) — `npm test`, `tsc`, `next build`; ledger anything deferred.

## Dev Notes

- **References:** [epic-qh-retro-2026-06-15.md] Action #1/#2/#3; [epic-qh-retro-2026-06-16.md]
  Action #7; QH.6 story (palette + `SUBNAV_PROVIDERS` registry); QH.2 story
  (`apps/web/components/analytics-panel.tsx` live badge, `FRESH_STYLE`).
- **Files of interest:** `apps/web/components/analytics-panel.tsx` (badge), the command-palette
  component + the `SUBNAV_PROVIDERS` registry from QH.6, `apps/web/lib/api.ts` (Schemas types).
- **Pairs with the palette a11y deferral** (prior Action #3) — not in this story's ACs, but the
  same files; do it here if cheap, else leave ledgered.
