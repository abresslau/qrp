# Story QH.8: Console fetch-hardening (stale-response / lifecycle safety)

Status: done

<!-- Promoted from the QH.7 code review (2026-06-16): the 7 pre-existing console issues the
review surfaced but QH.7 (test harness) did not introduce. Now unit-testable via that harness. -->

## Story

As the **operator using the QRP console**,
I want **the console's client-side `fetch` effects hardened against stale responses, unmount, and
mid-flight navigation, with load failures surfaced honestly instead of swallowed**,
so that **I never see another portfolio's live PnL bleed into the one I'm viewing, never get
silently navigated away after closing the palette, and can tell a failed load apart from an empty
result — each guarded by a unit test on the QH.7 harness**.

## Scope decision (read first)

The QH.7 review walked every changed (and adjacent) console surface and found a recurring class of
**pre-existing** client-fetch robustness gaps. QH.7 deliberately deferred them (it was the test-harness
story). This story fixes the genuinely-impactful ones and **locks each with a test** on the harness
QH.7 stood up. Pure frontend; no API/DB change; no new dependency.

**In scope (the real bugs):**
- **(A) Stale-response / unmount safety** on the console's on-demand fetches. The newest request
  must win and an unmounted component must not `setState`. The QH.2 live-PnL `loadLive` and the
  benchmarks effect in `analytics-panel` lack the `alive`/request-token guard the QH.7 analytics
  effect already got — a slow `/live` for portfolio A can land after the user switches to B and
  overwrite B's mark (a **correctness** bug, not just a warning).
- **(B) Palette op-run guarded against close.** A read-only op's `POST /run` resolving *after* the
  palette is Esc-closed can still `router.push("/sym/operate")` or `setMsg(...)` on the closed
  palette. Capture an open/alive flag and no-op the resolution if it's no longer open.
- **(C) Palette submenu-retry symmetry.** A failed async submenu provider (macro categories) is
  latched by the ops `loadedRef`, so it never retries on reopen — asymmetric with the sidebar,
  which retries on route change. Track submenu-load success per source so a *failed* submenu
  retries on the next open.
- **(D) Honest load-failure surfacing.** `portfolios` (and any list page with the same shape)
  swallows a mount-fetch failure in `.catch` → empty list, indistinguishable from a real empty DB,
  no retry. Add an error state + a retry affordance so a failure is visible.

**Out of scope (deliberate — do NOT change):**
- The **sidebar empty-but-successful latch** (categories populated later in a session don't appear
  without reload) — a documented, intentional trade-off in `sidebar.tsx`.
- The **heatmap tooltip `pos.w` resize staleness** — cosmetic (tooltip clamp off by a few px after a
  resize-without-mousemove); not worth a ResizeObserver. Leave ledgered.
- Any new dependency, any API/DB/contract change, Playwright/e2e.

## Acceptance Criteria

1. **Newest-request-wins on `analytics-panel` live PnL.** `loadLive` is guarded so a response for a
   prior `pid` (or a superseded manual refresh) cannot overwrite the current state, and no `setState`
   fires after unmount. Switching portfolio mid-flight shows the NEW portfolio's mark (or its
   loading/empty state), never the stale one. Test: a slow `/live` for pid A resolving after a remount
   on pid B does not set A's value into B.
2. **`analytics-panel` benchmarks effect is unmount-safe.** The benchmarks fetch does not `setState`
   after unmount (an `alive` guard). Behaviour otherwise unchanged (S&P 500 default selection).
3. **Palette op-run is close-safe.** If the palette is closed (Esc/⌘K/backdrop) before a read-only
   op's `POST /run` resolves, the resolution does NOT `router.push` and does NOT `setMsg`. Test:
   click a read-only op, close the palette before the run resolves → `nav.push` is not called.
4. **Palette retries a FAILED submenu on reopen.** A submenu provider whose `load()` rejected on
   first open re-attempts on the next open (not latched by the ops `loadedRef`); a *successful*
   submenu (even empty) is not re-fetched within the same open session. Mirrors the sidebar's
   retry-on-route-change posture. Test both paths.
5. **`portfolios` surfaces a load failure.** A failed mount fetch renders a visible error state with
   a retry control (distinct from the legitimate empty-list state); retry re-runs the load. Test:
   a rejected fetch shows the error + retry; clicking retry re-fetches and renders rows on success.
6. **No regressions, fully tested.** New/updated vitest tests cover ACs 1–5 on the QH.7 harness;
   `npm test` green, `eslint .` 0 errors (no new suppressions, no `set-state-in-effect`/`refs`
   reintroduced), `tsc --noEmit` clean, `next build` all routes. Python suites untouched.

## Tasks / Subtasks

- [x] **Task 1 — Stale/unmount guard for `analytics-panel` fetches** (AC: 1,2) — `loadLive` now uses
  an `AbortController` (each call aborts the prior in-flight; the `signal.aborted` check drops a
  superseded/post-unmount response); benchmarks effect got an `alive` guard. QH.7 analytics-effect
  guard intact. Tests: newest-request-wins (pid A resolving after switch to B) + unmount-safety.
- [x] **Task 2 — Palette close-safety + submenu retry** (AC: 3,4) — `command-palette.tsx`: an
  `openRef` (synced via effect) gates the `/run` resolution so a settle-after-close neither navigates
  nor `setMsg`s; the single `loadedRef` was split into `opsLoadedRef` + a per-source `subLoadedRef`
  Set, so a FAILED submenu retries on reopen while ops + successful submenus stay latched. Tests both.
- [x] **Task 3 — Honest load-failure on `portfolios`** (AC: 5) — added an `error` state + a Retry
  control (distinct from the empty-list row); `load()`/`fetchData()` set/clear it. New
  `__tests__/portfolios.test.tsx`: reject→error+retry→rows, and empty≠failure.
- [x] **Task 4 — Verify** (AC: 6) — `npm test` 23/23, `eslint .` 0/0, `tsc --noEmit` clean,
  `next build` 18/18. Heatmap-resize + sidebar empty-latch remain out-of-scope by decision.

## Dev Notes

### Current state of files being touched

- **`apps/web/components/analytics-panel.tsx`** (UPDATE) — `loadLive` (`useCallback([pid])`) fetches
  `/api/analytics/portfolios/{pid}/live` and `setLive` with no alive/token guard; the benchmarks
  effect (`[]`) `setBenches`/`setBench` with no guard. The benchmark/window analytics effect already
  has an `alive` guard (added in QH.7) — match that shape. The live block renders only when
  `live && live.n_priced > 0`; `FRESH_STYLE` badge keyed live/delayed/unavailable.
- **`apps/web/components/command-palette.tsx`** (UPDATE) — `loadedRef` latches after the
  `/api/operate/ops` fetch succeeds; the async-submenu `for` loop (macro `load()`) shares the early
  `return` so a failed submenu never retries. `act()` (the op handler) does `setMsg("Starting…")`
  then `POST /api/operate/run`; on success `router.push("/sym/operate")`, on rejection `setMsg`. No
  open/alive guard on that resolution. Esc/⌘K/backdrop set `open=false`.
- **`apps/web/components/sidebar.tsx`** (READ — reference, do NOT change the latch) — the canonical
  retry posture to mirror for AC4: `loadedOkRef` adds a key only on success, so a FAILED load retries
  on route change; a successful (even empty) load is not retried. The empty-latch behaviour is the
  intentional trade-off that stays.
- **`apps/web/app/portfolios/page.tsx`** (UPDATE) — `fetchData()` (QH.7 split) does the mount load;
  `load()` adds the loading flip for event-handler refreshes. The `.catch(() => setLoading(false))`
  swallows failure → empty list. Add an `error` state + retry; keep the QH.7 derive-don't-sync shape
  (no `set-state-in-effect`).

### Key constraints

- **Lint discipline (QH.7 baseline must stay green):** any new effect must NOT reintroduce
  `react-hooks/set-state-in-effect` or `react-hooks/refs` — flip loading in event handlers / async
  flow, never synchronously in an effect body; never read `ref.current` during render. `eslint .` → 0.
- **Test harness (QH.7):** `apps/web/__tests__/*.test.tsx`, vitest + @testing-library + jsdom; mock
  `next/navigation` (router/pathname via `vi.hoisted`), `next/link`, and route a `fetch` stub by URL;
  mock `@/lib/nav` with a controlled fixture where registry contents matter (the QH.7 palette test
  pattern). Test globals are NOT enabled — import `{ describe, it, expect, vi }` from `vitest`.
- **No new dependency, no API/DB change.** Pure client-side robustness + tests.
- **Newest-request-wins pattern:** prefer a request token (a ref incremented per call; compare on
  resolve) or an `alive` flag in the effect/callback closure — drop the response if superseded. Match
  the existing QH.7 analytics-effect guard for consistency.

### References

- [Source: _bmad-output/implementation-artifacts/qh-7-console-test-harness.md#Review Findings → Deferred] — the 7 deferred items this story draws from (and the 2 left out-of-scope).
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#Deferred from: code review of qh-7-console-test-harness (2026-06-16)] — the same list, ledgered.
- [Source: apps/web/components/sidebar.tsx#loadSub, loadedOkRef] — the retry-on-failure posture to mirror for the palette (AC4).
- [Source: apps/web/components/analytics-panel.tsx — the benchmark/window effect] — the QH.7 `alive` guard shape to extend to `loadLive` + benchmarks.
- [Source: apps/web/__tests__/command-palette.test.tsx, sidebar.test.tsx] — the QH.7 mocking patterns (router/link/fetch/registry) to reuse.

### Project Structure Notes

- New test file: `apps/web/__tests__/portfolios.test.tsx`; UPDATE the analytics-panel + command-palette
  test files. No migration, no API change, no `api-types.ts` regen.
- Deferred (ledger): heatmap tooltip resize-staleness (cosmetic), sidebar empty-success latch
  (intentional), sidebar `loadSub` synchronous-throw (theoretical — the only fetch provider is async).

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- `npm test` → 5 files, **23 tests** (was 17; +6: live newest-wins, benchmarks unmount-safety, palette close-safety, palette submenu-retry, portfolios error+retry, portfolios empty≠failure).
- `eslint .` → 0 errors, **0 warnings**. First pass introduced a `react-hooks/exhaustive-deps` warning from reading `liveReq.current` in the effect cleanup; refactored the token counter to an `AbortController` captured in the effect body, clearing the warning.
- `tsc --noEmit` → exit 0. `npm run build` → 18/18 routes.

### Completion Notes List

- **AbortController, not a token counter.** The newest-request-wins guard for `loadLive` uses an
  `AbortController` (idiomatic, and actually cancels the superseded HTTP request) with the controller
  captured in the effect so the cleanup never reads `ref.current` — avoids the exhaustive-deps warning
  the counter version tripped. The `signal.aborted` check also covers post-unmount setState.
- **Palette latch split.** The old single `loadedRef` gated the whole load effect, so a failed async
  submenu never retried. Split into `opsLoadedRef` (ops list) + a per-source `subLoadedRef` Set; each
  latches independently and only on success — matching the sidebar's retry-on-route-change posture.
- **`openRef` for close-safety.** A ref mirrors `open` (synced in a one-line effect — a ref write, not
  setState, so no lint issue); the `/run` resolution bails if the palette closed meanwhile. The op
  still runs server-side (fire-and-forget) — we just don't navigate or message a dismissed palette.
- **AC2 honesty note:** React 19 no longer emits a setState-after-unmount warning, so the benchmarks
  unmount-safety test asserts "no console.error fallout" — it documents the guard's intent rather than
  failing loudly pre-fix. The other four ACs have tests that genuinely fail without the fix.
- **Out of scope held:** heatmap tooltip resize-staleness (cosmetic) and the sidebar empty-success
  latch (intentional) were left untouched per the story's scope decision; still ledgered.

### File List

- `apps/web/components/analytics-panel.tsx` (UPDATE) — `loadLive` AbortController guard + benchmarks `alive` guard; `useRef` import.
- `apps/web/components/command-palette.tsx` (UPDATE) — `openRef` close-safety on `/run`; `opsLoadedRef` + `subLoadedRef` latch split.
- `apps/web/app/portfolios/page.tsx` (UPDATE) — `error` state + Retry control; `load`/`fetchData` set/clear it.
- `apps/web/__tests__/analytics-panel.test.tsx` (UPDATE) — +2 tests (AC1, AC2).
- `apps/web/__tests__/command-palette.test.tsx` (UPDATE) — +2 tests (AC3, AC4) + macro fetch provider in the `@/lib/nav` mock.
- `apps/web/__tests__/portfolios.test.tsx` (NEW) — 2 tests (AC5).

### Change Log

- 2026-06-16 — Implemented QH.8: console fetch-hardening from the QH.7 review deferrals — newest-request-wins
  + unmount safety on `analytics-panel` (AbortController + alive guard), command-palette close-safety
  (`openRef`) + failed-submenu retry (latch split), and honest load-failure surfacing on `portfolios`
  (error + Retry). 6 new tests on the QH.7 harness. `npm test` 23/23, eslint 0/0, tsc clean, build 18/18.
  Status → review.
- 2026-06-16 — Code review (3 adversarial layers; Auditor confirmed all 6 ACs met): 2 patches applied
  (`portfolios` throws on `!r.ok` so HTTP errors hit the error state — closing an AC5 hole; palette ops
  latch only on a valid array so a malformed 200 retries). +2 tests (25 total). 6 deferred (beyond-AC /
  React-19 no-op), 4 dismissed. `npm test` 25/25, eslint 0/0, tsc clean, `next build` 18/18. Status → done.

## Review Findings (code review 2026-06-16)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) on the uncommitted diff. The Auditor independently re-ran the gates and found all six ACs genuinely met.

### Patch (unchecked = open)

- [x] [Review][Patch] `portfolios` load doesn't check `r.ok` — an HTTP 500-with-body bypasses the new error state (defeats AC5 for HTTP errors) [apps/web/app/portfolios/page.tsx:24-26] — FIXED: both load fetches throw on `!r.ok` → an HTTP error reaches `.catch` → error+retry. Test added (500 → error). — `fetch(...).then((r) => r.json())` parses a 500's JSON error body and `setList(<object>)`, never tripping the `.catch` → no error surfaced and `.map`/`.filter` over a non-array can crash. Fix: throw on `!r.ok` in each fetch so a server error reaches the `.catch` → error+retry. Add a 500-path test.
- [x] [Review][Patch] Palette ops latch on a malformed-but-200 body — a non-array ops payload latches `opsLoadedRef` and never retries [apps/web/components/command-palette.tsx:69-75] — FIXED: latch + `setOps` only when `Array.isArray(d)`; a garbage 200 stays unlatched → retries on reopen. Test added. — `setOps(Array.isArray(d) ? d : [])` then `opsLoadedRef.current = true` unconditionally, so a 200-with-garbage permanently empties ops (the opposite of AC4's retry-on-bad-load). Fix: only `setOps` + latch when `Array.isArray(d)`; otherwise leave unlatched so it retries on reopen. Add a test.

### Deferred (beyond this story's ACs / no React-19 impact — ledgered)

- [x] [Review][Defer] Reopen-before-run-resolves: a superseded read-only op that resolves after the palette is closed AND reopened still navigates (openRef can't tell open-sessions apart) [command-palette.tsx openRef] — beyond AC3 (which covers close→stay-closed, tested); a run-session/generation token would fix it. Uncommon (close then reopen mid-run).
- [x] [Review][Defer] `analytics-panel` effect cleanup captures the mount controller, so a manual-refresh request in flight at unmount isn't aborted [analytics-panel.tsx:66-69] — nil user impact in React 19 (the late `setLive` is a silent no-op; data is correct); reading the ref in cleanup would reintroduce the exhaustive-deps warning just removed.
- [x] [Review][Defer] `portfolios` retry/create double-fetch race (no abort token) — a slow failed mount resolving after a fast successful retry can clobber rows with an error [portfolios/page.tsx] — same class as AC1 but beyond AC5; an AbortController like analytics would close it.
- [x] [Review][Defer] `portfolios` create paths (`createPortfolio`/`createClient`) ignore `r.ok` and have no try/catch — a failed create is silent / can be an unhandled rejection [portfolios/page.tsx:50-68] — pre-existing, out of QH.8's load-path scope.
- [x] [Review][Defer] Palette `setOps`/`setAsyncScreens` have no unmount guard (asymmetric with the benchmarks alive-guard) — React-19 no-op, no navigation/message impact.
- [x] [Review][Defer] Submenu provider that rejects forever re-fetches every open with no in-flight dedupe — rapid ⌘K toggling fires concurrent `load()` for one key, last-resolver-wins [command-palette.tsx submenu loop].

### Dismissed

- AC2 unmount test is near-vacuous in React 19 (no setState-after-unmount warning fires, so it passes without the guard) — already flagged honestly in the completion notes; the guard is correct, the observable assertion just doesn't exist in React 19.
- AC1 test doesn't exercise real network abort (the stub ignores `signal`) — the `signal.aborted` guard logic IS discriminated (without it, stale pid 5 overwrites); true fetch cancellation isn't unit-testable in jsdom.
- AC1/submenu test microtask-flush fragility — passes reliably; negative assertions on a settled tree.
- `portfolios.test` re-stubs fetch after `beforeEach` — works (render is after the re-stub); harmless redundancy.
