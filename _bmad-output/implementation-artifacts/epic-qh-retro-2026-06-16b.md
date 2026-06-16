# Epic QH — Production Hardening — Retrospective (3rd pass: the console-hardening arc)

**Date:** 2026-06-16 (later same day)
**Project Lead:** Andre
**Augments:** [epic-qh-retro-2026-06-15.md](epic-qh-retro-2026-06-15.md) + [epic-qh-retro-2026-06-16.md](epic-qh-retro-2026-06-16.md).

> Owner-operated project — working retrospective (analysis + decisions + actions), not a
> multi-person ceremony.

## Why a third QH retro

The 2026-06-16 augment closed Epic QH at 6/6 after QH.2 landed. Since then **QH.7** (console test
harness) and **QH.8** (console fetch-hardening) were each created, implemented, 3-layer
adversarially reviewed, patched, committed, and merged. **Epic QH is now 8/8.** This pass captures
that arc and the review→deferral→new-story loop it produced.

| Story | Outcome |
|-------|---------|
| QH.7 — Console test harness | done (2026-06-16) — vitest + @testing-library + jsdom in `apps/web`; 17 tests (palette / subnav registry / live-PnL badge); the 12-error RED lint baseline cleared (no suppressions); reviewed → 5 patches. Merged. |
| QH.8 — Console fetch-hardening | done (2026-06-16) — AbortController newest-request-wins + benchmarks `alive` guard; palette `openRef` close-safety + ops/submenu latch split; `portfolios` honest load-failure. +8 tests (25 total); reviewed → 2 patches. Merged. |

**Delivery:** 8/8 done. **0 production incidents** across the whole epic. Console went from **0 → 25
automated tests** in two stories.

## What went well

- **The thrice-deferred headline action is finally discharged — and immediately used.** "No console
  test infrastructure" was the systemic finding in BOTH prior retros (Action #1, "4× implicated").
  QH.7 stood up the harness; QH.8 consumed it the very next story. The action didn't get re-logged —
  it got done, then leveraged.
- **RED lint baseline eliminated** (QH.7) via derive-don't-sync / `useSyncExternalStore` /
  AbortController — **zero `eslint-disable`**. The console now starts green (0 errors, 0 warnings).
- **Adversarial review earned its keep a 5th/6th consecutive time.** QH.7: 5 patches incl. a real
  render-crash guard (`getSnapshot` reading `localStorage` during render). QH.8: 2 patches, the
  headline one a hole in **QH.8's own AC5** — `portfolios` didn't check `r.ok`, so an HTTP 500 would
  parse the error body as the list and bypass the very error state the story added.
- **Tests written to fail-without-the-fix.** QH.8 AC1 (stale-pid overwrite), AC3 (close-safety),
  AC4 (retry), AC5 (error+retry) each genuinely discriminate the fix. Where one couldn't (AC2
  unmount — vacuous under React 19, which dropped the setState-after-unmount warning), it was flagged
  honestly in the review rather than dressed up.

## What didn't — patterns

- **Lint-driven refactors carry their own regressions.** QH.7's `set-state-in-effect` fixes needed
  review to catch a UX regression (explorer lost its loading indicator); QH.8's first
  AbortController attempt tripped a fresh `exhaustive-deps` warning. **A refactor done to satisfy a
  linter deserves the same review scrutiny as a feature — the fix is not free.**
- **Every review on a mature surface surfaces a fresh batch of pre-existing issues — the hardening
  loop can run forever.** QH.7 review → 7 deferrals → became QH.8. QH.8 review → 6 MORE deferrals
  (reopen-mid-run navigation, portfolios double-fetch race, create-path error handling, …). This is
  the defining shape of the arc, and the reason a stop rule (below) matters.

## Decisions (Andre, 2026-06-16)

- **Did NOT auto-spawn QH.9** from the QH.8 review deferrals. They were ledgered, not actioned.
- **Stop rule (the durable lesson of this arc):** *when a review's deferrals are all beyond-AC and
  carry no user-facing impact, ledger and stop — do not reflexively spin another hardening story.*
  The 6 QH.8 deferrals are all beyond-AC or React-19 no-ops, so QH.8 is the right place to stop the
  console-lifecycle loop. (Recorded here in the artifact; not promoted to a cross-session memory
  unless wanted later.)
- **Session stop:** save this retro and stop — no new story picked up.

## Prior action-item follow-through

| From | Action | Status |
|------|--------|--------|
| 06-15 #1 | Console test harness | ✅ DONE (QH.7) |
| 06-15 #2 | Clear the RED lint baseline | ✅ DONE (QH.7) |
| 06-15 #3 | Palette a11y pass (focus trap / scroll-lock) | ❌ still deferred |
| 06-15 #4 | Non-Brazil GICS (SEC SIC→GICS, 134 rows) | ❌ still deferred — the one FUNCTIONAL gap left |
| 06-15 #5 | Spec-reuse self-check in `dev-story` | ⏳ partial — reviews keep catching it; no formal gate |
| 06-15 #6 | Broad introspection read-only role | ❌ still deferred (low priority) |
| 06-16 #7 | Promote test harness → a real story | ✅ DONE (became QH.7) |
| 06-16 #8 | "Name the probe + re-test trigger" rule | ✅ DONE (saved as a memory) |

## Open ledger (not actioned — by decision)

- **QH.8 review deferrals (6):** palette reopen-mid-run navigation; manual-refresh controller not
  aborted on unmount (nil React-19 impact); portfolios retry/create double-fetch race; portfolios
  create-path `r.ok`/try-catch; palette `setOps`/`setAsyncScreens` unmount guard + submenu in-flight
  dedupe. All in `deferred-work.md`. Subject to the stop rule above.
- **Standing functional gap:** non-Brazil GICS (134 `sym validate` FAIL rows) — the only outstanding
  item that is product coverage rather than hardening-loop churn. The natural next story IF Epic QH
  is ever reopened, or a fresh epic.

## Readiness assessment

- **Tests/build:** console 25 vitest tests + Python suites green; eslint 0/0; tsc clean; `next build`
  18/18 routes.
- **Production incidents:** 0 across the entire epic.
- **Deployment:** dev environment; nothing deployed. The manual browser pass remains the standing
  pre-deploy operator step (unchanged across all three retros).
- **Significant discoveries:** none forcing a plan change. No next epic exists; FR-13…FR-22 closed.

## Decision summary

Epic QH is **complete (8/8), stable, and tested**. The console-hardening loop is **intentionally
closed at QH.8** per the stop rule. The only forward thread worth a future story is **non-Brazil
GICS** (functional coverage). Session stops here.
