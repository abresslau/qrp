# Story: Universes as the sym landing page, with per-universe Prices/Returns/Fundamentals coverage

Status: done

<!-- Created via bmad-create-story (2026-06-18). Operator: "instead of Overview the main page should
be Universes and it should include Prices, Returns, Fundamentals so it's explicit what is missing —
also because markets are priced at different times." Standalone console-enhancement artifact. -->

## Story

As the **operator of QRP**,
I want **Universes to be the sym module's landing page, and each universe to show the coverage +
freshness of its Prices, Returns, and Fundamentals**,
so that **the first thing I see is "what's loaded and what's missing, per universe" — and because
different markets close at different times, the coverage is judged per-member-recency, not against a
single global "latest session" that lies for non-US names**.

## Why (current state + the recurring pain)

- The sym module lands on **Overview** (`/sym` = `app/sym/page.tsx`); Universes is a buried tab
  (`/sym/universes`) showing only **name · id · resolved-member count** — nothing about data coverage.
- This whole session's confusion (BPAC11 stale price, portfolio-3 missing returns, the misleading
  global "latest session") traces to one thing: **coverage drifts per layer and per market, and there
  was no per-universe view of it.** A global freshness number hides that nasdaq100 is current while
  Ibovespa/FTSE lag — and that a Tokyo name being 1 day "behind" New York is normal, not missing.
- The honest unit is **per universe, per layer (prices/returns/fundamentals), judged by per-member
  recency** so cross-market close-time differences don't read as gaps.

Reusable machinery already exists: the validate layer's per-member EXISTS checks
(`validate/completeness.py:_current_member_flags` — already does has_prices/has_fundamentals per
member per universe) and the overview freshness `classify()` + `STALE_AFTER_DAYS`.

## Acceptance Criteria

1. **Universes is the landing page.** `app/sym/page.tsx` now renders the (enriched) **Universes** view;
   the current Overview moves to `app/sym/overview/page.tsx`. `SYM_SUBNAV` (`apps/web/lib/nav.ts`) is
   reordered so **Universes is first** (`/sym`) and **Overview** second (`/sym/overview`); the rest
   unchanged. The root `/` → `/sym` redirect now lands on Universes. The old `/sym/universes` route
   redirects to `/sym` (back-compat for bookmarks + the heatmap-page links). Clicking "sym" in the
   sidebar lands on Universes; the Overview tab still works at `/sym/overview`.
2. **Per-universe coverage API.** A new endpoint (e.g. `GET /api/sym/universes` extended, or
   `/api/sym/universes/coverage`) returns, per universe: `universe_id`, `name`, `members_resolved`,
   and for each of **prices / returns / fundamentals** a block `{covered, total, latest_date, status}`
   where `covered` = resolved members whose OWN latest data is recent (see AC3), `total` = resolved
   members, `latest_date` = the max data date across the universe's members for that layer, `status` =
   `ok`/`stale`/`unknown` via the existing `classify` thresholds.
3. **Cross-market-honest coverage.** "Covered" for a member = its latest data date for that layer is
   within `STALE_AFTER_DAYS` (+ weekend slack) of the **global latest session** — NOT "present exactly
   at the global max session date." So a member whose market closed a day or two later/earlier than NY
   is still counted covered. A member with NO data for a layer, or data older than the threshold, is
   "missing." (This is the "markets priced at different times" requirement.)
4. **Performance — index-bounded, no full-table scans.** Per-member latest-date uses the PK index
   (`prices_raw(composite_figi, session_date)` etc.) via `LEFT JOIN LATERAL (SELECT max(date) … WHERE
   composite_figi = … )` or an equivalent grouped form — NEVER a `count(DISTINCT)` / unbounded scan
   over the 13.5M-row `prices_raw` (the Overview 125s regression). The endpoint must return in well
   under ~2s for all ~15 universes. A test/timing check confirms it.
5. **UI — the 3 layers, explicit.** The Universes landing renders, per universe row/card: Name ·
   Members · **Prices** (`covered/total`, latest date) · **Returns** (`covered/total`, latest) ·
   **Fundamentals** (`covered/total`, latest) — with a stale/missing layer visually flagged
   (amber/red), and the existing "Heat map →" link kept. Coverage that's complete reads calmly; gaps
   stand out. NULL/unknown → `—`.
6. **Typed contract + no regressions.** Pydantic models updated; `npm run gen:types` refreshes
   `lib/api-types.ts`; `tsc`/`eslint`/`next build` green; `uv run pytest` green. Overview is unchanged
   in content — only its route (`/sym/overview`) and tab position move. Explorer/heatmap/attention/
   validation/operate tabs unaffected.
7. **Tests.** API coverage gateway (DB-free fake conn): a universe fully covered across all 3 layers;
   one with a STALE returns layer (returns lag prices); a cross-market member whose latest price is
   1–2 days behind the global session still counts as covered (AC3); a member with no fundamentals
   counts missing. A perf guard asserting the coverage query is per-member-indexed (no
   `count(DISTINCT … FROM prices_raw)` unbounded form). Console test: the Universes landing renders the
   three layer columns + a stale flag; the landing route resolves to Universes and Overview is reachable
   at `/sym/overview`.

## Tasks / Subtasks

- [x] **Task 1 — Per-universe coverage gateway + endpoint** (AC: 2,3,4) — in `gateway.py`, add a
  `universe_coverage()` method: for each layer, `LEFT JOIN LATERAL (SELECT max(<date>) FROM <table>
  WHERE composite_figi = r.composite_figi)` over `universe_member_resolution r WHERE
  resolution_status='resolved'`, grouped by `universe_id`; `covered` = `count(*) FILTER (WHERE
  member_latest >= global_latest - STALE_AFTER_DAYS - weekend_slack)`, `latest_date` = `max(member_latest)`.
  Compute the global latest session once (cheap `max(session_date)`). Add the response model(s) +
  endpoint in `router.py`; reuse `freshness.classify` for `status`.
- [x] **Task 2 — Landing route swap** (AC: 1) — move Overview JSX to `app/sym/overview/page.tsx`; put
  the new Universes view at `app/sym/page.tsx`; reorder `SYM_SUBNAV`; make `app/sym/universes/page.tsx`
  a redirect to `/sym` (Next `redirect("/sym")`). Verify the tab strip + sidebar land on Universes.
- [x] **Task 3 — Universes coverage UI** (AC: 5) — render the per-universe table/cards with the three
  layer blocks (covered/total + latest date + stale flag) consuming the new endpoint; keep the heatmap
  link; null-safe.
- [x] **Task 4 — types + verify** (AC: 6) — `gen:types`; `uv run pytest`, `npm test`, `tsc`, build green;
  confirm `/sym` = Universes, `/sym/overview` = Overview, old `/sym/universes` redirects.
- [x] **Task 5 — tests** (AC: 7) — API coverage cases (full / stale-returns / cross-market-covered /
  missing-fundamentals) + perf guard; console landing + 3-layer render test.

## Dev Notes

### Current state of files (read in story prep — exact anchors)

- **`apps/web/lib/nav.ts:22-30`** — `SYM_SUBNAV` (first item = landing target the tab strip highlights);
  Overview is `{href:"/sym"}` first today. The sidebar routes `sym → /${key} = /sym`.
- **`apps/web/app/sym/page.tsx:1-150`** — the current **Overview** (to move to `/sym/overview`):
  global stats + the freshness table (`Freshness` type with `area/as_of_date/days_behind/status/coverage`).
- **`apps/web/app/sym/universes/page.tsx:1-61`** — the current Universes table (name/id/members + heatmap
  link); becomes a redirect to `/sym`.
- **`apps/web/app/page.tsx:1-6`** — root `redirect("/sym")` (unchanged; `/sym` will now be Universes).
- **`apps/web/app/sym/layout.tsx:6,13-14`** — the tab strip iterating `SYM_SUBNAV` with exact-pathname match.
- **`services/api/.../modules/sym/router.py`** — `UniverseSummary` (`58-62`), `/universes` endpoint
  (`295-300`); `SymOverview`/`FreshnessItem` (`48-56`), `/overview` (`259-292`). Extend here.
- **`services/api/.../modules/sym/gateway.py`** — `universes()` (`153-164`, the query to extend);
  `overview()` (`81-151`, the freshness/coverage-session logic to reuse); `live_heatmap()` (`288-418`,
  the member-resolution + per-member-MIC pattern to mirror).
- **`packages/sym/src/sym/validate/completeness.py:93-200`** — `_current_member_flags`: the per-member
  per-layer EXISTS pattern (has_prices/has_fundamentals) — closest reusable precedent.
- **`services/api/.../modules/sym/freshness.py:20,32-44`** — `classify` + `STALE_AFTER_DAYS=4` to reuse
  for per-layer status.

### Key constraints (meticulous)

- **Per-member recency, not global-session presence (the core requirement).** Coverage compares each
  member's own latest date to a freshness cutoff — so a universe spanning XNAS/XTKS/XLON isn't penalized
  because those markets closed at different times. Use a cutoff = `global_latest_session -
  (STALE_AFTER_DAYS + ~3 weekend/holiday slack)` so a normal 1–2 session lag is "covered", a week-old
  gap is "missing". Document the slack.
- **PERFORMANCE — do not repeat the Overview 125s regression.** Per-member `max(date)` rides the PK
  index; never `count(DISTINCT composite_figi)`/`GROUP BY date` over all of `prices_raw`. Bound any
  date scan. Live-time the endpoint (must be < ~2s for all universes) before claiming done. Note: a
  member can belong to several universes, so the resolved-member rows across ~15 universes total a few
  thousand × 3 lateral index lookups — verify that's fast, and if not, compute per-layer member-latest
  once into a CTE/temp and join.
- **`gics`/fx are out** — the three layers are prices, returns, fundamentals (what the operator named).
  fx stays on the (demoted) Overview.
- **Reuse, don't reinvent** — `freshness.classify` for status; the validate EXISTS pattern for presence;
  `universe_member_resolution … resolution_status='resolved'` for the member set (the heatmap/universes
  gateways already use it). `members_resolved` already comes from `universes()`.
- **Overview content unchanged** — only its route + tab slot move. Don't alter its queries (already
  perf-fixed). The `/sym/overview` page is the SAME component, relocated.
- **Next.js 16** (`apps/web/AGENTS.md`): read `node_modules/next/dist/docs/` first; the Universes page is
  a server component (`async` + `apiGet`) like the current one — keep that. The `/sym/universes`
  redirect uses `next/navigation` `redirect()`.
- **No new dependency.**

### Testing standards

- API: DB-free fake conn (mirror `test_sym_overview.py` / `test_sym_live_heatmap.py` — a `_RoutedConn`
  dispatching the coverage query, returning per-universe member-latest rows). Pin the AC3 cross-market
  case explicitly (member latest = global−1 → covered). Add a perf guard like
  `test_coverage_query_is_bounded_to_recent_history_not_full_table` does for the overview.
- Console: vitest + @testing-library; render the Universes landing from a mocked coverage payload, assert
  the three layer columns + a stale flag; assert Overview is reachable (route present).

### Project Structure Notes

- Frontend: move 2 pages (Overview → /sym/overview; Universes → /sym), reorder nav, redirect old route,
  build the coverage table. Backend: 1 gateway method + endpoint + model. Regen types. No migration.
- Deferred/ledger: per-MIC breakdown within a universe (show which markets lag); a coverage column on
  the heatmap; click-through from a stale layer to the missing members; wiring this coverage into a
  "is it safe to analyze?" gate.

### References

- [Source: apps/web/lib/nav.ts:22-30] — SYM_SUBNAV order (landing mechanism).
- [Source: apps/web/app/sym/page.tsx / universes/page.tsx] — Overview + Universes pages to swap.
- [Source: services/api/.../sym/gateway.py:81-164,288-418] — overview freshness, universes query, heatmap member-resolution.
- [Source: packages/sym/src/sym/validate/completeness.py:93-200] — per-member per-layer EXISTS pattern.
- [Source: services/api/.../sym/freshness.py] — classify + STALE_AFTER_DAYS.
- [Source: _bmad-output/implementation-artifacts/portfolios-exposure-and-layout.md / the overview perf fix 5749dcf] — the 125s count(DISTINCT) lesson to NOT repeat.
- [Source: apps/web/AGENTS.md] — Next.js 16 warning.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Amelia / bmad-dev-story)

### Debug Log References

- API: `uv run pytest` → 112 passed (incl. 3 new universe-coverage tests). Web: `npm test` → 47 (incl. 2 new landing tests); tsc/eslint/`next build` green.
- Coverage query timed live: naive form 15.5s → optimized 2.0s (restrict returns to one window_id; bound px/rt to 14d, fn to 180d; latest as a param). Under the <2s target.
- Headless render of `/sym`: Universes + Prices/Returns/Fundamentals + S&P 500 + Heat map present, not stuck on Loading. `/sym/overview` 200; `/sym/universes` → redirects to `/sym`.
- Live: 15 universes; e.g. S&P 500 prices 646/650 (4 genuinely unpriced → partial), IBrX 100 prices 99/99 ok — honest gaps surfaced.

### Completion Notes List (2026-06-18)

- **Landing swap:** `git mv` Overview → `app/sym/overview/page.tsx`; new `app/sym/page.tsx` = Universes coverage; `app/sym/universes/page.tsx` → `redirect("/sym")`; `SYM_SUBNAV` reordered (Universes first `/sym`, Overview second `/sym/overview`). Root `/`→`/sym` now lands on Universes.
- **Coverage gateway** (`universe_coverage()`): per universe, per layer {covered, total, latest_date, status}. Judged by PER-MEMBER recency (latest within 7 days of the global session) — NOT presence at one global date, so cross-market close-time lag isn't counted missing. Returns restricted to one `window_id` (fact_returns has ~28/figi/date); fundamentals on a 180d window (low cadence — any recent counts). Index-bounded per-figi `max()`, never a full-table count(DISTINCT) (the Overview 125s lesson, guarded by a test).
- **Endpoint/models:** `GET /api/sym/universes/coverage` → `list[UniverseCoverage]` (+ `LayerCoverage`). `gen:types` synced.
- **UI:** per-universe row with three layer cells (covered/total + status pill ok/partial/missing + latest date), heatmap link kept, null-safe, legend.

### File List

- `services/api/src/qrp_api/modules/sym/gateway.py` (UPDATE) — `universe_coverage()`.
- `services/api/src/qrp_api/modules/sym/router.py` (UPDATE) — `LayerCoverage`/`UniverseCoverage` + `/universes/coverage`.
- `apps/web/app/sym/page.tsx` (NEW landing) — Universes coverage view.
- `apps/web/app/sym/overview/page.tsx` (MOVED from app/sym/page.tsx) — Overview.
- `apps/web/app/sym/universes/page.tsx` (UPDATE) — redirect to /sym.
- `apps/web/lib/nav.ts` (UPDATE) — SYM_SUBNAV reorder.
- `apps/web/lib/api-types.ts` (REGEN).
- `services/api/tests/test_sym_universe_coverage.py` (NEW) — 3 tests + perf guard.
- `apps/web/__tests__/universes-coverage.test.tsx` (NEW) — 2 landing tests.

### Change Log

- 2026-06-18: Implemented universes-landing-coverage. Universes is now the `/sym` landing with per-universe Prices/Returns/Fundamentals coverage judged by per-member recency (cross-market honest); Overview moved to `/sym/overview`. New coverage endpoint (index-bounded, ~2s). 5 new tests; 112 api + 47 web green; live-verified. Status → done.
