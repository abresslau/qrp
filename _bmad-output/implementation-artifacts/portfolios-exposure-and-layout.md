# Story: Portfolio detail — net/gross exposure + analytics-first layout

Status: done

<!-- Created via bmad-create-story (2026-06-18). Operator: "for the portfolios is missing net exposure
and gross exposure, Risk & return analytics should be on top, move holdings to the bottom." Standalone
console-enhancement artifact (not in an epic decomposition), like the other Q-module stories. -->

## Story

As the **operator of QRP**,
I want **the portfolio detail view to show net exposure and gross exposure, with the Risk & return
analytics at the top and the holdings table at the bottom**,
so that **I read a portfolio the way I think about it — risk/return and leverage first, the position
list as supporting detail — and I can see long/short exposure at a glance**.

## Why (current state)

The portfolio detail page (`apps/web/app/portfolios/[id]/page.tsx`) currently orders sections:
**Header → Holdings table → Snapshot attribution → Contributions → Risk&Return analytics → Upload**.
So the analytics panel is buried near the bottom and holdings sit right under the header — the inverse
of how you read a book of risk. And there is **no exposure metric anywhere** — even though
`portfolios.portfolio_weight.weight` is **signed** (NUMERIC, no sign constraint → long/short/zero all
valid), so net and gross exposure are directly computable from the shown weight vector.

- **Net exposure** = Σ weight (long − short) — the directional tilt (≈1.0 for a fully-invested
  long-only book, lower/negative for net-short).
- **Gross exposure** = Σ |weight| (long + |short|) — the leverage/activity (= net for long-only;
  > net once shorts exist, e.g. 130/30 → gross 1.6, net 1.0).

The data is already in hand: `gateway.get()` fetches the shown vector's weights (`gateway.py:237-247`)
before returning `PortfolioDetail`.

## Acceptance Criteria

1. **API: exposures on `PortfolioDetail`.** `gateway.get()` computes `net_exposure = Σ weight` and
   `gross_exposure = Σ |weight|` over the **shown** weight vector (the one the response already
   carries), and `PortfolioDetail` gains `net_exposure: float | None` + `gross_exposure: float | None`.
   Both are `null` when the portfolio has no stored vector (`shown_as_of_date is None`). They reflect
   the **shown** as-of vector, so switching the as-of picker updates them. Existing fields/values
   unchanged.
2. **UI: exposures shown at the top.** The header area renders **Net exposure** and **Gross exposure**
   (as %, signed for net) near the portfolio metadata — visible without scrolling. NULL → `—`.
3. **UI: Risk & return analytics on top.** The `<AnalyticsPanel>` moves to **directly under the header
   (above everything else)** — it is the first content block.
4. **UI: holdings at the bottom.** The Holdings table (+ the Q4.5 as-of picker) moves to the **bottom**
   of the page (after analytics, attribution, contributions, and the upload form; just above the
   footer note). The as-of picker still drives `loadPortfolio` and the table still renders the shown
   vector. Net/gross exposure (top) and the holdings table (bottom) stay consistent (same shown
   vector).
5. **Resulting top-to-bottom order:** Header (+ net/gross exposure) → Risk & return analytics →
   Snapshot attribution → Contributions → Upload weights → Holdings (+ as-of picker) → footer.
6. **Typed contract + no regressions.** Pydantic `PortfolioDetail` updated; `npm run gen:types`
   refreshes `lib/api-types.ts` (the page uses `Schemas["PortfolioDetail"]`, so it picks the new
   fields up). `tsc`, `eslint`, `next build` green; `uv run pytest` (portfolios/api) green. The
   analytics panel, attribution, contributions, upload, and as-of picker behavior are unchanged — only
   their ORDER and the new exposure fields differ.
7. **Tests.** API gateway test: long-only vector → net == gross (≈ Σ weights); a long/short vector →
   net ≠ gross (e.g. weights 0.6/0.5/−0.1 → net 1.0, gross 1.2); no-vector portfolio →
   net/gross `null`. Console test: the analytics panel renders before the holdings table in document
   order, and the exposure values render (with `—` when null). No new dependency.

## Tasks / Subtasks

- [x] **Task 1 — API exposures** (AC: 1) — `router.py`: add `net_exposure`/`gross_exposure`
  (`float | None`) to `PortfolioDetail`. `gateway.py get()`: after building `weights`, set
  `net = sum(w["weight"] for w in weights)` and `gross = sum(abs(w["weight"]) for w in weights)` when
  `shown` is set, else `None`; add both to the returned dict.
- [x] **Task 2 — UI reorder + exposure display** (AC: 2,3,4,5) — in `[id]/page.tsx`: render net/gross
  exposure in the header block; move `<AnalyticsPanel>` to immediately after the header; move the
  Holdings `{p.as_of_dates.length > 0 && (...)}` block to the bottom (just before the footer `<p>`).
  Keep the snapshot-attribution, contributions, and upload blocks between analytics and holdings.
  Adjust top-margin classes so spacing stays consistent after the move (the moved blocks use `mt-6`/
  `mt-8`).
- [x] **Task 3 — types + verify** (AC: 6) — `npm run gen:types`; `uv run pytest`, `npm test`,
  `npx tsc --noEmit`, `npm run build` all green.
- [x] **Task 4 — tests** (AC: 7) — API: extend `services/api/tests/` (or the portfolios gateway test)
  with the long-only / long-short / no-vector exposure cases; console: extend
  `apps/web/__tests__/portfolios.test.tsx` (or a detail test) asserting analytics-before-holdings DOM
  order + exposure rendering.

## Dev Notes

### Current state of files being touched (read in story prep — exact anchors)

- **`apps/web/app/portfolios/[id]/page.tsx`** (UPDATE) — client component. Current section order (the
  reorder target): header `100-111`; **Holdings** `113-157` (the `{p.as_of_dates.length > 0 && (...)}`
  block + as-of `<select>` + table); snapshot attribution `159-189`; contributions `191-224`;
  **`<AnalyticsPanel pid=… />` at line 227**; upload form `229-260`; footer `262-265`. `pct`/`retClass`
  helpers `14-20` (reuse `pct` for exposures). `p.weights` is `Schemas["PortfolioDetail"]["weights"]`;
  the new `net_exposure`/`gross_exposure` arrive on `p` after gen:types.
- **`packages/portfolios/src/portfolios/router.py`** (UPDATE) — `PortfolioDetail` model `94-104`;
  `Weight` `87-91`. Add the two float|None fields.
- **`packages/portfolios/src/portfolios/gateway.py`** (UPDATE) — `get()` `208-259`; weights built at
  `244-247`, return dict `248-259`. Compute exposures from the `weights` list (signed `w["weight"]`).
- **`apps/web/components/analytics-panel.tsx`** (READ — no change) — the Risk&Return panel being moved;
  self-contained (`pid` prop, its own fetches). Moving its JSX position doesn't affect it.

### Key constraints

- **Exposures come from the SHOWN vector**, not the latest — so they stay consistent with the holdings
  table (which renders `p.weights` for `shown_as_of_date`) and update when the as-of picker changes.
  Compute in `get()` from the same `weights` it returns (single source, no separate query).
- **Signed weights.** `weight` is NUMERIC with no sign constraint — do NOT `abs()` for net; net keeps
  sign, gross uses `abs()`. A long-only book gives net == gross; the difference IS the short exposure.
- **NULL-safe.** No stored vector → `shown_as_of_date is None` → both exposures `null` → UI shows `—`.
  Mirror the existing `notional`/None handling.
- **Reorder is JSX-move only** — do not change the analytics panel, attribution, contributions, or
  upload logic; only their position and the surrounding margin classes. The holdings as-of `<select>`
  still calls `loadPortfolio(e.target.value)`; the table still maps `p.weights`.
- **Next.js 16** (`apps/web/AGENTS.md`): read `node_modules/next/dist/docs/` before altering the
  component; this stays a client component (`"use client"`).
- **Typed contract is generated** (`gen:types` → `lib/api-types.ts`); the page consumes
  `Schemas["PortfolioDetail"]`, so regen + the new Pydantic fields flow through automatically. No local
  type to hand-edit here.
- **No new dependency.**

### Testing standards

- API: portfolios gateway is DB-backed; mirror the existing portfolios/twr test pattern
  (`services/api/tests/test_twr_weight_history.py`) — a fake/recording conn or a fixture vector. Assert
  net/gross for long-only, long/short, and no-vector.
- Console: vitest + @testing-library (`apps/web/__tests__/portfolios.test.tsx` pattern — mocked fetch).
  Use DOM order (e.g. `compareDocumentPosition` or query order) to assert the analytics panel precedes
  the holdings table; assert the exposure values render.

### Project Structure Notes

- Surfacing + layout only: `router.py` (+2 fields), `gateway.py` (compute), one web page (reorder +
  exposure), regenerated `api-types.ts`, tests. No migration, no schema change, no new data.
- Deferred/ledger: per-as-of exposure history / an exposure time-series; long/short counts (# long vs
  # short); sector/factor exposure (a bigger analytics feature).

### References

- [Source: apps/web/app/portfolios/[id]/page.tsx:100-227] — the section order to reorder + header block.
- [Source: packages/portfolios/src/portfolios/router.py:87-104] — `Weight` + `PortfolioDetail` models.
- [Source: packages/portfolios/src/portfolios/gateway.py:208-259] — `get()` + the weights it already fetches.
- [Source: packages/portfolios/db/deploy/portfolios.sql] — `portfolio_weight.weight` is signed NUMERIC.
- [Source: apps/web/components/analytics-panel.tsx] — the Risk&Return panel being moved (no change).
- [Source: apps/web/__tests__/portfolios.test.tsx] — console test pattern (mocked fetch).
- [Source: apps/web/AGENTS.md] — Next.js 16 breaking-changes warning.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Amelia / bmad-dev-story)

### Debug Log References

- `uv run pytest` (api) → 103 passed (incl. 3 new exposure tests); `npm test` → 45 (incl. 2 new detail tests); tsc/eslint/`next build` green.
- Live API: portfolio 5 (long-only) → net == gross == 100% (sum-of-weights sanity = 1.0). Long/short unit case: 0.6/0.5/-0.1 → net 1.0, gross 1.2.

### Completion Notes List (2026-06-18)

- **API:** `PortfolioDetail` += `net_exposure`/`gross_exposure` (float|None); `gateway.get()` computes them from the SHOWN vector (`net = Σ weight` signed, `gross = Σ |weight|`), `None` when no vector. Tracks the as-of picker; consistent with the holdings table.
- **UI reorder:** `[id]/page.tsx` order is now Header (+ net/gross exposure chips) → Risk & return analytics → Snapshot attribution → Contributions → Upload weights → Holdings (bottom) → footer. The `<AnalyticsPanel>` moved to the top; the Holdings block (+ as-of picker) moved to the bottom — JSX-move only, no logic change.
- **Types:** `gen:types` flowed the new fields into `Schemas["PortfolioDetail"]` (the page consumes it; no local type edit).
- **Tests:** API exposure (long-only net==gross / long-short net≠gross / no-vector null); console DOM-order (analytics precedes holdings) + exposure render.

### File List

- `packages/portfolios/src/portfolios/router.py` (UPDATE) — `PortfolioDetail` += net/gross exposure.
- `packages/portfolios/src/portfolios/gateway.py` (UPDATE) — `get()` computes exposures from the shown vector.
- `apps/web/app/portfolios/[id]/page.tsx` (UPDATE) — exposure chips + analytics-first / holdings-last reorder.
- `apps/web/lib/api-types.ts` (REGEN) — new PortfolioDetail fields.
- `services/api/tests/test_portfolio_exposure.py` (NEW) — 3 exposure tests.
- `apps/web/__tests__/portfolio-detail.test.tsx` (NEW) — 2 layout/exposure tests.

### Change Log

- 2026-06-18: Added net/gross exposure to PortfolioDetail + the detail header; reordered the detail page so Risk & return analytics is on top and Holdings at the bottom. 5 new tests; 103 api + 45 web green; live-verified. Status → done.
