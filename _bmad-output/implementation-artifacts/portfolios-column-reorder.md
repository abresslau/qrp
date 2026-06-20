# Story: Drag-to-reorder columns in the live portfolio grid

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want to drag a column header left or right to reorder the columns in the live portfolio grid,
so that I can put the columns I care about (e.g. Daily P&L next to Ticker) side by side without scrolling past the ones I don't.

## Background (what exists today)

`apps/web/components/portfolio-pivot.tsx` renders the grid with columns in a **fixed, hard-coded order**, written out positionally in **four** places:

1. **Header row** — 17 `<SortableTh>` elements in source order (Ticker, Name, Country, Exch, Ccy, Wt, Price, 1D/1M/3M/6M, 52-week range, Daily/MTD/YTD P&L, Mkt cap, Volume).
2. **Stock rows** (`SectorGroup`) — 17 `<td>` in the *same* positional order.
3. **Grand-total row** — uses **`colSpan`** blocks: `colSpan={5}` "Total · N holdings", a weight cell, `colSpan={6}` blank (Price→52-week range), 3 P&L cells, `colSpan={2}` blank (Mkt cap+Volume).
4. **Sector-subtotal row** (`SectorGroup`) — the same `colSpan={5}` / weight / `colSpan={6}` / 3×P&L / `colSpan={2}` shape.

The header already supports click-to-sort + Ctrl/Cmd multi-sort (commit `c21ca18`). **The columns are not data-driven** — so reordering is impossible until a single ordered column model drives all four row types. The `colSpan` aggregate rows are the main obstacle: their contiguous spans (text block, the two blank blocks) only make sense in the current order and break under any permutation.

## Acceptance Criteria

1. **Drag a header to reorder.** Dragging a column header and dropping it on another header moves the dragged column to the drop target's position; every other column keeps its relative order. The header, the stock-row cells, the grand-total row, and the sector-subtotal rows **all** reflect the new order consistently (no column's header and body cells ever diverge).
2. **Drag-and-drop with no new dependency.** **AMENDED 2026-06-20 (during dev):** implemented with **Pointer Events** (`onPointerDown` on the header → window `pointermove`/`pointerup`), NOT the native HTML5 Drag-and-Drop API. Rationale: native `draggable` does not reliably start a drag from inside the header's `<button>` in Chrome (the button absorbs the gesture) — confirmed live by the user ("hand cursor shows but drop does nothing / frozen"), and jsdom's `fireEvent.dragStart` had masked it in tests. Pointer Events work regardless of the button and distinguish click (sort) from drag (reorder) by a 5px movement threshold. Still **no DnD package** added (`@dnd-kit`/`react-dnd`/`react-beautiful-dnd`/`sortablejs` all avoided).
3. **Drag and click-to-sort coexist.** A plain click on a header still sorts (single / Ctrl-Cmd multi-sort — unchanged). A drag reorders. Because a native drag suppresses the subsequent `click`, the existing sort button keeps working for clicks while the header is also draggable. The header shows a grab affordance (`cursor-grab`, `cursor-grabbing` while dragging).
3. **Drop-target feedback.** While dragging, the prospective drop target is visually indicated (e.g. a left/right insertion border or highlight on the hovered header), and the dragged header is visually de-emphasised; feedback clears on drop/dragend/drag-leave.
4. **Aggregate rows decomposed to per-column cells.** The grand-total and sector-subtotal rows no longer use positional `colSpan` blocks. Each column renders its own total/subtotal cell — the **weight** column renders the weight %, the three **P&L** columns render their P&L totals, every other column renders an empty cell — so the totals land under the correct columns after any reorder. The row **label** ("Total · N holdings" / "SECTOR · n") still reads as a left-aligned heading: it spans from the leftmost column up to (but not including) the first aggregated (weight/P&L) column in the **current** order via a computed `colSpan` (preserving today's look in the default order); if an aggregated column is dragged to the first position, the label falls back to its own single leading cell.
5. **Within-sector grouping + sort untouched.** Reordering changes only column order. Sector grouping, sector ordering (gross weight desc), subtotal/total math, the active sort (`sorts[]`) and its indicators, the 52-week range bar, 2-dp currency formatting, and per-type alignment (text left / numeric right / range centre) are all preserved and travel with their column.
6. **Order is component state (in-memory).** Column order is React state initialised to the canonical default order; it persists across re-renders and `data` prop changes within the session, and resets on reload/navigation. (Persistence across reloads is an explicit non-goal here — see Open Questions.)
7. **No regressions.** First render shows the canonical order identical to today; all existing pivot behaviour (sort, P&L, returns, range bar, empty state) works. `tsc --noEmit`, `eslint`, and the pivot/portfolio vitest suites stay green.
8. **Tests.** `@testing-library` tests: (a) a simulated drag (`dragStart` on column A, `drop` on column B) reorders both the header and the stock-row cells consistently; (b) after a reorder, an aggregated value (weight % or a P&L total) still appears under its column in the subtotal/total row; (c) a plain header click still sorts after the drag machinery is added (no regression); (d) default order on first render matches today.

## Tasks / Subtasks

- [x] Task 1: Introduce a single column-descriptor model (AC: #1, #4, #5)
  - [x] Defined a `COLUMNS` registry (array of `{ id, label, align, cell(h) }`) reusing the sort keys as ids (`ticker`/`name`/…/`range`/`pnl:*`/`mcap`/`volume`); `cell(h)` returns the full keyed `<td>` so per-column classes + `retClass` coloring stay intact. `WINDOWS`/`PNL_COLS` are spread into the registry; they remain only for the subtotal/total math loops. Added `subtotalCell`/`totalCell` helpers (value for weight/P&L, empty `<td>` otherwise) + `DEFAULT_COLUMN_ORDER`/`COLUMN_BY_ID`/`isAggCol`.
  - [x] The descriptor `id` is the `sortKey`; `align` drives both header and cell alignment.
- [x] Task 2: Column-order state + drag-reorder (AC: #1, #2, #3)
  - [x] `const [order, setOrder] = useState<string[]>(DEFAULT_COLUMN_ORDER)`. Header + grand-total + sector-subtotal + stock rows all map the same `order`.
  - [x] **Pointer-events** drag on each `SortableTh` `<th>` (amended from native DnD — see AC#2): `onPointerDown` records id + startX in a ref and attaches window `pointermove`/`pointerup`; a 5px move starts the drag (`draggingId`), the drop target is the `th[data-col-id]` under the pointer, `pointerup` does an immutable move (filter dragged, splice before target). Drop-target shows a left border (`border-l-2 border-fg/70`), dragged header dims (`opacity-40`), `select-none` avoids text selection.
  - [x] The inner sort `<button>` click still fires for non-drag clicks (no `preventDefault`/`stopPropagation` on the click path); `cursor-grab` affordance on the header.
- [x] Task 3: Decompose the colSpan aggregate rows (AC: #4)
  - [x] Grand-total + sector-subtotal rows now map `order` → per-column cells; the label spans `labelSpan(order)` = index of the first aggregated column (fallback 1 if an agg column is first). Same label text + `retClass` coloring + py padding preserved.
- [x] Task 4: Tests (AC: #8)
  - [x] Extended `portfolio-pivot.test.tsx` with 4 tests: drag Volume→Ticker reorders header AND the stock-row cells in sync; an aggregate (weight 120.0% + Daily P&L +3.30%) still renders after moving Wt; a plain header click still sorts; default order on first render is canonical. `dataTransfer` stubbed (the reorder reads the dragged id from a ref, not `getData`).
- [x] Task 5: Verify (AC: #7)
  - [x] `tsc --noEmit` clean; `eslint` clean (component + test); `vitest` 10/10 pivot + 24/24 across all portfolio suites; headless render of `/portfolios/1/live` confirms the default order + grand-total/subtotal layout are pixel-identical to pre-refactor. Full production `next build` deferred (would clobber the running dev server's `.next` and stale the open tab — `feedback_minimize_dev_churn`); tsc is the same type-check and the dev server compiles the route cleanly.

## Dev Notes

### Where this fits

Frontend-only, one client component (`components/portfolio-pivot.tsx`) + its test, rendered on `app/portfolios/[id]/live/page.tsx`. No API/gateway/contract/schema changes. This builds directly on the sort work (commits `e4fabcf`, `c21ca18`) — **keep that intact**.

### The core risk — read the current component first

The component renders columns positionally in four row types (header, stock row, grand-total, sector-subtotal) and the two aggregate rows use `colSpan={5}`/`{6}`/`{2}`. **A naive "reorder the header only" change will desync the header from the body and corrupt the colSpan rows.** The required shape is: one ordered list of column ids → one descriptor registry → every row maps the same order. The colSpan rows must become per-column cells (Task 3). Read `portfolio-pivot.tsx:175-346` end-to-end before editing; in particular:
- Grand-total row `:252-266` (colSpan 5 / weight / colSpan 6 / 3×PNL / colSpan 2).
- Sector-subtotal row `:295-311` (same shape).
- Stock row `:312-342` (Ticker, Name [`max-w-[16rem] truncate`], Country, Exch, Ccy, Wt, Price, 4×WINDOWS, RangeBar, 3×PNL, Mkt cap, Volume).
- Header `:228-247` (the `SortableTh` list — already takes `align`/`sortKey`/`sorts`/`onSort`).

### Reuse — do NOT reinvent

- **`SortableTh`** already encodes header click-to-sort, alignment, arrows, and the multi-sort priority indicator. Add `draggable` + the drag handlers to it (or its `<th>`), passing the column `id` and reorder callbacks. Do not fork it.
- **`compareHoldings` / `sorts` / `onSort`** are independent of column order — leave them as-is; reordering must not touch sort state.
- **`pnlOf`, `retClass`, `wpct`, `pct`, `fmtPrice`, `fmtCompact`, `RangeBar`** — reuse verbatim inside the descriptor `cell`/`subtotal`/`total` render fns.
- **`WINDOWS` / `PNL_COLS`** drive the subtotal/total math loops (`pnls[win]`, `totalPnls[win]`) — keep those; only the *rendering* moves into the registry.

### Native HTML5 DnD specifics (the gotchas)

- `onDragOver` **must** `e.preventDefault()` on a valid target, else `onDrop` never fires (the #1 native-DnD mistake).
- A completed drag does **not** emit a `click`, so the sort button and the drag can share the same header without a mode toggle. Don't add `preventDefault` to the click path.
- Use `e.dataTransfer.setData("text/plain", id)` for Firefox (some browsers require data set to start a drag) and read it on drop; also keep the dragged id in a ref for robustness.
- Drop-target feedback via state (hovered id + side); clear on `dragend`/`drop`/`dragleave`.
- Accessibility: native DnD is pointer-only. This is acceptable for the desktop console (the multi-sort feature is likewise modifier/desktop-centric). A keyboard/menu reorder is an Open Question, not in scope.

### Testing standards

- Vitest + `@testing-library/react` (jsdom) — harness from QH.7, tests colocated in `apps/web/__tests__/`. The fixture `COMP` (Tech: AAPL/INTC, Energy: XOM) is sufficient.
- jsdom supports `fireEvent.dragStart/dragOver/drop`, but `DataTransfer` is not implemented — pass a stub: `fireEvent.dragStart(th, { dataTransfer: { setData: () => {}, getData: () => "<id>", effectAllowed: "" } })` (or store the dragged id in component state/ref so the test doesn't depend on `getData`). Verify header order via `getAllByRole("columnheader").map(th => th.textContent)` and body order via the first stock row's `querySelectorAll("td")`.
- Keep the existing 6 pivot tests green (sort behaviour must not regress).

### Critical conventions (regressions if violated)

- **No new dependency** — native DnD only (this codebase is dependency-cautious; `npm --prefix` once broke lightningcss — see memory `feedback_minimize_dev_churn`).
- **Immutable state** — reorder produces a new `order` array (no in-place splice on state); React 19 + the project's `react-hooks` lint.
- **Header/body never diverge** — both must map the *same* `order`. This is the whole point; a test asserts it.
- **Sort untouched** — column order and sort order are orthogonal states.
- **Verify via headless Chrome**, never by asking Andre. Dev servers: API `:8001`, console `:3000` (`npm run dev`); uvicorn has no `--reload`, web hot-reloads.
- **Windows/console** is irrelevant here (frontend), but keep new strings ASCII-safe in any CLI-adjacent output (none expected).

### Files to touch

- MOD `apps/web/components/portfolio-pivot.tsx` (column-descriptor registry, `order` state + native DnD on `SortableTh`, decomposed aggregate rows)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (drag-reorder tests)

### References

- [Source: apps/web/components/portfolio-pivot.tsx] — the four positional row renderers + `colSpan` aggregate rows + `SortableTh` (commit `c21ca18`).
- [Source: apps/web/__tests__/portfolio-pivot.test.tsx] — existing sort tests + the `COMP` fixture + the `getAllByRole("row")`/`querySelectorAll("td")` assertion patterns.
- [Source: _bmad-output/implementation-artifacts/portfolios-multi-column-sort.md] — the sort model this must leave intact.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx] — the live cockpit page rendering `PortfolioPivot`.
- [Source: memory feedback_minimize_dev_churn] — no new deps casually; verify via headless Chrome, not by asking Andre.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- RED first: the two drag-dependent tests failed against the positional render (drag was a no-op); the
  default-order + sort tests passed pre-implementation. After the refactor all 10 passed.
- One test assertion was initially wrong (expected total weight `100.0%`) — the fixture's `total_weight`
  is `1.2` → `120.0%`. The code was correct; fixed the assertion (the `100.0%` seen in screenshots is
  real portfolio-1 data, not the unit fixture).
- **Native HTML5 DnD failed in the real browser** (user report: grab cursor but drop did nothing) even
  though jsdom `fireEvent.dragStart` made the tests green — the classic "button-absorbs-drag" gap.
  Rewrote to **Pointer Events** (pointerdown on the `<th>` → window pointermove/pointerup, 5px threshold,
  drop target via `event.target.closest("th[data-col-id]")`). Tests switched to `fireEvent.pointerDown/
  Move/Up`; the `e.button > 0` guard (not `!== 0`) lets jsdom's button-less synthetic event through.
- **Verified for real in headless Chrome over CDP** (`Input.dispatchMouseEvent` press→move→release on the
  Volume header dropped onto Ticker): order went `[ticker,…,volume]` → `[volume,ticker,…]`. PASS.

### Completion Notes List

- **Refactored to a single column-descriptor model.** A module-level `COLUMNS` registry (id/label/align/
  `cell`) is now the one source of column identity + default order. The header, grand-total row, sector-
  subtotal rows, and stock rows **all** render by mapping the same `order: string[]` state, so header and
  body can never diverge (a test asserts this).
- **The colSpan aggregate rows were decomposed** into per-column cells (`subtotalCell`/`totalCell`: value
  for weight + the three P&L columns, empty `<td>` otherwise). The row label spans `labelSpan(order)` =
  the leading run of non-aggregated columns (default 5 = Ticker..Ccy, identical to before); if an
  aggregated column is dragged to the front it falls back to a single leading cell. This is what makes
  reordering correct across all four row types — the old positional `colSpan={5}/{6}/{2}` could not.
- **Pointer-events drag, no new dependency** (amended from native HTML5 DnD, which didn't fire from
  inside the header `<button>` in real Chrome). `onPointerDown` on the `<th>` → window `pointermove`/
  `pointerup`; a 5px movement threshold starts the drag; the drop target is the header under the pointer;
  `pointerup` does an immutable move (filter dragged, splice before target). `cursor-grab`/`select-none`
  affordances; drop target left-bordered, dragged header dimmed. **No DnD package added.**
- **Coexists with click-to-sort** (commits `e4fabcf`/`c21ca18`, left intact): a real drag (≥5px) sets a
  `suppressClickRef` so the trailing click doesn't sort; a press without movement falls through to the
  sort handler. `metaKey`/multi-sort all preserved.
- **Verified in a real browser, not just jsdom:** a CDP-driven mouse drag in headless Chrome moved the
  Volume header to the first column (`["volume","ticker",…]`). This caught what the green jsdom tests
  had masked.
- **In-memory order** (resets on reload) per the AC default; sort state is orthogonal and untouched.
- **Verification:** tsc + eslint clean; 10/10 pivot + 24/24 portfolio tests; headless render shows the
  default order + aggregate layout pixel-identical to pre-refactor (the decomposition is behaviour-
  preserving at the default order). Drag behaviour proven by the 4 interaction tests. Full `next build`
  deferred to protect the running dev server (see Task 5).
- **Open questions left at AC defaults:** in-memory (no persistence), no reset button, all columns
  draggable (Ticker not pinned), no column show/hide, pointer-only (no keyboard reorder). Flagged for
  Andre, not blocking.

### File List

- MOD `apps/web/components/portfolio-pivot.tsx` (column registry + `order` state + native DnD on `SortableTh` + decomposed aggregate rows + `SectorGroup` order-driven render)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (4 drag-reorder / default-order tests)

## Open Questions (for Andre — do not block implementation)

1. **Persist the column order?** Default is in-memory (resets on reload). A per-portfolio (or global) persistence via `localStorage` is a small add-on — flag if you want it to stick. (Pairs with the same open question on the multi-sort story.)
2. **Reset-to-default affordance.** Once columns are reordered there's no obvious way back except reload. Want a small "reset columns" link/button in the grid header?
3. **Pin identity columns?** Should Ticker (and/or Name) be locked as non-draggable / always-first so the row is always identifiable, or is everything freely reorderable (current default)?
4. **Column show/hide.** Reordering naturally invites hiding columns too (a column chooser). Out of scope here; flag if you want it as a follow-up.
5. **Keyboard/accessible reorder.** Native DnD is pointer-only. If keyboard reorder matters, it needs a menu ("move left/right") or a DnD lib — a separate story.

## Review Findings (code-review 2026-06-20)

3 adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor) on commit `0b1f17b`. All 8 ACs
+ critical conventions verified met (incl. amended AC#2 Pointer Events, no DnD dep). No correctness bugs;
the reorder math, labelSpan/colSpan decomposition (incl. agg-column-first fallback), immutable moves,
header/body sync, and sort coexistence are all correct. 1 decision, 3 patches, 4 dismissed.

- [x] [Review][Decision→Accepted] Reorder is insert-*before*-target, so a column can't be moved to the LAST slot (RESOLVED: Decision 1 → accept insert-before-only) — Andre chose to keep the simple insert-before model; no change. Drag-past-last to make a column last is a possible future refinement (right-half drop detection).
- [x] [Review][Patch] Window `pointermove`/`pointerup` listeners leak on unmount-mid-drag; no `pointercancel` (FIXED 2026-06-20) — `onColPointerDown` now stores a `teardown()` in `dragCleanupRef`, removes all three listeners (added `pointercancel`) on every release/cancel path, and a `useEffect(() => () => dragCleanupRef.current?.(), [])` tears down on unmount mid-drag. Real-Chrome CDP drag re-verified PASS after the refactor.
- [x] [Review][Patch] `COLUMN_BY_ID[id]` dereferenced without an undefined guard (FIXED 2026-06-20) — header map does `if (!col) return null`; body map uses `COLUMN_BY_ID[id]?.cell(h) ?? null`. Guards a table-wide crash from a stale order id.
- [x] [Review][Patch] `pnlOf`/`PnlAccess` byte-identical duplicates (FIXED 2026-06-20) — removed the in-component `pnlOf`; the subtotal/total math now uses the module-level `PnlAccess` (single source of the FX-hedged formula).

Dismissed (4): `suppressClickRef` same-tick window (self-correcting via `setTimeout(0)`; the only click after `pointerup` in the same task is the drag's own compatibility click — user sort clicks are separate tasks → practically unreachable); one-dimensional (clientX-only) drag threshold (intentional — columns move horizontally); `e.button > 0` relying on `undefined > 0 === false` (works, documented); + ~10 verified-handled edge cases (plain click / sub-threshold / non-header & same-column drop / non-left button / agg-column-first labelSpan width / order survives data refetch / multi-sort indicator position-agnostic / immutable reorder / stable React keys).

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: drag-to-reorder columns in the live portfolio grid. Requires refactoring the four positional row renderers to a single column-descriptor registry + `order` state, decomposing the `colSpan` aggregate rows into per-column cells, and native HTML5 drag-and-drop on the headers (no new dependency) coexisting with click-to-sort. Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): `COLUMNS` registry + `order` state driving header + all body rows; colSpan aggregate rows decomposed to per-column cells (`subtotalCell`/`totalCell` + `labelSpan`); native HTML5 DnD on `SortableTh` (no new dep) coexisting with click-to-sort. 4 new tests; 10/10 pivot + 24/24 portfolio green; tsc + eslint clean; default render verified pixel-identical. Status → review. |
| 2026-06-20 | Bug (user-found): native HTML5 DnD didn't fire from inside the header button in real Chrome. Rewrote to **Pointer Events** (no new dep); AC#2 amended. Verified for real via a CDP-driven mouse drag in headless Chrome (Volume→first column). 10/10 pivot + 24/24 portfolio tests green, tsc + eslint clean. Committed `0b1f17b`. |
| 2026-06-20 | Code-review (3 adversarial layers): all 8 ACs met, no correctness bugs. Decision 1 → accept insert-before-only (no change). 3 patches applied: drag-listener unmount cleanup + `pointercancel`; `COLUMN_BY_ID` undefined guards; deduped `pnlOf`→`PnlAccess`. Real-Chrome drag re-verified PASS; 10/10 pivot + tsc + eslint clean. Status → done. |
