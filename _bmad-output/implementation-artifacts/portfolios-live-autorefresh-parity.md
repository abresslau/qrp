# Story: Portfolio live cockpit — auto-refresh parity with the WEI / FX live boards

Status: review

<!-- Created via bmad-create-story 2026-06-22 (Andre: "review the portfolio live page so it's like
wei and fx pages"). The WEI (`/monitor/wei`) and FX (`/monitor/fx`) live boards both poll-auto-refresh
(an `autoSec` interval, `useOnline`-paused, with a `refreshed HH:MM:SS` stamp), mirroring the QH.9
`heatmap-view`. The portfolio live cockpit (`/portfolios/[id]/live`) has only a MANUAL ↻ — it never got
the auto-refresh. This brings it to parity. -->

## Story

As a portfolio manager watching a book intraday,
I want the **live cockpit to auto-refresh on an interval** (like the WEI and FX live boards),
so that the heat map, donut, movers, grid and P&L keep updating on their own without me clicking ↻ —
and I get a visible "refreshed" confirmation each tick.

## Background / current state (read before coding)

- **The target is the cockpit `apps/web/app/portfolios/[id]/live/page.tsx`** — NOT the Monitor launcher
  `apps/web/app/monitor/portfolio-live/page.tsx` (that's just a list of books linking to each cockpit;
  leave it). The cockpit fetches `/api/analytics/portfolios/{id}/composition` once (feeds the donut, heat
  map, movers, pivot, and the P&L strip), with a newest-wins `AbortController` and a `nonce` that a
  **manual ↻ refresh** button bumps. It already shows a freshness badge (`FRESH_STYLE` pill +
  `n_priced/n_holdings priced · as of … · not stored`) and "refreshing" while loading. Composition is
  fetched at view time, **never persisted**.
- **What it LACKS vs WEI/FX (the gap to close):** no auto-refresh interval, no `refreshedAt` stamp, no
  `useOnline` pause. The manual ↻ is the only way to update.
- **The canonical auto-refresh pattern to mirror (copy it, don't reinvent):**
  - `apps/web/components/heatmap-view.tsx` (the QH.9 origin) — `autoSec` state (`useState(0)`), a
    `refreshedAt` stamp, `const online = useOnline()`, and the effect:
    ```
    useEffect(() => {
      if (win !== LIVE || autoSec <= 0 || !online) return;
      const id = setInterval(() => setNonce((n) => n + 1), Math.max(3, autoSec) * 1000);
      return () => clearInterval(id);
    }, [win, autoSec, online]);
    ```
    plus the `auto [input] s (every Ns)` control and the `· refreshed ${refreshedAt}` suffix on the badge.
  - `apps/web/app/monitor/wei/page.tsx` + `apps/web/app/monitor/fx/page.tsx` — the same `autoSec` /
    `refreshedAt` / `useOnline` trio I just shipped; identical control markup. (`refreshedAt` is the
    LOCAL clock stamped on each settle so an auto-tick shows visible confirmation even when the sim-clock
    `as_of` doesn't move.)
  - `useOnline` is `apps/web/lib/connection.ts` — the sidebar offline toggle; when offline, all live
    polling pauses. The cockpit must respect it like every other live surface.
- **Two things that DON'T port from WEI/FX (do not add them):**
  1. **No EOD/LIVE toggle.** WEI/FX put an EOD board and a LIVE board behind one toggle. The portfolio
     cockpit is *inherently* the live view; the EOD/static equivalent is the separate `/portfolios/[id]`
     page. There is no "EOD composition" mode here — do NOT add a toggle.
  2. **Keep the `FRESH_STYLE` pill badge.** The cockpit's badge already matches the sibling
     `heatmap-view` + analytics-panel idiom (a coloured pill). WEI/FX use a `LIVE_TONE` *text* colour
     because they're dense tables — that's the outlier, not the standard. Do NOT convert the cockpit to
     `LIVE_TONE`; just ADD the `refreshed` suffix to the existing badge.
- **Env note:** live quotes read `delayed` in this sim environment (sim-clock vs Yahoo's real
  timestamp); the data still updates each refresh. The auto-refresh's `refreshedAt` stamp is exactly what
  makes that visible. Documented in `wei-live-board` / `fx-matrix-live` / QH.2.

## Acceptance Criteria

1. **Auto-refresh control.** The cockpit gains an `auto [number] s` input next to the ↻ refresh button,
   mirroring `heatmap-view`/WEI/FX exactly: blank/0 = off (the default), floored at 3s, shows
   `(every Ns)` when set. Setting a positive interval polls the live composition on that cadence by
   bumping the existing `nonce` (re-using the current fetch effect — no second fetch path).
2. **`useOnline`-paused.** While the sidebar shows offline, the auto-refresh timer is paused (same
   `useOnline` gate as `heatmap-view`/WEI/FX); flipping back online resumes it. The interval is cleared on
   unmount / when the interval or online state changes (effect cleanup).
3. **`refreshed HH:MM:SS` stamp.** Each successful (non-aborted) composition settle stamps the local clock
   into a `refreshedAt`, appended to the freshness badge line (`… · refreshed 15:01:49 · not stored`),
   so an auto-tick gives visible confirmation even when the data's own `as_of` (sim-clock) doesn't move.
4. **set-state-in-effect safe.** The interval callback (`setNonce`) lives in the timer, not the effect
   body (the `react-hooks/set-state-in-effect` rule the project enforces). No new dependency; SSR-safe;
   the existing newest-wins `AbortController` composition fetch is unchanged.
5. **Manual ↻ + badge preserved.** The manual ↻ refresh button still works (and is the only control
   when auto is off). The `FRESH_STYLE` pill badge, `n_priced/n_holdings priced`, `as of …`, "refreshing"
   state, P&L strip, donut, movers, heat map, and pivot are all unchanged except for the appended
   `refreshed` suffix. NO EOD/LIVE toggle is added.
6. **No regression.** `/portfolios/[id]/live`, the composition fetch, the `/monitor/portfolio-live`
   launcher, and the analytics composition endpoint are unaffected. `tsc`/`eslint`/`vitest` clean.
7. **Tests.** Extend `apps/web/__tests__/portfolio-live.test.tsx`: (a) the auto control is present, defaults
   to off (blank), floors at 3s, and shows `(every Ns)`; (b) the badge renders the `refreshed` suffix after
   a load; (c) the manual ↻ still triggers a re-fetch. (Use a deterministic control/render assertion;
   don't rely on real wall-clock interval timing in the test.)

## Tasks / Subtasks

- [x] Task 1: Add the auto-refresh state + effect to the cockpit (AC: #1, #2, #4) — added `autoSec`
  (`useState(0)`), `refreshedAt` (`useState<string|null>(null)`), `const online = useOnline()`; a
  `useEffect` that, while `autoSec > 0 && online`, `setInterval(() => setNonce(n => n+1), Math.max(3,
  autoSec) * 1000)` with `clearInterval` cleanup and deps `[autoSec, online]`. Copied from
  `heatmap-view.tsx`/`monitor/fx/page.tsx`.
- [x] Task 2: Stamp `refreshedAt` on settle + render it (AC: #3) — `setRefreshedAt(new
  Date().toLocaleTimeString())` in the composition fetch's success branch (guarded by
  `!ac.signal.aborted`); appended `${refreshedAt ? \` · refreshed ${refreshedAt}\` : ""}` to the badge
  line before "· not stored".
- [x] Task 3: Add the `auto … s` control to the header button row (AC: #1, #5) — added the labelled
  `<input type="number" min={0}>` (`aria-label="Auto-refresh interval in seconds"`, `(every Ns)` suffix)
  beside the ↻ refresh button; ↻ + the `FRESH_STYLE` pill badge intact; no toggle.
- [x] Task 4: Tests + verify (AC: #6, #7) — extended `portfolio-live.test.tsx` (auto control present +
  off-by-default + 3s floor + `refreshed` suffix + manual ↻ re-fetch). tsc/eslint clean; web 138 green
  (5 in this file). Real-Chrome CDP on `/portfolios/5/live`: auto=3s → "every 3s", the `refreshed` stamp
  advanced 15:29:04 → 15:29:14 over ~2 ticks; control + badge + cockpit render correctly (screenshot).

## Dev Notes

### Critical conventions (regressions if violated)
- **Copy the proven pattern; don't reinvent.** The `autoSec`/`refreshedAt`/`useOnline` trio + the control
  markup already exist verbatim in `heatmap-view.tsx`, `monitor/wei/page.tsx`, `monitor/fx/page.tsx`.
  Use the same names, the same 3s floor, the same effect deps.
- **`setNonce` in the timer callback, not the effect body** — the `react-hooks/set-state-in-effect` rule
  (the one WEI/FX/heatmap all comply with). Floored at 3s to stay polite.
- **Composition is never persisted** — it's a live view-time read; this story only changes *when* it
  re-fetches, not what it stores.
- **Do NOT add an EOD/LIVE toggle** and **do NOT switch the badge to `LIVE_TONE`** — see Background. The
  cockpit's pill badge already matches the `heatmap-view`/analytics-panel idiom; keep it.
- **Honest freshness preserved** — the badge keeps showing `freshness` + `n_priced/n_holdings priced`; the
  sim-env `delayed` read is expected ([[feedback_freshness_per_market]]). No new dependency; SSR-safe;
  newest-wins `AbortController` unchanged ([[feedback_minimize_dev_churn]]).

### References
- [Source: apps/web/app/portfolios/[id]/live/page.tsx] — the cockpit (add auto-refresh here); current manual ↻ + `FRESH_STYLE` badge + the composition fetch effect (deps `[id, nonce]`).
- [Source: apps/web/components/heatmap-view.tsx] — the canonical `autoSec`/`refreshedAt`/`useOnline` auto-refresh + control markup + the `· refreshed …` badge suffix (QH.9 origin).
- [Source: apps/web/app/monitor/fx/page.tsx + monitor/wei/page.tsx] — the same trio as just shipped (`fx-matrix-live`, `wei-live-board`); identical control.
- [Source: apps/web/lib/connection.ts] — `useOnline` (the sidebar offline pause).
- [Source: apps/web/__tests__/portfolio-live.test.tsx] — the existing cockpit test to extend.
- Sibling stories: `wei-live-board`, `fx-matrix-live` (the auto-refresh they added), `portfolios-live-header-pnl-declutter` (the cockpit's current layout).

## Open Questions (for Andre — defaults chosen, do not block)
1. **Scope = the cockpit, not the launcher.** I read "the portfolio live page" as the per-book cockpit
   `/portfolios/[id]/live` (the one with live data + a refresh button). The `/monitor/portfolio-live`
   launcher stays a plain list. Say if you actually wanted a new multi-book live *board* there (bigger,
   separate story).
2. **No EOD/LIVE toggle + keep the pill badge** — the two WEI/FX elements that don't fit the cockpit
   (it's inherently live; its badge already matches `heatmap-view`). Flag if you want them anyway.
3. **Auto-refresh default = off** (blank, 3s floor), matching every other live surface. Keep, or default
   it on at some interval for the cockpit?

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes
- A small, faithful port of the proven `heatmap-view`/WEI/FX trio (`autoSec` + `refreshedAt` + `useOnline`)
  onto the cockpit — no new dependency, ~20 lines. The auto-refresh re-uses the existing `nonce`-driven
  composition fetch (a second effect bumps `nonce` on the timer), so there's one fetch path, newest-wins
  `AbortController` unchanged.
- Held the two scope lines from the story: **no EOD/LIVE toggle** (the cockpit is inherently live; the
  static view is `/portfolios/[id]`) and **kept the `FRESH_STYLE` pill badge** (it already matches the
  `heatmap-view`/analytics-panel idiom — WEI/FX's `LIVE_TONE` text is the table-only outlier). The only
  badge change is the appended `· refreshed HH:MM:SS` suffix.
- Tests assert the control + the `refreshed` suffix + the manual re-fetch deterministically (no fake
  timers); the actual interval firing is CDP-verified (the stamp advanced over two 3s ticks).

### File List
- `apps/web/app/portfolios/[id]/live/page.tsx` (modified — `useOnline` import, `autoSec`/`refreshedAt` state, auto-refresh effect, `refreshed` badge suffix, `auto … s` control)
- `apps/web/__tests__/portfolio-live.test.tsx` (modified — auto control off-by-default/3s-floor + refreshed-suffix + manual ↻ re-fetch tests)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story, Andre: "review the portfolio live page so it's like wei and fx pages"). Bring the portfolio live cockpit (`/portfolios/[id]/live`) to auto-refresh parity with the WEI/FX live boards: add the `autoSec` interval control (3s floor, off by default, `useOnline`-paused) + a `refreshed HH:MM:SS` stamp on the freshness badge, mirroring `heatmap-view`/WEI/FX. Keep the manual ↻ + the `FRESH_STYLE` pill badge; add NO EOD/LIVE toggle (the cockpit is inherently live). Status → ready-for-dev. |
| 2026-06-22 | Dev complete → review. Ported the `autoSec`/`refreshedAt`/`useOnline` trio onto the cockpit (auto-refresh effect bumps the existing `nonce`; `refreshed HH:MM:SS` appended to the badge; `auto … s` control beside ↻). No toggle, kept the `FRESH_STYLE` pill. 138 web tests green (5 in `portfolio-live.test.tsx`); tsc/eslint clean. Real-Chrome CDP on `/portfolios/5/live`: auto=3s → "every 3s", `refreshed` stamp advanced over ~2 ticks. Status → review. |
