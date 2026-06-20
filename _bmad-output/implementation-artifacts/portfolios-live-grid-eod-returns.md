# Story: Live Portfolio grid — live-adjusted trailing return columns (1D · 1M · 3M · 6M) after Price

Status: done

<!-- Created via bmad-create-story (2026-06-20). Operator: "For the Live Portfolio page, I want stock
returns in the grid, after price 1D 1M 3M 6M" + "these returns I mentioned should be adjusted to live
prices". Standalone console-enhancement artifact (not in an epic decomposition), like
portfolios-live-heatmap-and-pizza.md and portfolios-exposure-and-layout.md — tracked inline here, NOT
enumerated in sprint-status.yaml (per its DERIVATION NOTE: delivered stories outside the epic
decompositions live in their artifacts, not the status file). -->

## Story

As the **operator of QRP**,
I want **each stock row in the Live Portfolio grid to show its trailing returns over 1D, 1M, 3M and 6M —
each re-based to end at the holding's **live** price rather than yesterday's close — in columns placed
right after the live Price**,
so that **I can read each holding's momentum across multiple horizons *as of right now*, consistent with
the live price, live move and live P&L already on the page, without leaving the cockpit for the Explorer**.

## Why (current state)

The Live Portfolio page (`apps/web/app/portfolios/[id]/live/page.tsx`) renders, in order: header + live
freshness badge → `<PortfolioRiskPnl>` → sector pizza + top movers → `<PortfolioHeatmap>` → **the pivot
grid `<PortfolioPivot>`** (the "grid" in the request). The pivot grid
(`apps/web/components/portfolio-pivot.tsx`) is the book grouped by sector, each stock carrying the
Explorer-style columns plus its weight, **live** return and P&L contribution. Today its columns are:

```
Ticker · Name · Country · Exch · Ccy · Wt · Price · Mkt cap · Volume · Return · P&L
```

The single **Return** column is the *live intraday* return (live quote vs its own prior close — the QH.2
`live_return`). There is **no view of trailing multi-horizon performance per holding** on this page, and
crucially the operator wants those horizons measured **to the live price**, not to the last EOD close —
so the whole row reads "as of now," matching the live Price, the live move, and the live P&L.

The data path is entirely in hand:

- The grid is fed by **one** response — `GET /api/analytics/portfolios/{pid}/composition`
  (`analytics/gateway.py:329` → `analytics/router.py:203`). The page owns the single fetch; `<PortfolioPivot>`,
  `<PortfolioHeatmap>`, `<PortfolioPizza>` and `<PortfolioMovers>` are all **presentational** and take
  `data` as a prop. So the new returns must ride on the **composition** response (extend `composition()`),
  NOT a new endpoint or a second fetch.
- `composition()` already fetches, per holding, the **live quote price** (`price`) and the live return
  (`live_return`) via the bounded fan-out (`analytics/gateway.py:438-454`), and runs ONE `sym` metadata
  query (`:364-409`) that already pulls the latest stored row from `prices_raw` (currently just
  `volume` — `:400-404`). It just needs the latest stored **close** too, plus the stored trailing returns.
- The stored trailing returns live in `fact_returns` (price return `pr` per window), the same matrix the
  Explorer security detail reads (`sym/gateway.py:774-782`). The window codes are fixed and already used by
  the heat-map selector: `HEATMAP_WINDOWS = ["1D","WTD","MTD","QTD","YTD","1M","3M","6M","1Y"]`
  (`sym/gateway.py:28`); `1D`,`1M`,`3M`,`6M` are valid `return_window.code` values.

### The re-basing math (why we don't just pass `fact_returns.pr` through)

A stored window return is measured to the **last close**, not to the live price:

```
pr[w] = last_close / base_close[w] − 1        ⇒   base_close[w] = last_close / (1 + pr[w])
```

To make the window end at the **live** price (the operator's request), re-base it onto the live quote:

```
window_return_live[w] = live_price / base_close[w] − 1
                      = live_price · (1 + pr[w]) / last_close − 1
```

So the inputs are: `live_price` (the live quote — already fetched), `last_close` (the latest stored close
— one extra column on the existing metadata query), and `pr[w]` (the stored window return — one new
`fact_returns` query). No persistence, no schema change.

> Note on 1D: with `pr_1D` measured to `last_close`, the re-based 1D return is the trailing-session window
> ending at the live price — close to, but not identical to, the existing intraday **Return** column
> (which is `live_price / quote.previousClose − 1`). Both belong on the row; the operator asked for 1D
> explicitly. Keep them as separate columns.

So this is a **surfacing + light-compute** story: one extra column on the metadata query (`last_close`),
one new `fact_returns` query, the re-base formula in the holdings loop, one new field on the holding
contract (Pydantic + the local TS type), four new columns in the pivot grid. **No migration, no schema
change, nothing persisted, no new dependency.**

## Acceptance Criteria

1. **API — live-adjusted trailing returns on each composition holding.** `GET
   /api/analytics/portfolios/{pid}/composition` returns, on every holding, a new field
   `window_returns: { "1D": float|null, "1M": float|null, "3M": float|null, "6M": float|null }` — for a
   holding that **has a live quote**, the trailing return over each window **re-based to end at the live
   price**: `window_return[w] = live_price · (1 + pr[w]) / last_close − 1`, where `pr[w]` is the latest
   stored `fact_returns.pr` for that `(composite_figi, window)` and `last_close` is the holding's latest
   stored close (`prices_raw`). Values are fractional decimals (e.g. `0.0123` = +1.23%), NOT pre-multiplied
   percentages — same contract as `live_return`. Every one of the four keys is always present (value
   `null` when not computable), so the frontend never guards a missing key.
2. **Honest degradation per cell.** A window is `null` when it can't be computed: no stored `pr[w]` for
   that holding, OR `last_close` missing/≤ 0. When the holding has **no live quote** (`live_return`/`price`
   null — unmapped MIC, miss, 503-degraded cell), the window **falls back to the plain stored EOD return**
   `pr[w]` (the trailing return to last close) rather than null — the holding's row `freshness` already
   signals it isn't live, and an EOD trailing return is more useful than a blank. (So: priced live →
   re-based to live; not priced → EOD value; no stored return → null "—".) Document this fallback in the
   gateway docstring.
3. **Latest as-of per window; one query; reuses the read seam; writes nothing.** For each
   `(composite_figi, window)` use the row with the **max `as_of_date`** (mirroring the Explorer
   `DISTINCT ON (window_id) … ORDER BY window_id, as_of_date DESC`, `sym/gateway.py:774-782`); windows
   need not share an `as_of_date`. Fetch all four windows for all figis in **one** `sym` query
   (`WHERE composite_figi = ANY(%s) AND w.code = ANY(%s)`), not a per-holding loop. The query runs on the
   analytics `sym` read connection inside `composition()` — no new endpoint, no `portfolios` package
   import, no new role grant (`fact_returns`/`return_window`/`prices_raw` are already in the QH.3
   `qrp_readonly` read surface). SELECT-only — the live path's writes-nothing invariant holds
   (`test_composition_writes_nothing` stays green). The endpoint's error contract is unchanged (404
   missing portfolio, 422 over `COMPOSITION_MAX`, 503 wholly-unreachable quote provider); the
   returns/close reads are quote-independent and must not introduce a new failure mode (a DB read on the
   already-open conn, not a 503 source).
4. **UI — four return columns after Price.** In `<PortfolioPivot>` the column order becomes:

   ```
   Ticker · Name · Country · Exch · Ccy · Wt · Price · 1D · 1M · 3M · 6M · Mkt cap · Volume · Return · P&L
   ```

   The four new columns sit **immediately after Price** and before Mkt cap. Each cell shows the holding's
   `window_returns[window]` via the existing `pct()` + `retClass()` helpers (green ≥ 0 / red < 0 / muted
   "—" for null) — right-aligned `tabular-nums`, matching the existing Return column. The live **Return**
   column and the **P&L** column stay at the end and are NOT replaced — the intraday move and the trailing
   live-adjusted windows coexist.
5. **Subtotal & total rows stay aligned.** The sector subtotal row and the grand-total `<tfoot>` row do
   NOT aggregate the four new columns (summing returns is meaningless — the rule the code already applies
   to the live Return column). The `colSpan` of the blank middle span that today covers Price/Mkt
   cap/Volume (`colSpan={3}`) widens to cover Price + the 4 new + Mkt cap + Volume (`colSpan={7}`) so the
   Wt, Return and P&L cells stay under their headers. Column count goes 11 → 15; no misaligned cells in any
   row (header, sector subtotal, holding, footer).
6. **No-data / empty states unchanged.** A portfolio with no shown vector still shows the existing "No
   holdings yet" state; a holding with all-null windows shows four "—" cells (not an error). Widen the
   table `min-w-[56rem]` → `min-w-[72rem]` so 15 columns fit without crushing (already `overflow-x-auto`).
7. **Typed contract, tested, no regressions.** `window_returns` added to the Pydantic `CompositionHolding`
   (`analytics/router.py:116-131`) AND the local TS `CompositionHolding` type (`portfolio-heatmap.tsx:10-26`,
   which `portfolio-pivot.tsx` imports). `gen:types` regen is a pre-deploy step (needs the running API) —
   ledger it; the components use the local type so nothing blocks on it. New/updated tests: **API** —
   `test_portfolio_composition.py` asserts `window_returns` re-bases correctly for a priced holding
   (`live_price·(1+pr)/last_close − 1`), falls back to plain `pr` for an unpriced holding, is `null` when
   `pr` or `last_close` is missing, picks the latest `as_of`, and that writes-nothing still holds.
   **Console** — `portfolio-pivot.test.tsx` asserts the four headers render in order after Price, a
   holding's four values render with the right sign/format, a null window renders "—", and the
   subtotal/footer rows stay column-aligned. `uv run pytest` (services/api), `npm test`, `eslint .`,
   `npx tsc --noEmit`, `npm run build` all green. No new dependency.

## Tasks / Subtasks

- [x] **Task 1 — Add `last_close` to the metadata query** (AC: 1,3) — in
  `packages/analytics/src/analytics/gateway.py` `composition()`, extend the existing `prices_raw` lateral
  in the metadata query (`:400-404`, which already selects `volume`) to also select the latest `close`
  (alias `last_close`). Add it to the `meta` tuple unpack (`:365-366`, `:436`) and `_MISSING` (`:363`).
- [x] **Task 2 — Fetch the four stored window returns** (AC: 1,3) — add ONE `sym` read after the metadata
  query, keyed off the same `figis`, with a new module constant
  `WINDOW_RETURNS = ["1D", "1M", "3M", "6M"]` (define near `COMPOSITION_MAX`):

  ```sql
  SELECT DISTINCT ON (fr.composite_figi, fr.window_id)
         fr.composite_figi, w.code, fr.pr
    FROM fact_returns fr JOIN return_window w USING (window_id)
   WHERE fr.composite_figi = ANY(%s) AND w.code = ANY(%s)
   ORDER BY fr.composite_figi, fr.window_id, fr.as_of_date DESC
  ```

  params `(figis, WINDOW_RETURNS)`. Build `pr_by_figi: dict[str, dict[str, float|None]]`, seeding every
  figi with all four keys = `None`, filling `float(pr)` when not null.
- [x] **Task 3 — Re-base to live in the holdings loop** (AC: 1,2) — in the loop (`:431-469`), after `price`
  (live) and `lr` (live_return) are resolved (`:438-454`), compute per window:

  ```python
  win: dict[str, float | None] = {}
  for code in WINDOW_RETURNS:
      pr = pr_by_figi[figi][code]
      if pr is None:
          win[code] = None
      elif price is not None and last_close not in (None, 0):
          # re-base the trailing window to END at the live price
          win[code] = price * (1.0 + pr) / float(last_close) - 1.0
      else:
          win[code] = pr            # not priced live → plain EOD trailing return
  ```

  Attach `"window_returns": win` to the holding dict (`:461-469`). Keep `live_price = price` naming
  consistent with the existing code (`price` is the live quote price).
- [x] **Task 4 — Extend the contract** (AC: 1,7) — add `window_returns: dict[str, float | None]` to the
  Pydantic `CompositionHolding` (`analytics/router.py:130`, after `live_return`) and
  `window_returns: Record<string, number | null>;` to the local TS `CompositionHolding`
  (`portfolio-heatmap.tsx:24`, after `live_return`). `portfolio-pivot.tsx` already imports the TS type.
- [x] **Task 5 — Four columns in the pivot grid** (AC: 4,5,6) — in `portfolio-pivot.tsx`:
  - Header (`:49-61`): insert four `<th class="px-3 py-2 text-right font-medium">1D</th>` … `6M` between
    the **Price** `<th>` (`:56`) and **Mkt cap** `<th>` (`:57`).
  - Holding row (`SectorGroup`, `:114-128`): insert four right-aligned `tabular-nums` cells between the
    Price `<td>` (`:122`) and Mkt cap `<td>` (`:123`):
    `<td class={...retClass(h.window_returns?.["1D"] ?? null)...}>{pct(h.window_returns?.["1D"] ?? null)}</td>`
    for 1D/1M/3M/6M. Reuse `pct()` (`:10`) and `retClass()` (`:16`).
  - Sector subtotal (`:103-113`): blank middle `colSpan={3}` (`:110`) → `colSpan={7}`.
  - Grand-total `<tfoot>` (`:69-77`): blank middle `colSpan={3}` (`:74`) → `colSpan={7}`.
  - Table width (`:47`): `min-w-[56rem]` → `min-w-[72rem]`.
- [x] **Task 6 — Tests** (AC: 7) — **API** `services/api/tests/test_portfolio_composition.py`: feed the
  fake `sym` conn `fact_returns` rows + a `last_close` in the metadata row; assert (a) a priced holding's
  `window_returns[w] == price*(1+pr)/last_close − 1` (use exact numbers), (b) an unpriced holding falls
  back to plain `pr`, (c) a missing `pr` or `last_close` → null, (d) latest `as_of` wins. Confirm
  `test_composition_writes_nothing` still passes. **Console** `apps/web/__tests__/portfolio-pivot.test.tsx`:
  add `window_returns` to the mocked holdings; assert the four ordered headers after Price, formatted
  values, a null → "—", and footer/subtotal cell alignment. Run `uv run pytest` (services/api), `npm test`,
  `eslint .`, `npx tsc --noEmit`, `npm run build`. Ledger the `gen:types` pre-deploy step. Update the Dev
  Agent Record below.

## Review Findings (code review 2026-06-20)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Auditor confirmed all 7 ACs
and all key constraints MET; no decision-needed. Actionable items (all patches applied):

- [x] [Review][Patch] Non-finite (`NaN`/`Inf`) `last_close` or `pr`, and negative `last_close`, would
  emit a garbage/non-finite window value — a single `NaN` breaks JSON serialization of the WHOLE
  composition response (client `JSON.parse` throws → blank page). FIXED: `lc_ok = lc is not None and
  math.isfinite(lc) and lc > 0`; non-finite `pr` → null on both branches (matches the `math.isfinite`
  weight hygiene already in `composition()`) [packages/analytics/src/analytics/gateway.py composition()]
- [x] [Review][Patch] Frontend `pct()`/`retClass()` would render `NaN%`/`Infinity%` — added a
  `Number.isFinite` guard → "—"/muted (defense-in-depth; the helper is shared with the live-return and
  P&L columns) [apps/web/components/portfolio-pivot.tsx]
- [x] [Review][Defer] "Latest `as_of` per window" is verified by code inspection, not a unit test — the
  DB-free fake conn can't exercise the SQL `DISTINCT ON … ORDER BY as_of_date DESC`; the query mirrors
  the proven Explorer template. Closing it needs a DB integration test [services/api/tests/test_portfolio_composition.py] — deferred (test-coverage caveat).

#### Dismissed (noise / per-spec / false positive)

Mixed as-of within a window column (live-priced vs EOD-fallback rows) — per-spec AC2 documented
degradation, conveyed by the row freshness badge. Priced-but-`last_close`-missing → null — the spec's
explicitly-tested intent (AC2 + testing standards). Meta-tuple unpack arity & `last_close` fan-out
(Blind Hunter, diff-only) — false positives: `_MISSING` is the correct 11-tuple and the `prices_raw`
lateral is `ORDER BY session_date DESC LIMIT 1` (latest-per-figi), both confirmed by the Edge Case Hunter
against source + the live endpoint (5/5 priced, sane values). `pr = -1` → −100%, the `?? null` 0-handling,
empty-dict/undefined `window_returns` — all confirmed safe.

## Dev Notes

### Current state of files being touched (read in story prep — exact anchors)

- **`packages/analytics/src/analytics/gateway.py`** (UPDATE) — `composition()` `:329-489`. Metadata query
  `:364-409` (the `prices_raw` lateral at `:400-404` already pulls `volume` — add `close`); the `_MISSING`
  tuple `:363` and the `meta` unpack `:365-366`/`:436` must grow by one. The bounded quote fan-out
  `:411-419` yields `batch`; the holdings loop `:431-469` resolves `price` (live) `:445` and `lr`
  `:443`, then appends the holding dict `:461-469` — that's where the re-base + `window_returns` go.
  `COMPOSITION_MAX` is the constant to define `WINDOW_RETURNS` beside. Do NOT touch `live_pnl()`
  (`:213-327`) or `analytics()`.
- **`apps/web/components/portfolio-pivot.tsx`** (UPDATE — the grid) — presentational, takes
  `data: Composition`. Helpers `pct`/`wpct`/`retClass` (`:10-19`) handle null → "—" and sign-coloring —
  **reuse them**. Header `:49-61` (11 `<th>`); holding rows in `SectorGroup` `:114-128`; sector subtotal
  `:103-113`; grand-total footer `:69-77`. The live Return column is `:59`/`:125` — **keep it**.
  Column-span gotcha: the subtotal (`:110`) and footer (`:74`) `colSpan={3}` blanks Price+Mktcap+Volume —
  both must become `colSpan={7}` after inserting four columns, or every cell to the right shifts under the
  wrong header.
- **`apps/web/app/portfolios/[id]/live/page.tsx`** (READ — no change) — owns the single composition fetch
  (`:63-93`) and passes `data={comp}` to `<PortfolioPivot>` (`:160`). The grid gets the new returns for
  free once they ride the composition response — **no page edit**.
- **`packages/analytics/src/analytics/router.py`** (UPDATE) — `CompositionHolding` `:116-131`; add
  `window_returns: dict[str, float | None]` after `live_return` (`:130`). Route/error contract `:203-215`
  unchanged.
- **`apps/web/components/portfolio-heatmap.tsx`** (UPDATE — type only) — exports the local
  `CompositionHolding`/`Composition` types (`:10-44`) imported by the pivot. Add
  `window_returns: Record<string, number | null>;` to `CompositionHolding` (`:24`). The heatmap component
  ignores the field (it colors by `live_return`) — no render change there.
- **`services/api/src/qrp_api/modules/sym/gateway.py`** (READ — the query template) — Explorer
  security-detail returns query `:774-782` (`DISTINCT ON (window_id) … fr.pr … ORDER BY window_id,
  as_of_date DESC`) is the shape to adapt to many figis + the four-code filter. `HEATMAP_WINDOWS` (`:28`)
  confirms `1D`/`1M`/`3M`/`6M` are valid codes.
- **`services/api/tests/test_portfolio_composition.py`** (UPDATE) — fake/recording `sym` conn dispatching
  by SQL + monkeypatched `read_latest_weights`/`portfolio_exists`/`fetch_quotes_batch`. Feed `fact_returns`
  rows and a `last_close` so the re-base can be asserted with exact numbers; `test_composition_writes_nothing`
  scans `conn.seen` for INSERT/UPDATE (new query is SELECT → stays green).
- **`apps/web/__tests__/portfolio-pivot.test.tsx`** (UPDATE) — existing pivot test with a mocked
  `Composition`; add `window_returns` to the mock holdings.

### Key constraints

- **Re-base to the live price; don't pass `pr` through raw (for priced names).** The whole point of the
  operator's follow-up: the window must END at the live quote, not the last close. Formula:
  `window_return[w] = live_price · (1 + pr[w]) / last_close − 1`. Equivalent to chaining the intraday move
  onto the EOD window, but computed via `last_close` (sym's own bridge) so it doesn't depend on the quote
  vendor's `previousClose` matching sym's close.
- **Price return (`pr`), not total return (`tr`).** "Stock returns" here = price return, matching the heat
  map / movers convention. A TR variant or a PR/TR toggle is a deferred option.
- **Fractional decimals, formatted in the UI.** Both `pr` and the re-based value are fractions; the grid's
  `pct()` multiplies by 100. Do NOT pre-multiply server-side (same contract as `live_return`).
- **These are trailing windows, distinct from the live Return column.** Keep both; don't merge.
- **One fetch, one contract.** The new returns ride the existing `composition` response — no new endpoint,
  no second fetch. Preserves the "one fetch feeds grid + heatmap + pizza + movers" invariant.
- **Topology + role unchanged.** `fact_returns`/`return_window`/`prices_raw` are already in the QH.3
  `qrp_readonly` read surface (the universe heat map + Explorer read them via the same role). No
  `sym_contract.py` change, no re-provision. Confirm before assuming; if a topology test flags any of
  these tables, STOP and reconsider — don't widen the surface silently.
- **Next.js 16** (`apps/web/AGENTS.md`): read `node_modules/next/dist/docs/` before component work; these
  are client components (`"use client"`).
- **No new dependency, no migration, nothing persisted.**

### Testing standards

- **API:** mirror `services/api/tests/test_portfolio_composition.py`. Use exact numbers so the re-base is
  unambiguous, e.g. `last_close=100`, `pr_1M=0.10` (base 90.909…), live `price=110` →
  `window_returns["1M"] = 110·1.10/100 − 1 = 0.21`. Cases: (a) priced holding re-bases correctly; (b)
  unpriced holding → plain `pr`; (c) missing `pr` → null; (d) `last_close` null/0 → null (priced) or `pr`
  (the AC2 ordering: null only when `pr` is null; when `pr` present but `last_close` unusable AND priced →
  null — make the dev choice explicit in code and assert it); (e) latest `as_of` wins. Re-run
  `test_composition_writes_nothing`.
- **Console:** vitest + @testing-library, mocked `Composition` prop (the grid is presentational — no
  fetch). Assert: four headers `1D`/`1M`/`3M`/`6M` present and ordered immediately after `Price`; a
  holding's four cells render formatted (sign + `%`); a null window → `—`; `<tfoot>` total + a sector
  subtotal row have the expected `<td>` count / span. No new dependency.

### Project Structure Notes

- Surfacing + light compute: `analytics/gateway.py` (+ `last_close` on the metadata query, + the
  `fact_returns` query, + `WINDOW_RETURNS` const, + re-base + `window_returns` per holding),
  `analytics/router.py` (+ one Pydantic field), `portfolio-heatmap.tsx` (+ one TS field),
  `portfolio-pivot.tsx` (+ four columns + colSpan fixes + width), two test files, regenerated
  `api-types.ts` (pre-deploy). **No migration, no schema change, nothing persisted, no new dependency.**
- Standalone console-enhancement artifact — NOT added to `sprint-status.yaml`'s `development_status` (per
  that file's DERIVATION NOTE).
- Deferred / ledger: a PR/TR toggle (or a separate TR set), operator-configurable windows (reuse
  `HEATMAP_WINDOWS`), a per-cell live-vs-EOD indicator (today the row freshness conveys it), surfacing the
  same columns in the **detail** page holdings table, and the `gen:types` regen.

### References

- [Source: packages/analytics/src/analytics/gateway.py:329-489] — `composition()`: metadata query
  (`:364-409`, `prices_raw` lateral `:400-404`), holdings loop (`:431-469`, live `price` `:445`); add
  `last_close`, the `fact_returns` query, the re-base + `window_returns` here.
- [Source: packages/analytics/src/analytics/router.py:116-131,203-215] — `CompositionHolding` model (add
  `window_returns`) + the unchanged `/composition` route/error contract.
- [Source: apps/web/components/portfolio-pivot.tsx:10-19,47-77,103-131] — helpers, header/footer/subtotal
  `colSpan` layout, holding row — where the four columns + span fixes + width go.
- [Source: apps/web/app/portfolios/[id]/live/page.tsx:63-93,160] — single composition fetch + the
  `<PortfolioPivot data={comp} />` mount (no page edit needed).
- [Source: apps/web/components/portfolio-heatmap.tsx:10-26] — local `CompositionHolding` type to extend.
- [Source: services/api/src/qrp_api/modules/sym/gateway.py:28,774-782] — `HEATMAP_WINDOWS` code vocabulary
  + the Explorer `fact_returns ⋈ return_window` DISTINCT-ON query template to adapt.
- [Source: services/api/tests/test_portfolio_composition.py] — the API fake-conn/monkeypatch pattern to
  mirror.
- [Source: _bmad-output/implementation-artifacts/portfolios-live-heatmap-and-pizza.md] — the parent story:
  the one-fetch-feeds-the-views contract, the composition shape, the QH.2 live-quote/`last_close` source,
  and why these aren't in sprint-status.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]` (Amelia / bmad-dev-story)

### Debug Log References

- `uv .venv python -m pytest services/api` → **142 passed** (was 137 baseline; +1 new composition
  re-base test plus the dispatch/`last_close` upgrades to the existing composition tests — all green,
  incl. `test_composition_writes_nothing` and the topology/readonly gates).
- `npm --workspace web run test` (vitest) → **78 passed / 19 files** (the pivot test gained a
  trailing-columns case; the four sibling composition-mock tests — pizza/movers/heatmap/live — updated
  for the new required `window_returns` field, behavior unchanged).
- `eslint` 0/0, `tsc --noEmit` clean, `next build` ✓ 20/20 routes (incl. `/portfolios/[id]/live`).

### Completion Notes List (2026-06-20)

- **Returns re-based to the LIVE price (the operator's refinement).** `composition()` now fetches the
  latest stored close (`last_close`, added to the existing `prices_raw` metadata lateral) and the latest
  `fact_returns.pr` per `(figi, window)` for `WINDOW_RETURNS = ["1D","1M","3M","6M"]` in ONE extra `sym`
  query, then per holding computes `window_return[w] = live_price · (1 + pr) / last_close − 1`. Priced →
  re-based to live; not priced live → degrades to the plain stored EOD `pr`; `pr`/`last_close` unusable →
  null. All four keys always present. Raw fractions (the UI's `pct()` ×100s).
- **One fetch, one contract.** The values ride the existing `/composition` response (no new endpoint, no
  second fetch) — the Live page already owns the single fetch and passes `data` to `<PortfolioPivot>`, so
  no page edit was needed.
- **No new role grant.** `fact_returns`/`return_window`/`prices_raw` are already in the QH.3 `qrp_readonly`
  read surface (Explorer + universe heat map read them via the same role), so — unlike the parent story's
  `gics_scd` AR-R3 extension — there is **no `sym_contract.py` change and no readonly re-provision** at
  deploy. SELECT-only; the writes-nothing invariant holds.
- **Grid columns.** `<PortfolioPivot>` gains 1D/1M/3M/6M columns immediately after Price (before Mkt cap),
  reusing the existing `pct()`/`retClass()` helpers (green/red/"—"). The live **Return** and **P&L**
  columns are unchanged. Subtotal + total rows widened their blank middle `colSpan` 3 → 7 so every cell
  stays under its header (column count 11 → 15); table `min-w` 56rem → 72rem.
- **Latest-as_of caveat (test honesty).** The "latest `as_of` per window" pick is the SQL's
  `DISTINCT ON … ORDER BY as_of_date DESC`; the DB-free fake conn can't exercise it, so the unit test
  feeds already-deduped rows and the as_of ordering is an integration concern (noted inline in the test).
- **No live-app verification.** A live composition needs a running API restart + live DB; per the
  minimize-dev-churn rule the dev server (which runs the API without `--reload`) was not restarted so
  Andre's open tab isn't disturbed. Covered by the unit suites + a green production build — same posture
  as the parent story. Post-deploy smoke (load a portfolio's Live page, confirm the four columns populate)
  is the open check.
- **`gen:types` NOT run** — it needs the running API; the components use the LOCAL `Composition` types
  (the heatmap-view convention), so nothing consumes the generated `PortfolioComposition`. Pre-deploy
  step, ledgered alongside the parent story's `gen:types` ledger.

### File List

- `packages/analytics/src/analytics/gateway.py` (UPDATE) — `WINDOW_RETURNS` const; `composition()`:
  `last_close` on the metadata query, the `fact_returns` window-returns query, the live re-base + the
  `window_returns` field per holding; docstring updated.
- `packages/analytics/src/analytics/router.py` (UPDATE) — `window_returns: dict[str, float | None]` on
  the `CompositionHolding` Pydantic model.
- `apps/web/components/portfolio-heatmap.tsx` (UPDATE) — `window_returns` on the exported local
  `CompositionHolding` type (imported by the pivot).
- `apps/web/components/portfolio-pivot.tsx` (UPDATE) — `WINDOWS` const; 1D/1M/3M/6M header + body cells
  after Price; subtotal/footer `colSpan` 3 → 7; `min-w` 56rem → 72rem; header comment.
- `services/api/tests/test_portfolio_composition.py` (UPDATE) — `_SymConn` dispatches by SQL
  (meta vs `fact_returns`); `last_close` added to meta rows; new `test_composition_window_returns_rebased_to_live`.
- `apps/web/__tests__/portfolio-pivot.test.tsx` (UPDATE) — `window_returns` in the mock + a new
  trailing-columns rendering/alignment test.
- `apps/web/__tests__/portfolio-pizza.test.tsx`, `portfolio-movers.test.tsx`, `portfolio-live.test.tsx`,
  `portfolio-heatmap.test.tsx` (UPDATE) — added the now-required `window_returns` field to composition mocks.

### Change Log

- 2026-06-20: Story created (ready-for-dev), then revised for the "adjust to live prices" refinement.
- 2026-06-20: Implemented. `/composition` holdings gain `window_returns` (1D/1M/3M/6M trailing price
  returns re-based to the live price; plain EOD fallback when unpriced; null when not computable) via one
  extra `sym` read (`last_close` + `fact_returns.pr`); four new columns after Price in the live pivot grid.
  No new endpoint/fetch, no migration, nothing persisted, no role re-provision. 142 api + 78 console tests,
  eslint 0/0, tsc + build green. Status → review.
- 2026-06-20: Post-restart live smoke — the dev runner's API runs without `--reload`, so it served the
  stale pre-change composition (every grid cell "—"); restarted the runner and verified
  `/api/analytics/portfolios/1/composition` now returns `window_returns` (5/5 priced, sane re-based
  values; 1D ≈ the live move as expected).
- 2026-06-20: Code review (3 adversarial layers; all 7 ACs + constraints MET, no High bugs). 2 patches
  applied + 1 deferred: (1) finite-positive `last_close` / non-finite `pr` guard in `composition()` —
  prevents a single corrupt `prices_raw.close`/`fact_returns.pr` from emitting `NaN` and breaking the
  whole JSON response; (2) `Number.isFinite` guard in the grid's `pct()`/`retClass()`. Deferred: a DB
  integration test for the latest-`as_of` `DISTINCT ON` pick. 143 api + 78 console tests, eslint 0/0,
  tsc + build green. Status → done.
