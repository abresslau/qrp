# Retrospective — Console hardening

Date: 2026-06-17 · Scope: the console-hardening passes (NOT a numbered epic; not in sprint-status.yaml) · Facilitator: Amelia (Developer) · Lead: Andre

> Written retro (solo owner-operated project), same adaptation as the classification retros. This
> closes the console-hardening items the Epic QH retro (`epic-qh-retro-2026-06-16b.md`) left deferred,
> and checks whether the classification retros' recurring lessons showed up here too.

## What the two passes delivered

Both addressed deferred QH.6/QH.7/QH.8 frontend items in `apps/web` (Next 16 / React 19, vitest harness), all on the **stale-async / alive-guard / abort / error-surfacing** theme.

1. **command-palette** — a11y: focus trap, focus restore on close, body scroll-lock, selected-item `scrollIntoView`; plus a **run-session/generation token** fixing the close→reopen op-run navigation bug (the bare `openRef` couldn't tell a reopen from "same session"). The `aria-*`, the `openRef` close-guard, and the retry-latches were already done — verified, not re-touched.
2. **analytics-panel + portfolios** — analytics-panel cleanup now aborts the **current** in-flight live controller (not a stale mount-time capture); portfolios got a **generation token** on `fetchData` (a slow stale failed load can't clobber a newer success) + **`r.ok`/try-catch** on the create paths (surface the error, keep the form). The silent-`.catch`, `loadLive`'s AbortController, and the benchmarks `alive` guard were already done.

Outcome: **9 new tests; 37 web tests pass, eslint 0, tsc clean, `next build` green.** Two reviewed `--no-ff` merges.

## Follow-through on the Epic QH retro's deferred items

| QH-retro deferral | Status |
|---|---|
| Palette a11y pass (focus trap / scroll-lock / restore / auto-scroll) | ✅ **Done** (pass 1) |
| Palette reopen-before-run-resolves navigates (needs a session token) | ✅ **Done** — run-session token (pass 1) |
| analytics-panel manual-refresh controller not aborted on unmount | ✅ **Done** (pass 2) |
| portfolios retry/create double-fetch race | ✅ **Done** — generation token (pass 2) |
| portfolios create paths ignore `r.ok` | ✅ **Done** (pass 2) |
| heatmap tooltip-resize clamp; sidebar sync-throw / empty-submenu-latch; palette `setOps` unmount-guard | ❌ Still deferred (minor — see below) |

Every *substantive* deferred console item is now closed; only cosmetic/theoretical ones remain.

## Did the classification retros' recurring lessons recur here?

- **Stale-async guarding (the per-item-isolation lesson, generalized): YES — it *was* the whole theme.** The palette run-session token, the analytics abort-the-current-controller, and the portfolios generation token are the SAME failure class as classification's per-item isolation: *an async resolution must be guarded against a context that changed while it was in flight* (unmount, pid switch, close→reopen, a superseding load). Three components, one idiom.
- **"A behavior-preserving refactor drops the non-obvious behavior": YES, again.** The analytics bug was *introduced by a prior refactor* — the cleanup captured `const ac = liveAbort.current` with the comment "avoid reading the ref in the teardown." That defensive move (to dodge a *perceived* lint concern) froze the mount-time controller and left manual refreshes uncancelled. Reading the ref in the cleanup was fine all along. Identical shape to the classification registry's `factory()`-outside-the-try regression: a refactor preserved the obvious behavior and quietly dropped the subtle one. The QH retro had *already* flagged this class ("a refactor done to satisfy a lint rule tripped a fresh warning").
- **"Green tests ≠ reviewed": consistent.** These items were surfaced by the QH **code reviews** (deferred, not failing any test); the suite was green throughout. The new tests were written fail-without-the-fix.
- **"Self-assessment drifts optimistic": inverted-but-applied.** Less relevant (these were known deferrals, not fresh claims) — but the discipline showed up as its mirror: I **probed the current code first** rather than trusting the ledger, and found several "deferred" items (`aria-*`, `openRef`, retry-latches, the silent-`.catch`, the `alive` guards) were *already done*. Trust-but-verify saved redundant work.

## What went well

- **Probe-before-build avoided rework.** Reading each component before touching it showed ~half the ledgered items were already fixed in earlier passes — so the work targeted only the genuinely-open ones.
- **Cohesive, component-at-a-time scoping.** Palette first (densest cluster), then analytics+portfolios — each its own reviewed merge, easy to reason about and revert.
- **Tests pin the fix, not just the happy path.** Each new test fails without its fix (manual-refresh-aborted-on-unmount; close→reopen no-navigate; stale-load-doesn't-clobber; failed-create-surfaces).

## What was hard / friction

- **The deferred-work ledger was partly stale** — it listed items already closed by QH.7/QH.8. Not a blocker (the probe caught it), but a reminder that ledger entries decay as later passes quietly address them.
- **The same lint-driven anti-pattern recurred** — "restructure to avoid reading a ref/satisfy a rule" produced the analytics stale-capture bug, echoing the QH retro's own warning. The fix was to read the ref (correct) rather than contort around it.

## Action items

1. **Extract the async-resolution guard into a tiny shared idiom** — the abort + generation-token + alive-flag pattern now appears in the palette, analytics-panel, and portfolios (and `loadLive`). A small documented hook would stop the next component reinventing it (and getting it subtly wrong, as analytics did). — **DONE ✅ (2026-06-17):** `lib/use-run-guard.ts:useRunGuard()` — the generation-token + mount-safety primitive behind three verbs (`begin` for event-handler-concurrent ops; `supersede`+`capture` for session-reopen). Applied to **portfolios** (`begin`, replacing the manual genRef + adding mount-safety) and **command-palette** (`supersede` on open + `capture` at op-launch, replacing the manual genRef). Deliberately NOT forced onto analytics' `loadLive` AbortController (real cancellation) or its effect-scoped `alive` flags — those are the right, different primitives (heeding this retro's own "don't refactor working code onto a generic just for DRY" lesson). 4 hook unit tests; the existing palette + portfolios tests confirm behavior preserved; 41 web tests, eslint 0/0, tsc, build green.
2. **Prune the deferred-work ledger when a pass closes items** — mark entries ✅ as they're addressed (done for these) so the ledger doesn't carry phantom work. _Process; done this pass._
3. **Leave the remaining console items ledgered** — heatmap tooltip-resize clamp (cosmetic; needs an intervening mousemove), sidebar sync-throw (theoretical — sole provider is `async`) / empty-submenu-latch (documented trade-off), palette `setOps`/`setAsyncScreens` unmount-guard (React-19 no-op; the palette never unmounts). All low-value; not worth a pass. _Owner: agent/Andre · conditional._

## Readiness assessment

- **Complete + on `main`.** All substantive console-hardening items closed across two reviewed merges; 37 web tests, eslint 0, tsc clean, `next build` green.
- **No deploy step beyond the standard web build.** No carried blocker.
- **Genuinely-left work is cosmetic/theoretical** (action item 3), ledgered.

## No "next epic"

Console hardening is a cross-cutting cleanup, not an epic with a successor. The reusable-guard idiom (action item 1) is the one forward-looking item; otherwise this is a clean close. Other open tracks (the optional classification follow-ups, or new feature work) are independent.
