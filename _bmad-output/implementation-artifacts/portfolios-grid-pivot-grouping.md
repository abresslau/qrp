# Story: Grid grouping is configurable (flat by default; drag any column to group — a pivot)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want the live portfolio grid to start **flat** (ungrouped) and let me **group by any column** by dragging its header into a group-by zone (not just the hard-coded Sector),
so that I can pivot the book by sector, country, exchange, or currency on demand — and start from a plain flat list to drag from.

## Background (what exists today)

`apps/web/components/portfolio-pivot.tsx` is **always grouped by sector**: it builds `bySector` from `h.sector`, renders a sector-subtotal row per sector (ordered by gross weight desc) + a grand-total row, and a `SectorGroup` per sector. Notable current facts:
- **`sector` is NOT a grid column** — the registry `COLUMNS` (ticker, name, country, mic[Exch], currency[Ccy], weight, price, 4×ret, range, 3×pnl, mcap, volume) has no `sector`; sector is only the (invisible) group key. `sortValue(h, id)` (the per-column comparable accessor) likewise has no `sector` case.
- **Sorting** is within-group via `compareHoldings(a,b,sorts)` (`sorts: Sort[]`, default weight desc).
- **Column drag** (just shipped): `onColPointerDown` → window pointermove/up; on drop, `colUnder(ev)` = the `th[data-col-id]` under the pointer → reorder via `setOrder`. `order: string[]` drives header + all body rows; aggregate rows use `labelSpan(order)` + `subtotalCell`/`totalCell`.
- The grand-total + sector-subtotal rows are per-column cells (weight + P&L carry values, others blank); the leading non-aggregated columns are spanned by the label.

So today there is no "flat" mode and no way to choose the group column. This story generalises sector-grouping into **group-by-any-column, default none (flat)**, set by **dragging a column header into a group-by drop zone** (reusing the existing pointer-drag — drop target = the zone instead of another header).

## Acceptance Criteria

1. **Flat by default.** On first render the grid is **ungrouped**: the grand-total row, then ALL holdings as a single flat list sorted by the active sort (`sorts`, default weight desc) — **no group/subtotal rows**. (This is the explicit ask: start flat so the user can drag a column to group.)
2. **Sector is a real, draggable column.** Add a `Sector` column to the registry (text/left-aligned, shows `h.sector`) and a `sector` case to `sortValue`, so Sector can be displayed, sorted, reordered, AND dragged to group — alongside the other categorical columns (Country, Exch, Ccy, Ticker, Name).
3. **Drag a column header into a group-by zone to group by it.** **REVISED 2026-06-20 (Andre's UX call): the zone has NO permanent row** — the drop strip ("⤓ Drop here to group by {column}") appears **only while a groupable column header is being dragged**, then disappears on release. The active grouping is shown on the **grouped column's header** (tinted + an ✕ to ungroup), not a resting bar. Dragging a column header and releasing **over the strip** groups the grid by that column. Reuse the existing pointer-drag: in the drop handler, if the release is over the zone (`(ev.target).closest('[data-groupby-zone]')`), set `groupBy`; otherwise the existing column-reorder runs (drop over another header). Only **categorical** columns (the `align:"left"` text columns: sector/country/mic/currency/ticker/name) are groupable; releasing a numeric/range column on the zone is a no-op (the zone shows it's not accepted).
4. **Grouped rendering generalises the current sector view.** When `groupBy` is set, group holdings by `String(sortValue(h, groupBy) ?? "—")` (a null value → a "—" group), render a subtotal row per group (group label + Σweight% + ΣP&L, via the existing `labelSpan`/`subtotalCell`) + the group's holdings sorted by `sorts`, groups ordered by gross weight desc — i.e. exactly today's sector behaviour, but keyed on the chosen column. The grand-total row is unchanged. Grouping by `sector` reproduces today's look.
4b. **Ungroup returns to flat.** The chip's ✕ (and/or dropping the grouped column back out) clears `groupBy` → flat.
5. **Sort coexists with grouping + reorder.** Flat → sort orders the whole list; grouped → sort orders within each group (current). A header **click** still sorts; a **drag onto another header** reorders; a **drag onto the zone** groups — the three are distinguished by where the pointer is released (the existing click-vs-drag threshold + drop-target check). `sorts`, `order`, and `groupBy` are independent state.
6. **No regression.** All per-column cells, the 52-week range bar, 2-dp prices, alignment, the grand-total math, container-query donut (separate component), etc. are unchanged. Column reorder, multi-sort, and the drag-listener cleanup all still work. `tsc`, `eslint`, and the vitest suites stay green.
7. **Tests.** (a) default render is flat (no subtotal rows; all holdings present; grand total present); (b) dragging a header onto the group-by zone groups by it (subtotal rows appear, group label = the column value); (c) the chip ✕ returns to flat; (d) Sector is present as a draggable column; (e) reorder-by-drop-on-header still works (distinct from group-by-drop-on-zone); (f) sort still works flat and within groups. Update the existing pivot tests that assumed default sector grouping.

## Tasks / Subtasks

- [x] Task 1: Add Sector as a column + sortValue case (AC: #2)
  - [x] Added `{ id: "sector", label: "Sector", align: "left", cell }` after Ccy (joins `DEFAULT_COLUMN_ORDER`; Ticker stays first so the reorder tests hold) + `case "sector": return h.sector ?? null;` in `sortValue`.
- [x] Task 2: `groupBy` state + flat-default rendering (AC: #1, #4, #4b)
  - [x] `const [groupBy, setGroupBy] = useState<string | null>(null)`. Replaced `bySector` with: `groupBy == null` → `sortedFlat` rows directly (no group rows); else group by `String(sortValue(h, groupBy) ?? "—")` → `{ label, hs, wt, pnls }[]` ordered by `wt` desc. Renamed `SectorGroup` → generic `RowGroup` (takes `label`); grand-total uses Σ over all holdings (independent of grouping).
- [x] Task 3: Group-by zone + extend the pointer-drag (AC: #3, #5)
  - [x] Group-by zone bar (`data-groupby-zone`) above the table inside the card: hint when flat, "Grouped by {label} ✕" chip (✕ → `setGroupBy(null)`, `aria-label="clear grouping"`) when set; highlights (`bg-fg/10 ring`) while a header is dragged over it. The table moved into an inner `overflow-x-auto` div so the zone isn't horizontally scrolled.
  - [x] Added `zoneUnder(ev)` + `isGroupable(id)` (= `align === "left"`). `onMove` tracks `dragOverZone`; `onUp` → if released over the zone and the column is groupable, `setGroupBy(id)` (+ suppress click) and return (no reorder); else the existing reorder. Non-categorical drop on the zone is a no-op.
- [x] Task 4: Tests (AC: #7)
  - [x] Updated `portfolio-pivot.test.tsx`: rewrote the old "sector groups" test → FLAT by default (5 rows, no `· 2` subtotal, Sector column present); fixed the column-count (17→18) + body cell indices (+1 after Sector). Added: drag Sector→zone groups (5→7 rows, "Grouped by", "· 2") and chip-✕ returns to flat (7→5). Reorder + sort tests still pass (relative order holds flat).
- [x] Task 5: Verify (AC: #6)
  - [x] `tsc` + `eslint` clean; `vitest` 12/12 pivot + 33 across all portfolio/donut suites. Real-Chrome CDP at `/portfolios/1/live`: **flat on load** (zone hint, 6 body rows), **drag Sector header → zone** groups by sector (zone "Grouped by Sector ✕", 9 rows = +3 sector subtotals), **✕** returns to flat (6 rows).

### Review Findings (code review 2026-06-20)

- [x] [Review][Decision→Patch] Group-by zone reflowed the table when it appeared mid-drag — the strip was a sibling ABOVE the `<table>`, so mounting it on drag-start pushed the table (and the dragged header) down ~33px under the pointer. **Resolved (Andre's call): render the zone as a non-reflowing overlay** — `absolute bottom-full … z-20 shadow-lg` anchored just above the card, so it never shifts the table or covers the header row. Side benefit: dragging a categorical header now stays in *reorder* mode until pulled UP onto the floating strip (cleaner gesture disambiguation). Real-Chrome CDP re-verified: sector header top unchanged (Δ=0px) when the strip appears; drag-onto-strip → grouped (9 rows); ✕ → flat (6 rows).
- [x] [Review][Patch] Fixed stale "sector"-era prose after the generalization to any-column grouping [portfolio-pivot.tsx:81-84, 181, 456-458] — the section comment ("stays grouped by sector"), the SortableTh button `title` ("group **bar**" → "drop strip"), and the body-row comment ("within each **sector**" → "the flat list, or rows within each group when grouped") now match the flat-default/configurable-grouping design. (Acceptance Auditor, Low)
- [x] [Review][Defer] Group weight % uses Σ|weight| over a signed `total_weight` denominator [portfolio-pivot.tsx:427, subtotalCell] — deferred, pre-existing (the old `SectorGroup` aggregated identically; only matters for long-short books and predates this change).

Dismissed as noise (6): orphaned/unclearable grouping if a column leaves `order` (unreachable — `setOrder` only reorders, never removes, so the grouped header + ✕ always render); `groupBy` persists across data refetches (intended in-memory behaviour, consistent with `sorts`/`order`); `key={label}` collision / null→"—" bucket merge (group keys are unique by construction, and null→"—" is the specified AC#4 behaviour); `whitespace-nowrap` on the 52-week-range cell (browser-verified rows stay single-line, bar intact); grouped column dragged to front sits under the `labelSpan` label on subtotal rows (pre-existing cosmetic); AC#4b "drag the grouped column back out to ungroup" not implemented (the ✕ satisfies the primary AC#4b wording and is the design you chose).

## Dev Notes

### Where this fits

Frontend-only, `apps/web/components/portfolio-pivot.tsx` (+ its test). No API/data change — `sector`, `country`, `mic`, `currency` already arrive on each `CompositionHolding` (the grid already reads `h.sector`). This generalises the existing sector grouping; it builds directly on the just-shipped column-reorder pointer-drag (commits `0b1f17b`/`8cfac30`) — keep that intact.

### Reuse — do NOT reinvent

- **`sortValue(h, id)`** is the per-column comparable accessor — reuse it verbatim as the **group-key accessor** (`groupBy` is a column id). Add the missing `sector` case there (and the registry column).
- **`compareHoldings` / `sorts` / `onSort`** — unchanged; sorting applies flat (whole list) or within each group.
- **The pointer-drag** (`onColPointerDown` → `onMove`/`onUp`/`teardown`, `colUnder`, `suppressClickRef`, the unmount `useEffect`) — extend `onUp` with a zone check; do NOT rebuild the drag. Add a `zoneUnder(ev)` mirroring `colUnder`.
- **`labelSpan(order)` / `subtotalCell` / `totalCell` / `COLUMN_BY_ID`** — the subtotal/total rows are already per-column and order-aware; the generic `RowGroup` feeds them the group label (same as `SectorGroup` fed the sector name). The grand-total row is unchanged.
- **`SectorGroup`** → rename to `RowGroup` and pass a `label` (the group's value) instead of `sector`.

### Critical conventions (regressions if violated)

- **Default MUST be flat** (`groupBy = null`) — the headline behaviour change; the current always-sector default is replaced.
- **Three gestures on one header, disambiguated by release:** click (no move ≥5px) → sort; drag → release over a header = reorder, release over the zone = group. Don't break the existing click-vs-drag threshold or `suppressClickRef`.
- **Group key via `sortValue`** (single source) — don't add a parallel accessor; null group → "—".
- **Immutable state**, SSR-safe, `react-hooks` lint (set state in handlers/effects, not render) — same as the existing component.
- **No new dependency** — pure React + the existing pointer-drag; no grid/pivot lib.
- **Verify via headless Chrome / CDP** (real drag of a header onto the zone), per `feedback_minimize_dev_churn`; the dev server hot-reloads frontend edits.

### Files to touch

- MOD `apps/web/components/portfolio-pivot.tsx` (Sector column + `sortValue` case; `groupBy` state + flat-default + generic `RowGroup`; group-by zone + `zoneUnder` + `onUp` extension)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (flat-default + group-by-drag + ungroup + sector-column + reorder-still-works tests; fix the old sector-grouping assumption)

### References

- [Source: apps/web/components/portfolio-pivot.tsx] — `COLUMNS`/`sortValue`/`compareHoldings`; the `bySector`→`sectors` grouping (~:369-385) and `SectorGroup` (~:432); the pointer-drag (`onColPointerDown`/`colUnder`/`onUp`, ~:303-358); `labelSpan`/`subtotalCell`/`totalCell`; the grand-total row (~:417-422).
- [Source: _bmad-output/implementation-artifacts/portfolios-column-reorder.md] — the pointer-drag this extends (drop-target = zone vs header).
- [Source: _bmad-output/implementation-artifacts/portfolios-multi-column-sort.md] — the sort model that must keep working flat + within-group.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx] — the live page rendering the grid.
- [Source: memory feedback_minimize_dev_churn] — verify via headless Chrome; no `npm --prefix`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- RED first: updated the existing tests to the new flat-default + Sector-column expectations and added the
  group-by-drag tests; 4 failed against the sector-default code, then green after implementation.
- Real-Chrome CDP gotcha: the pivot grid sits far down `/portfolios/1/live` (sector header ≈ y1317), so a
  1200px-tall headless viewport put it below the fold and the mouse coordinates missed → used a 2200px
  window so the drag lands. (Same lesson as prior CDP runs.)

### Completion Notes List

- **Grid is now flat-by-default and group-by-any-(categorical)-column.** `groupBy: string|null` (default
  null) drives it: null → all holdings in one sorted list (no group rows); a column id → grouped by
  `sortValue(h, id)` (reused as the group-key accessor), groups ordered by gross weight desc, sorted
  within. Grouping by `sector` reproduces the original view.
- **Sector is now a real column** (added to the registry + `sortValue`), so it can be displayed, sorted,
  reordered, AND dragged to group. Other categorical columns (Country/Exch/Ccy/Ticker/Name) group too.
- **Drag-to-group reuses the existing pointer-drag** — one extra branch in `onUp`: released over the
  `data-groupby-zone` (+ groupable column) → `setGroupBy`; over another header → reorder; a click → sort.
  Three gestures, disambiguated by release target. `groupBy`/`order`/`sorts` are independent state.
- **Generic `RowGroup`** (renamed from `SectorGroup`) renders any group's subtotal via the existing
  `labelSpan`/`subtotalCell`; the grand-total row is unchanged (Σ over all holdings).
- **No regression / no new dependency:** all per-column cells, the 52-week range bar, sort, reorder, the
  drag-listener unmount cleanup, etc. intact. Verified: 12 pivot + 33 portfolio tests, tsc + eslint clean,
  real-Chrome flat→group→ungroup.
- **Open questions left at defaults:** grouped column stays visible (not hidden); single-level only (no
  nested grouping); in-memory (resets on reload); categorical-only grouping. Flagged for Andre.
- **UX refinement (Andre's call, 2026-06-20):** removed the permanent group-by bar — the drop strip now
  appears ONLY while a groupable header is being dragged (zero resting footprint), and the grouped
  column's header carries the ✕ to ungroup (tinted `bg-fg/10`). Re-verified in real Chrome via CDP:
  at rest no zone (6 rows) → drag Sector → strip appears → drop → grouped (9 rows, zone gone, ✕ on
  header) → ✕ → flat (6 rows). 12 pivot + 33 portfolio tests green; tsc + eslint clean.

### File List

- MOD `apps/web/components/portfolio-pivot.tsx` (Sector column + `sortValue` case; `groupBy` state + flat/grouped rendering + generic `RowGroup`; group-by zone + `zoneUnder`/`isGroupable` + `onUp` group branch)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (flat-default + column-count/index fixes; group-by-drag + ungroup tests)

## Open Questions (for Andre — do not block implementation)

1. **Hide the grouped column?** When you group by Sector, the Sector column still shows (redundant with the group header). Default: keep it visible (simplest). Pivot-style would hide the grouped column from the grid body — say if you want that.
2. **Multi-level grouping (nested pivot).** This story does single-column grouping (group by ONE column). Dragging several columns into the zone for nested groups (Sector → Country) is a natural follow-up but bigger (recursive group rows) — flag if you want it.
3. **Persist the grouping?** In-memory (resets on reload), consistent with the sort/order/donut decisions. localStorage per portfolio is a small add-on if wanted.
4. **Group by numeric columns?** Default restricts grouping to categorical (text) columns; numeric (price/returns) would make a group per distinct value (rarely useful). Say if you want numeric grouping (e.g. binned).

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: make the portfolio grid grouping configurable — flat by default, group by any categorical column by dragging its header into a group-by zone (generalising the hard-coded sector grouping; reusing `sortValue` as the group key and the existing pointer-drag). Adds Sector as a real draggable column. Single-level; frontend-only. Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): Sector column + `sortValue` case; `groupBy` state (flat default) + generic `RowGroup`; group-by zone + `zoneUnder`/`isGroupable` + `onUp` group branch. Updated/added tests (flat default, column-count/index, drag-to-group, ungroup). 12 pivot + 33 portfolio tests green; tsc + eslint clean; real-Chrome CDP verified flat→drag-Sector→grouped(9 rows)→✕→flat. Status → review. |
| 2026-06-20 | Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor): all 6 ACs + full test matrix confirmed; grand-total refactor proven equivalent. 1 decision + 1 patch + 1 defer + 6 dismissed. Applied: (1) group-by zone → non-reflowing floating overlay (`absolute bottom-full`, zero table reflow, cleaner reorder-vs-group gesture); (2) stale "sector"-era comments/title text generalized. Deferred: group-weight Σ\|w\| vs signed total denominator (pre-existing, long-short only). 12 pivot tests + tsc + eslint green; real-Chrome re-verified no-reflow (header Δ=0px) + group + ungroup. Status → done. |
