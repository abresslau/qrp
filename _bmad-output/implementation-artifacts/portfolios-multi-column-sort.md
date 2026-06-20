# Story: Multi-column sort for the live portfolio grid (Ctrl/Cmd-click)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want to sort the live portfolio grid by more than one column at once by Ctrl-clicking (Cmd on Mac) additional column headers,
so that I can order holdings by a primary key and break ties with a secondary key — e.g. group by **Exchange** and, within each exchange, rank by **Daily P&L** — without losing the first sort when I pick the second.

## Background (what exists today)

The single-column sort shipped in commit `e4fabcf` (`Live pivot: click-to-sort columns`). `components/portfolio-pivot.tsx` holds a single `Sort = { key, dir }` in `useState`, clicking a header calls `onSort(key, defaultDir)` (toggles direction if it's already the active key, else switches to that key with its default direction), and rows are ordered **within each sector group** by `compareHoldings(a, b, sort)`. The active header shows a `▲`/`▼` indicator. This story generalises that one sort into an **ordered list** of sorts driven by the Ctrl/Cmd modifier.

## Acceptance Criteria

1. **Plain click = single sort (unchanged behaviour).** A normal (no-modifier) click on a column header replaces the entire sort with just that column. If that column is *already the sole sort*, the click toggles its direction (preserving today's behaviour). Default direction on a fresh column is unchanged: ascending for text columns (`align="left"`), descending for numeric/range columns (`align="right"`/`"center"`).
2. **Ctrl/Cmd-click = add or toggle a secondary sort.** Holding **Ctrl** (Windows/Linux) or **⌘ Cmd** (macOS) while clicking a header:
   - If the column is **not** already in the sort list → it is **appended** as the next-lower-priority sort (keeping all existing sorts and their order/directions).
   - If the column **is** already in the sort list → its **direction toggles** in place (its priority position is unchanged).
   The modifier is read from the click event as `e.ctrlKey || e.metaKey` (so keyboard activation via Enter/Space with the modifier held works too).
3. **Comparator honours the full ordered list.** Rows are ordered by the first sort key; ties are broken by the second, then the third, and so on. The first non-zero comparison wins; if every key compares equal the original relative order is preserved (stable). Null/missing values still sink to the bottom **per key** (a null on the primary key sorts that row last among its sector regardless of secondary keys). Text keys compare with `localeCompare`, numeric/range keys numerically — exactly as `compareHoldings` does today.
4. **Sorting stays within the sector grouping.** Multi-column sort reorders holdings **within each sector group** only; the sector grouping, the sector subtotal rows, the grand-total row, and the sector ordering (gross weight desc) are all unchanged. The worked example (Exchange primary, Daily P&L secondary) groups rows by exchange and ranks by Daily P&L **inside each sector**.
5. **Priority + direction indicator.** Every column participating in the sort shows its direction arrow (`▲`/`▼`). When **two or more** columns are active, each active header also shows its **1-based priority** (e.g. `Exch ▲ 1`, `Daily P&L ▼ 2`) so the analyst can see which key is primary. A single active sort shows just the arrow (no `1`), matching today's look. `aria-sort` is set on every active header (`ascending`/`descending`), `none` otherwise.
6. **Reset path is obvious.** A plain (no-modifier) click on any header collapses the multi-sort back to a single sort on that column — this is the documented way to clear secondary sorts. (No separate "clear" control is required.)
7. **No regressions.** Default order on first render is still weight-descending (largest positions first), the 2-decimal price formatting, the 52-week range bar, the column alignment (text left / numbers right / range centred), and all existing P&L/return columns render exactly as before. `tsc --noEmit`, `eslint`, and `next build` stay clean.
8. **Tests.** The existing pivot tests stay green. New `@testing-library` interaction tests cover: (a) Ctrl-click adds a secondary sort and the within-sector order reflects primary-then-secondary; (b) Ctrl-click on an already-active column toggles only that column's direction and keeps its priority; (c) a plain click after a multi-sort resets to a single sort; (d) the priority numbers (`1`, `2`) render only when ≥2 sorts are active.

## Tasks / Subtasks

- [x] Task 1: Generalise sort state to an ordered list (AC: #1, #2, #3)
  - [x] Change the component state from `useState<Sort>` to `useState<Sort[]>` (default `[{ key: "weight", dir: "desc" }]`). Keep the `Sort`/`SortDir` types.
  - [x] Rewrite `onSort` to take the modifier: `onSort(key, defaultDir, additive)`. Non-additive → `[{ key, dir }]` (toggle dir iff the list is already exactly `[{key}]`). Additive → if `key` present, map-toggle its `dir` in place; else append `{ key, dir: defaultDir }`. Use immutable updates (`setSorts((prev) => …)`).
  - [x] Generalise `compareHoldings(a, b, sort)` → `compareHoldings(a, b, sorts: Sort[])`: loop the array, return the first non-zero per-key comparison, else `0`. Extracted the existing per-key logic verbatim into `compareByKey` (null-last, string vs number) and loop it.
- [x] Task 2: Wire the modifier through `SortableTh` (AC: #2, #5)
  - [x] `SortableTh` takes `sorts: Sort[]` instead of `sort`. Derives `active` = list contains `sortKey` (`i = findIndex`); `dir` = the matching entry's dir; `priority` = `i + 1`; shown only when `sorts.length > 1`.
  - [x] `onClick={(e) => onSort(sortKey, defaultDir, e.ctrlKey || e.metaKey)}`. No `preventDefault` (keyboard activation preserved); added a `title` hint.
  - [x] Indicator span renders `arrow` when active, plus the priority number when ≥2 sorts. `tabular-nums` keeps the number aligned.
  - [x] Keep `aria-sort` per active header.
- [x] Task 3: Update the call sites + within-sector sort (AC: #4)
  - [x] Pass `sorts` to every `<SortableTh>` (replaced the `sort={sort}` prop via a single replace-all).
  - [x] In the sector `.map`, sort with `compareHoldings(a, b, sorts)`. Sector ordering (`.sort((a, b) => b.wt - a.wt)`) and subtotals unchanged.
- [x] Task 4: Tests (AC: #8)
  - [x] Extended `__tests__/portfolio-pivot.test.tsx`: `fireEvent.click(header, { ctrlKey: true })` / `{ metaKey: true }` to add/toggle a secondary sort; asserts within-sector order under Exch(primary)+Daily-P&L(secondary), the toggle-in-place, plain-click-reset, and priority-number cases. Fixture already had AAPL/INTC both `XNAS` (Exch tie) with differing Daily P&L — no fixture change needed.
- [x] Task 5: Verify (AC: #7)
  - [x] `tsc --noEmit` clean, `eslint` clean (both files), `vitest` 6/6 pivot + 20/20 portfolio suites green, headless render of `/portfolios/1/live` confirms the default `Wt ▼` (single sort, no priority number) and intact alignment. Full production `next build` deferred to avoid clobbering the running dev server's `.next` (would stale the open tab); tsc is the same type-check and the dev server compiles the route cleanly.

## Dev Notes

### Where this fits

This is a **frontend-only** change to one client component and its test — no API, gateway, schema, or contract changes. The grid is `components/portfolio-pivot.tsx`, rendered on `app/portfolios/[id]/live/page.tsx`. The sort runs entirely client-side over the `Composition.holdings` already fetched; nothing new is requested from the API.

### Reuse — do NOT reinvent

- **`compareHoldings` / `sortValue` / `PnlAccess`** already encode the per-column comparison (null-last, string `localeCompare` vs numeric subtract, the `ret:`/`pnl:` key prefixes, `weight` = `Math.abs`). The ONLY change to comparison is wrapping the existing single-key body in a loop over `Sort[]`. Do not duplicate the accessor.
- **`SortableTh`** already renders the header button + arrow slot + `align`/`justify` + default-direction logic (`align === "left" ? "asc" : "desc"`). Extend it; don't rebuild it.
- **`onSort` toggle semantics** for the single-key case must be preserved byte-for-byte so AC#1 holds.

### The current state being modified (read before editing)

`components/portfolio-pivot.tsx` today (commit `e4fabcf`):
- `type Sort = { key: string; dir: SortDir }` — becomes the element type of a `Sort[]`.
- `const [sort, setSort] = useState<Sort>({ key: "weight", dir: "desc" })` → `useState<Sort[]>([{ key: "weight", dir: "desc" }])`.
- `onSort = (key, defaultDir) => setSort((s) => s.key === key ? {…toggle…} : { key, dir: defaultDir })` → add the `additive` branch.
- `compareHoldings(a, b, sort)` is called once in the sector `.map`: `rows.slice().sort((a, b) => compareHoldings(a, b, sorts))`.
- `SortableTh` is rendered ~17 times (Ticker/Name/Country/Exch/Ccy, Wt, Price, the 4 `WINDOWS`, 52-week range, the 3 `PNL_COLS`, Mkt cap, Volume) — all take `sort={sort}` today; switch to `sorts={sorts}`.

### Critical conventions (regressions if violated)

- **`e.metaKey` matters** — macOS users press ⌘, not Ctrl. Gate the additive branch on `e.ctrlKey || e.metaKey`, never Ctrl alone.
- **Stable, immutable state updates** — never mutate the existing `sorts` array (React 19 + the project's `react-hooks` lint). Map/spread to new arrays.
- **Keyboard parity** — the header is a real `<button>`; Enter/Space activation fires a click whose `ctrlKey`/`metaKey` reflect held modifiers, so no extra `onKeyDown` is needed. Do not add `preventDefault`/`stopPropagation` that would break it.
- **Multi-sort is desktop-only by nature** (needs a modifier key) — this is acceptable for the console (a desktop research app). Note it; don't try to add a touch affordance in this story.
- **Sort is within-sector** — the pivot's identity is the sector grouping (AR: sector subtotals + gross-weight sector order). Do not flatten the grid. A flat, ungrouped sortable view would be a *separate* story.
- **Console verification via headless Chrome**, never by asking Andre to look; the dev servers run the API on :8001 and the console on :3000 (`npm run dev`). uvicorn has no `--reload`; web hot-reloads.

### Testing standards

- Vitest + `@testing-library/react` (jsdom), the harness from QH.7. Tests are colocated in `apps/web/__tests__/`.
- The fixture `COMP` in `portfolio-pivot.test.tsx` has Tech (AAPL w0.5, INTC w0.4) + Energy (XOM). For a clean **multi-column** assertion, give two Tech holdings the **same** primary-key value and a differing secondary so the tie-break is observable — e.g. set both AAPL and INTC `mic: "XNAS"` (already the default) and distinct `live_return`, then Ctrl-add Daily P&L as secondary and assert the order flips with its direction. Add a third Tech name if a cleaner primary tie is wanted.
- Use `fireEvent.click(el, { ctrlKey: true })`. Query headers via `getByRole("button", { name: /…/ })`; row order via `getAllByRole("row").map(r => r.textContent)` and index comparisons (the established pattern in the existing sort test).

### Files to touch

- MOD `apps/web/components/portfolio-pivot.tsx` (sort state → array, `onSort` additive branch, `compareHoldings` loop, `SortableTh` props + priority indicator, call sites)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (multi-sort interaction tests)

### References

- [Source: apps/web/components/portfolio-pivot.tsx] — current single-column sort (`Sort`, `sortValue`, `compareHoldings`, `SortableTh`, `onSort`), commit `e4fabcf`.
- [Source: apps/web/__tests__/portfolio-pivot.test.tsx] — existing "sorts holdings within a sector when a column header is clicked" test + the `COMP` fixture.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx] — the live cockpit page that renders `PortfolioPivot`.
- [Source: _bmad-output/implementation-artifacts/portfolios-live-grid-eod-returns.md] — the grid columns this sort operates over.
- [Source: memory feedback_minimize_dev_churn] — verify pages via headless Chrome, not by asking Andre; never `npm --prefix` in this workspace.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- RED first: added the two multi-sort tests against the single-sort code → they failed (no `ctrlKey`
  additive path, no priority numbers), confirming the tests exercise the new behaviour. Then implemented
  → GREEN (6/6).

### Completion Notes List

- **Implemented multi-column sort via Ctrl/Cmd-click.** State generalised from a single `Sort` to an
  ordered `Sort[]` (index 0 = primary). `onSort(key, defaultDir, additive)`: plain click collapses to a
  single sort (toggling direction iff it's already the sole key); Ctrl/Cmd-click appends the column as a
  secondary key, or toggles that key's direction in place if already active. `compareHoldings` now loops
  the list (first non-zero per-key comparison wins; stable for all-equal rows; null-last per key) — the
  per-key body was extracted unchanged into `compareByKey`.
- **Indicator:** every active header shows its `▲`/`▼`; when ≥2 keys sort, each also shows its 1-based
  priority (e.g. `Exch ▲1`, `Daily P&L ▼2`). A single sort shows just the arrow (default render verified:
  `Wt ▼`, no number). `aria-sort` set per active header.
- **Within-sector only:** sorting reorders rows inside each sector group; sector grouping, subtotals, and
  gross-weight sector order are untouched. Worked example verified by test: Exch primary (AAPL/INTC tie on
  XNAS) + Daily P&L secondary breaks the tie, and toggling the secondary flips only that order.
- **macOS + keyboard:** modifier read as `e.ctrlKey || e.metaKey`; no `preventDefault`, so Enter/Space
  keyboard activation (with modifier held) works too.
- **Verification:** `tsc --noEmit` clean; `eslint` clean (component + test); `vitest` 6/6 pivot + 20/20
  across all portfolio suites (no regressions); headless render of `/portfolios/1/live` confirms the
  default state + alignment. Full production `next build` deferred (see Task 5) to protect the running dev
  server's `.next`; tsc covers the type compile and the dev server serves the route cleanly (200).
- **Open questions left at the AC defaults:** Ctrl-click toggles direction (no cycle-to-remove); sort is
  in-memory (not persisted); priority numbers show only for ≥2 keys. Flagged for Andre, not blocking.

### File List

- MOD `apps/web/components/portfolio-pivot.tsx` (sort state → `Sort[]`, `onSort` additive branch, `compareByKey` + looped `compareHoldings`, `SortableTh` priority indicator + modifier click, call sites)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (two multi-sort interaction tests)

## Open Questions (for Andre — do not block implementation)

1. **Ctrl-click cycle: toggle vs. remove.** Default spec is: Ctrl-click on an active column **toggles its direction** (and a plain click anywhere resets to single). A common alternative is a 3-state cycle on Ctrl-click: asc → desc → **remove from the sort**. Say if you'd prefer the cycle-to-remove behaviour for dropping a secondary key without resetting everything.
2. **Persist the sort?** The sort resets on reload/navigation (component state). If you want it to survive (e.g. URL query param or localStorage per portfolio), that's a small add-on — flag it.
3. **Priority display.** Default shows a small `1`/`2`/… next to the arrow only when ≥2 sorts are active. If you'd rather always show the number (even for a single sort) or use a different marker, easy to change.

## Review Findings (code-review 2026-06-20)

3 adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). All 8 ACs + critical
conventions verified met. No Critical/High; state machine, comparator (first-non-zero, stable,
null-last per key), immutability, and 1-based priority all confirmed correct. 1 decision, 2 patches.

- [x] [Review][Decision→Accepted] Plain-click on a column already in a multi-sort resets it to the default direction (RESOLVED: Decision 1 → keep current) — Andre chose the predictable "fresh single sort at default" semantics; no change. Spec-compliant (AC#6 collapse + AC#1 sole-sort toggle), documented in-comment.
- [x] [Review][Patch] Arrow and priority number render with no separator [apps/web/components/portfolio-pivot.tsx] (FIXED 2026-06-20) — indicator now renders `{arrow}{priority ? ` ${priority}` : ""}` → `▼ 2`, matching the spec's `Daily P&L ▼ 2` format; single sort still shows just the arrow.
- [x] [Review][Patch] AC8(b) "keeps its priority" only asserted indirectly [apps/web/__tests__/portfolio-pivot.test.tsx] (FIXED 2026-06-20) — the metaKey-toggle test now asserts the secondary header still shows `2` after the in-place direction toggle.

Dismissed (4): `next build` literal gate deferred (intentional, documented, `feedback_minimize_dev_churn`-sanctioned — tsc + dev-server route compile substitute); the `title` hint is untested (none required); the single-sort test's `not.toMatch(/\d/)` over the whole header textContent is slightly broad but safe ("Ticker" has no digit); ~11 edge cases (empty sorts unreachable, duplicate-append guarded by findIndex, mixed string/number per key impossible, keyboard-modifier parity, sort persists across `data` change, no cross-sector leak) all verified handled.

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: multi-column sort for the live portfolio grid via Ctrl/Cmd-click — generalise the single `Sort` into an ordered `Sort[]`, additive modifier branch in `onSort`, looped `compareHoldings`, priority+direction indicators; within-sector grouping preserved. Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): `Sort[]` state + additive `onSort` + looped `compareHoldings`/`compareByKey` + `SortableTh` priority indicator (Ctrl/Cmd-click). 2 new interaction tests; 6/6 pivot + 20/20 portfolio tests green; tsc + eslint clean; headless render verified. Status → review. |
| 2026-06-20 | Code-review (3 adversarial layers): all 8 ACs met, no Critical/High. Decision 1 → keep "fresh single sort at default" (no change). 2 patches applied: indicator separator (`▼ 2`), explicit priority-kept test assertion. 6/6 pivot tests green, tsc + eslint clean. Status → done. |
