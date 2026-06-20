# Story: Multi-level (nested) grouping in the live portfolio grid — a true pivot

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want to group the live portfolio grid by **more than one** categorical column at once — a nested pivot (e.g. **Sector → Country**, then optionally **→ Ccy**),
so that I can drill the book into sub-totals at several levels (sector, then country within sector, …) instead of only a single flat grouping.

## Background (what exists today — after `portfolios-grid-pivot-grouping`, committed `4e99fee`)

`apps/web/components/portfolio-pivot.tsx` is **flat by default** and supports **single-column** grouping:
- **State:** `const [groupBy, setGroupBy] = useState<string | null>(null)` — `null` = flat; a column id = grouped by that one column.
- **Group key accessor:** `sortValue(h, id)` is reused as the group key (`case "sector"/"country"/"mic"/"currency"/"ticker"/"name"` etc.). A null value → `String(... ?? "—")` → the `"—"` group.
- **Drag-to-group:** the pointer-drag (`onColPointerDown` → window `onMove`/`onUp`/`teardown`; `colUnder`/`zoneUnder`/`isGroupable`). On `onUp`, releasing **over the zone** (`zoneUnder(ev)`) for a groupable (`align:"left"`) column calls `setGroupBy(st.id)`; releasing over another header reorders; a click sorts. `swallowClick()` suppresses the trailing click.
- **Group-by zone:** a **non-reflowing floating overlay** (`absolute bottom-full left-0 right-0 z-20 mb-1 … shadow-lg`, `data-groupby-zone`) shown ONLY while a groupable header is dragged: `{draggingId && isGroupable(draggingId) ? (… "⤓ Drop here to group by {label}") : null}`. It never shifts the table or covers the header row.
- **Grouped rendering:** when `groupBy` is set, `groups` = `Object.entries(reduce by String(sortValue(h, groupBy) ?? "—"))` → `{ label, hs, wt, pnls }[]`, groups ordered by gross weight desc, holdings within each sorted by `sorts`. Rendered by **`RowGroup`** (one subtotal row via `labelSpan`/`subtotalCell` + the group's holding rows). Flat path renders `sortedFlat` directly.
- **Ungroup:** the grouped column's header is tinted (`bg-fg/10`) and carries an **✕** (`aria-label="clear grouping"`) → `onClearGroup={() => setGroupBy(null)}`.
- **Grand total** = Σ `PnlAccess` over **all** `data.holdings` (independent of grouping). `labelSpan(order)` spans the leading non-aggregate columns; `subtotalCell`/`totalCell` are per-column + order-aware.

So today grouping is exactly **one level**. This story generalises it to **N levels (nested)**: `groupBy` becomes an **ordered list** of column ids, the strip **adds a level**, and the body renders **nested subtotal rows**.

## Acceptance Criteria

1. **`groupBy` becomes an ordered list of column ids.** Generalise `groupBy: string | null` → `groupBy: string[]` (`[]` = flat — the current default). Order = nesting order (index 0 = outermost). All the flat-default behaviour (AC#1 of the prior story) is preserved when `groupBy.length === 0`.
2. **Dragging a header onto the strip ADDS a nesting level.** Releasing a groupable column over the zone **appends** its id to `groupBy` (no-op if already present, or not `isGroupable`). So drag Sector → `["sector"]`; then drag Country → `["sector","country"]` (Country nested *within* Sector). Reuse the existing pointer-drag/zone — only the `onUp` zone branch changes from `setGroupBy(st.id)` to an append.
3. **Nested rendering.** When `groupBy.length ≥ 1`, holdings are partitioned recursively: level 0 by `String(sortValue(h, groupBy[0]) ?? "—")`, each of those by `groupBy[1]`, … down to the leaf holdings. Render a **subtotal row per group node at every level** (label + Σweight% + ΣP&L via the existing `labelSpan`/`subtotalCell`), then the node's children (deeper subtotals) or, at the leaf level, the holding rows (sorted by `sorts`). Groups at **each** level are ordered by **gross weight desc** (same convention as today). The single-level case (`["sector"]`) renders **identically to today**.
4. **Depth is visually legible.** Each nested level's subtotal label is **indented** by depth (e.g. `padding-left` step per level on the label cell, and/or a depth tint) so the hierarchy reads clearly. Keep it subtle and consistent with the existing subtotal-row styling (`bg-bg/40`, uppercase tracking). The grand-total row is unchanged at the top.
5. **The strip reflects multi-level state.** While dragging a groupable column that is **not yet** in `groupBy`, the strip reads "⤓ Drop here to group by {label}" (add a level); if the dragged column is **already** grouped, the strip indicates it's already a level (and the drop is a no-op). Showing the current grouping order (e.g. a small breadcrumb "Sector › Country" somewhere non-reflowing) is **optional/nice-to-have**, not required — do not reintroduce a permanent resting row.
6. **Ungroup removes one level (not all).** Each grouped column's header still shows the tint + ✕; clicking the ✕ removes **that column** from `groupBy` (`setGroupBy(prev => prev.filter(x => x !== id))`), and the remaining levels re-nest in their existing order (removing the outer level promotes the inner ones). Clearing the last level → flat. (No need for a separate "clear all" control; removing each ✕ in turn suffices.)
7. **Sort + reorder + group coexist (unchanged contract).** Flat → sort orders the whole list; nested → sort orders holdings **within the deepest leaf groups**. Click sorts; drag onto a header reorders; drag onto the strip adds a group level. `sorts`, `order`, `groupBy` remain independent state. Column reorder still drives both header and every (subtotal + holding) row via `order`.
8. **No regression.** Single-level grouping, the non-reflowing overlay, the 52-week range bar, 2-dp prices, alignment, single-line rows (`whitespace-nowrap`), grand-total math, the drag-listener unmount cleanup, multi-sort, donut (separate component) — all unchanged. `tsc`, `eslint`, and the vitest suites stay green.
9. **Tests.** (a) default still flat (no subtotal rows; all holdings; grand total); (b) drag one column → single-level group identical to today (subtotal rows + `· N` counts); (c) drag a **second** column → **two-level nesting** (outer subtotal rows, inner subtotal rows nested under them, then holdings — assert the extra subtotal rows + nesting via row counts/labels); (d) the ✕ on the **outer** column removes just that level (drops to single-level by the inner column), and the ✕ on the inner returns to single-level by the outer; (e) reorder-by-drop-on-header still works; (f) sort still works flat and within the leaf groups. Update the existing pivot tests that assume `groupBy: string|null` (the `dragToZone` helper still applies; add a `dragToZone` for a second column).

10. **Grouped columns are HIDDEN from the grid (Andre's call, added during review).** A column that defines a grouping level is removed from the grid body AND header (its value already shows in the subtotal labels), keeping the remaining columns aligned. Because the header — and thus its inline ✕ — disappears, ungroup moves to a **grouping breadcrumb**: a small "Grouped: {outer} › {inner} …" chip row that appears ONLY while grouped, each chip carrying an ✕ to remove that level (`aria-label="clear grouping {label}"`). A `visibleOrder = order.filter(id => !groupBy.includes(id))` drives the header + every body/subtotal/total row. Flat → `visibleOrder === order` (nothing hidden). This supersedes the prior single-level decision to keep the grouped column visible (and the per-header ✕).

## Tasks / Subtasks

- [x] Task 1: Generalise `groupBy` state to `string[]` (AC: #1, #2, #6)
  - [x] `useState<string[]>([])`; `onUp` zone branch appends (`prev.includes(st.id) ? prev : [...prev, st.id]`); SortableTh call site `grouped={groupBy.includes(id)}`, `onClearGroup={() => setGroupBy(prev => prev.filter(x => x !== id))}`.
  - [x] Overlay-zone label varies by state: "group by X" (flat) / "add X as a nesting level" (already grouped) / "X is already a grouping level" (X already a level).
- [x] Task 2: Recursive grouping computation (AC: #3, #7)
  - [x] Module-level `buildGroups(holdings, keys, sorts): GroupNode[]` — partitions by `String(sortValue(h, keys[0]) ?? "—")`, computes `{label, wt, pnls, count}` per node, recurses on `keys.slice(1)`; leaf (`keys.length===0`) holds `hs` sorted by `sorts`; siblings ordered by `wt` desc at every level. `totalPnls` stays Σ over all holdings (unchanged). In-component: `groups = groupBy.length > 0 ? buildGroups(data.holdings, groupBy, sorts) : null`.
- [x] Task 3: Render the nested tree (AC: #3, #4)
  - [x] Replaced `RowGroup` with recursive `renderGroupRows(nodes, order, gross, depth, pathKey): ReactNode[]` — a subtotal row per node (label `paddingLeft: 0.5 + depth*1.25rem`, `· count`, + `labelSpan`/`subtotalCell`), then children (recurse, depth+1) or leaf holding rows. Keys encode the full ancestor path (`g:/Tech/United States`, `h:.../<figi>`) so repeated sibling labels under different parents never collide.
- [x] Task 4: Tests (AC: #9)
  - [x] `portfolio-pivot.test.tsx`: kept flat-default + single-level + reorder + sort (all still green under `string[]`); added "nests when a SECOND column dragged (Sector → Country)" (7→9 rows, 4 subtotals via two `· 2` + two `· 1`, 2 ✕ buttons) and "removes ONE nesting level" (✕ on Sector → single-level by Country: 9→6 rows, 1 ✕ left on Country, none on Sector).
- [x] Task 5: Verify (AC: #8)
  - [x] `tsc` + `eslint` clean; 14 pivot + 35 portfolio tests green. Real-Chrome CDP `/portfolios/1/live`: FLAT (6 rows, 0 subtotals) → +Sector (9 rows, 3 subtotals, **header reflow Δ=0px**) → +Country nested (12 rows, **6 subtotals** = 3 sector + 3 nested country) → ✕ Sector (7 rows, 1 subtotal = single-level Country) → ✕ Country (6 rows, flat). Overlay still non-reflowing.
- [x] Task 6: Hide grouped columns + grouping breadcrumb (AC: #10 — added during review)
  - [x] `visibleOrder = order.filter(id => !groupBy.includes(id))` drives header + all body/subtotal/total rows. Removed the per-header ✕ from `SortableTh` (its column is now hidden); added the breadcrumb chip row (`Grouped: {label} › … ✕` each, `aria-label="clear grouping {label}"`) shown only while grouped. Real-Chrome verified: 18→17 headers on +Sector (sector hidden), →16 on +Country (both hidden), breadcrumb `Sector › Country`; ✕ Sector → sector column returns, breadcrumb `Country`. Tests updated (column-hidden assertions + chip-based ungroup).

### Review Findings (code review 2026-06-20)

- [x] [Review][Patch] Test fixture masked true nesting — `COMP` is all-US, so the two-level test never produced two DISTINCT inner siblings; inner-level ordering (AC#3) and the AC#9(d) inner-✕ removal path were unproven. (Edge Case Hunter + Acceptance Auditor.) **Fixed:** added a separate `COMP_MULTI` fixture (Tech→{US 0.4, Germany 0.3}, Energy→{US 0.2, Norway 0.1}) + a test asserting inner siblings render and are ordered by gross weight desc (US before Germany under Tech; "United States" repeats across parents → exercises the path-keyed rows), and a test removing the INNER (Country) level → single-level by Sector. 16 pivot + 37 portfolio tests green; tsc + eslint clean.
- [x] [Review][Defer] `labelSpan` floors at 1, so if EVERY leading non-aggregate column is grouped (or an aggregate is reordered to the front), the subtotal/total **weight %** is subsumed under the label cell (not shown) [portfolio-pivot.tsx labelSpan ~:272, total row ~:524, renderGroupRows]. (Blind + Edge Case Hunter, Med — but column COUNT stays aligned via colSpan, so no other column shifts; it matches the *documented* labelSpan fallback for an aggregate dragged to the front, and only triggers at a contrived ≥6-level grouping. Realistic 2–3-level nesting keeps ticker/name/mic leading → unaffected.) Deferred, pre-existing-style + proportionate.

Dismissed as noise (6): stringify-collapse of group keys (groupable columns are all string-categorical via `isGroupable`=align-left; null→"—" is the specified AC#4 behaviour); nested subtotal % taken against the grand total not the parent (consistent with the single-level view — each subtotal = share of the whole book); groups ordered by weight desc ignoring the active sort (that IS AC#3); leaf `key={h.figi}` collision risk (pre-existing, and path-scoping makes it *less* likely now); the "X is already a grouping level" overlay variant being dropped (moot — grouped columns are hidden, so an already-grouped column can't be dragged); inability to sort/reorder a grouped column (inherent + intended consequence of AC#10, recoverable by ungrouping).

## Dev Notes

### Where this fits

Frontend-only, `apps/web/components/portfolio-pivot.tsx` (+ its test). No API/data change — the categorical fields (`sector`/`country`/`mic`/`currency`) already arrive on each `CompositionHolding`. This is a **direct generalisation** of the just-shipped single-level grouping: same drag, same zone, same `sortValue` group key, same `subtotalCell`/`labelSpan` — only the **arity** of grouping changes (`string|null` → `string[]`) and the rendering becomes **recursive**.

### Reuse — do NOT reinvent

- **`sortValue(h, id)`** — the group-key accessor, used per level. Unchanged.
- **`subtotalCell(id, wt, gross, pnls)` / `labelSpan(order)` / `totalCell` / `COLUMN_BY_ID`** — reuse verbatim for every subtotal row at every depth; only add an indent on the label cell.
- **The pointer-drag** (`onColPointerDown`/`onMove`/`onUp`/`teardown`, `colUnder`, `zoneUnder`, `isGroupable`, `swallowClick`, the unmount `useEffect`) — unchanged except the `onUp` zone branch becomes an **append** and `onClearGroup` becomes a **filter-out**.
- **The non-reflowing overlay zone** (`absolute bottom-full … data-groupby-zone`) — unchanged; do NOT reintroduce a resting row (the user explicitly rejected that, and the reflow was just fixed in review).
- **`compareHoldings` / `sorts` / `onSort`** — unchanged; sort applies to the **leaf** holdings.
- **The grand-total row** — unchanged (Σ over all holdings).

### Critical conventions (regressions if violated)

- **`groupBy = []` MUST stay the default (flat).** Single-level (`["sector"]`) must render like the prior single-level view EXCEPT for AC#10 (the grouped Sector column is now hidden + the ✕ moved to the breadcrumb) — the subtotal math/labels/counts are byte-for-byte identical.
- **Siblings ordered by gross weight desc at EVERY level** (today's convention).
- **Group key via `sortValue`** (single source); null → `"—"` group (per level).
- **React keys must encode the full path** (depth + ancestor labels), not just the node label — two different parents can each have a "United States" child; a bare `key={label}` would collide.
- **Three gestures on one header, disambiguated by release** (click=sort / drop-on-header=reorder / drop-on-strip=add group level) — don't break the click-vs-drag threshold or `suppressClickRef`.
- **Immutable state**, SSR-safe, `react-hooks` lint (set state in handlers, not render). No new dependency — pure React + the existing pointer-drag; **no grid/pivot lib**.
- **Verify via headless Chrome / CDP** (real drag of a 2nd header onto the strip → nested render), per `feedback_minimize_dev_churn`; the dev server hot-reloads frontend edits. **Never `npm --prefix`** in this workspace.

### Files to touch

- MOD `apps/web/components/portfolio-pivot.tsx` (`groupBy: string[]`; append/remove in `onUp`/`onClearGroup`; recursive `buildGroups` + recursive/flattened nested render with depth indent; `SortableTh` `grouped`/`onClearGroup` call sites)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (string[] state; add two-level nesting + remove-one-level tests; keep flat/single-level/reorder/sort)

### References

- [Source: apps/web/components/portfolio-pivot.tsx] — `groupBy` state (~:324); `onUp` zone branch (~:374-380); `onClearGroup`/`grouped` SortableTh props (~:188-201, :473-474); the single-level `groups` build (~:417-433); `RowGroup` (~:506-540); `subtotalCell`/`labelSpan` (~:260-290); the overlay zone (~:442-451).
- [Source: _bmad-output/implementation-artifacts/portfolios-grid-pivot-grouping.md] — the single-level grouping this extends (incl. Open Question #2 which IS this story); the non-reflow overlay decision from its code review.
- [Source: _bmad-output/implementation-artifacts/portfolios-column-reorder.md] — the pointer-drag; [Source: portfolios-multi-column-sort.md] — the sort model that must keep working at the leaf level.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx] — the live page rendering the grid.
- [Source: memory feedback_minimize_dev_churn] — verify via headless Chrome; no `npm --prefix`.

## Open Questions (for Andre — do not block implementation; sensible defaults chosen)

1. **Indent style.** Default: a small `padding-left` step per depth on the subtotal label (+ the existing subtotal tint). Say if you want guide lines / chevrons / a stronger tint per level.
2. **Grouping breadcrumb.** Default: none (the tinted headers + ✕ already show which columns are grouped). A "Sector › Country" breadcrumb is an easy add if you want the order shown explicitly.
3. **Hide grouped columns from the body.** Still default-visible (consistent with the single-level decision). Pivot-style hiding of all grouped columns is a follow-up.
4. **Reorder the nesting levels.** This story adds levels in drag order and removes by ✕; re-ordering existing levels (e.g. drag to swap Sector↔Country nesting) is a possible follow-up, not in scope.
5. **Depth cap.** No hard cap (there are only ~6 categorical columns); practically Sector→Country→Ccy is the realistic max.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m]

### Debug Log References

- RED first: added the two-level nesting + remove-one-level tests; both failed against the `string|null`
  code (a 2nd drag REPLACED the group instead of nesting → 7 rows, not 9), 12 existing green. Then green
  after the `string[]` + recursive refactor.
- Real-Chrome CDP: reused the overlay drag approach (press header → move +30 past threshold → read the
  floating strip's rect → move onto it → release). Confirmed nesting depth via subtotal-row counts and
  that ✕ on the outer level promotes the inner one.

### Completion Notes List

- **`groupBy` is now an ordered `string[]`** (`[]` = flat). Dragging a categorical header onto the strip
  APPENDS it as a nesting level (`["sector"]` → add Country → `["sector","country"]`, Country within
  Sector); a no-op if already a level or non-categorical. The ✕ on each grouped header removes just THAT
  level (`filter(x => x !== id)`), promoting the inner levels; clearing the last → flat.
- **Recursive grouping:** module-level `buildGroups(holdings, keys, sorts)` returns a `GroupNode[]` tree
  (internal nodes carry `children`, leaves carry the sorted `hs`; `count`/`wt`/`pnls` = Σ over the
  subtree), siblings ordered by gross weight desc at every level. `["sector"]` renders identically to the
  prior single-level view (verified: same 7-row shape).
- **Recursive render:** `renderGroupRows(nodes, order, gross, depth, pathKey)` flattens the tree into
  `<tr>`s — a depth-indented subtotal row (reusing `labelSpan`/`subtotalCell`) then children or leaf
  holdings. React keys encode the full ancestor path so a label repeated under different parents (e.g.
  "United States" under both Tech and Energy) never collides.
- **No new dependency; overlay/sort/reorder/grand-total unchanged.** Grand total stays Σ over all
  holdings. The non-reflowing floating strip is reused as-is (real-Chrome header reflow Δ=0px).
- **Open questions left at defaults:** per-depth `padding-left` indent (no guide lines); add-by-drag /
  remove-by-chip-✕ (no level re-ordering); no depth cap.
- **Hide grouped columns (added during review, Andre's call):** a grouped column is now hidden from the
  grid (header + body) — `visibleOrder` filters it out everywhere — and ungroup moved to a grouping
  breadcrumb (chips with ✕), since the column header (and its ✕) goes away. Resolves this story's Open
  Question #1. Real-Chrome verified header count drops per grouped level and restores on ungroup.

### File List

- MOD `apps/web/components/portfolio-pivot.tsx` (`groupBy: string[]`; append in `onUp` zone branch; module-level `GroupNode`/`buildGroups`; recursive `renderGroupRows` replacing `RowGroup`; multi-level overlay label; **`visibleOrder` hides grouped columns**; **grouping breadcrumb chips** replace the per-header ✕; `Fragment` import)
- MOD `apps/web/__tests__/portfolio-pivot.test.tsx` (two-level nesting + remove-one-level tests; column-hidden + breadcrumb-chip-ungroup assertions; existing flat/single-level/reorder/sort retained)

## Change Log

| Date | Change |
|---|---|
| 2026-06-20 | Created story: multi-level (nested) grouping — generalise `groupBy` from `string\|null` to an ordered `string[]`; drag a 2nd+ column onto the existing non-reflowing strip to add a nesting level; recursive subtotal rendering with depth indent; ✕ removes one level. Frontend-only; reuses `sortValue`/`subtotalCell`/`labelSpan`/the pointer-drag/the overlay. Generalises the single-level `portfolios-grid-pivot-grouping` (its Open Question #2). Status → ready-for-dev. |
| 2026-06-20 | Implemented (red-green): `groupBy: string[]` (append-on-drop, filter-out-on-✕); module-level recursive `buildGroups` → `GroupNode` tree; recursive `renderGroupRows` (depth-indented subtotals, path-keyed) replacing `RowGroup`; multi-level overlay label. Added two-level + remove-level tests. 14 pivot + 35 portfolio tests green; tsc + eslint clean; real-Chrome CDP verified flat→Sector→Country-nested(12 rows/6 subtotals)→✕Sector(single-level)→✕→flat, header reflow Δ=0px. Status → review. |
| 2026-06-20 | Review refinement (AC#10, Andre's call): HIDE grouped columns from the grid — `visibleOrder` filters grouped ids from the header + all rows; removed the per-header ✕; added a grouping breadcrumb (chips with ✕) as the new ungroup affordance, shown only while grouped. Resolves Open Q#1. Tests updated (column-hidden + chip-ungroup). 14 pivot + 35 portfolio tests green; tsc + eslint clean; real-Chrome verified 18→17→16 headers as levels added, breadcrumb `Sector › Country`, columns restore on ungroup. |
| 2026-06-20 | Code review (Blind + Edge Case Hunter + Acceptance Auditor): no AC violations; colSpan/labelSpan alignment, remove-one-level, grand-total math, single-level-identical all confirmed. 0 decision + 1 patch + 1 defer + 6 dismissed. Patch applied: added `COMP_MULTI` fixture + tests proving distinct inner siblings ordered by weight desc (path-keyed) and INNER-level (Country) removal → single-level by Sector. Deferred: `labelSpan` floor-at-1 subsumes the weight total under the label at a contrived ≥6-level grouping (column count stays aligned; matches the documented fallback). 16 pivot + 37 portfolio tests green; tsc + eslint clean. Status → done. |
