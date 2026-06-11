# Story C.1: Console submenus — sidebar sub-navigation + macro category breakdown

Status: done

## Story

As Andre (the operator),
I want the console sidebar to support submenus under each module — Perplexity-style, where the active section breaks down into sub-items — with macro as the first real case (Inflation, Rates, GDP, Employment, Debt, Population),
so that a module's content is navigable by topic instead of one undifferentiated list (23 macro series today, growing).

## Background + scope decision

Operator request 2026-06-11: *"I want to be able to access submenus, have a look at Perplexity for reference — for instance for macro it should be able to break down by inflation, rates, GDP, population…"*

**Perplexity reference (perplexity.ai blocks in-env fetching — 403; pattern from knowledge):** left sidebar with primary sections; the ACTIVE section auto-expands into indented sub-items beneath it (Finance → Markets / Earnings / Crypto; Discover → topic list). Sub-items are smaller indented links with their own active state; the parent stays highlighted. No chevrons/manual collapse needed for v1 — active-module auto-expansion IS the Perplexity behavior.

**What exists today:**
- `apps/web/components/sidebar.tsx` — flat module list from `/api/platform` (server layout fetches, passes as props; sidebar is a client component).
- `apps/web/app/sym/layout.tsx` — sym ALREADY has 7 subpages navigated by a hardcoded in-page tab strip. That tab list is the static-submenu precedent.
- `apps/web/app/macro/page.tsx` — one flat client-side series list; no category dimension exists anywhere (schema: series_id/source/name/geo/unit/frequency).

**Scope decisions:**
1. **Two submenu providers, no framework.** A console-side nav registry (`apps/web/lib/nav.ts`): sym's sub-items STATIC (single source shared with its tab strip — the tab strip STAYS, no regression); macro's sub-items DATA-DRIVEN from a new `GET /api/macro/categories`. A generic module-submenu framework is NOT built (NFR-10 just-in-time: extract when module #3 wants one — record that in the registry's header comment).
2. **Category is a declared catalog dimension**, like name/unit: every ingest catalog entry names its category; a new nullable `macro.series.category` column carries it; the categories endpoint reads DISTINCT from the DB so the submenu can never drift from the data.
3. **Population becomes real.** Andre named it; no population series exists. Add World Bank `SP.POP.TOTL` (scaled to millions, labelled — the UST:DEBT trillions precedent) and `SP.POP.GROW` (% per year) for US/BRA/EMU/GBR/JPN.
4. **Canonical categories (lower-case slugs):** `inflation, rates, gdp, employment, debt, population`. Mapping for the existing 23 series: CPI/HICP → inflation; ECB:MRR + UST:AVG_RATE:* + WB real interest rate → rates; WB GDP growth → gdp; WB unemployment + EU:UNEMP → employment; UST:DEBT → debt.
5. **OUT of scope:** server-side `?category=` filtering on `/api/macro/series` (23 rows — client-side filter; revisit at scale), manual expand/collapse chevrons, submenus for the other 7 modules (registry makes them one-liners later), lifting sym's tab strip OUT of the page (kept; sidebar submenu is additive).

## Acceptance Criteria

1. **Schema + ingest:** sqitch change `series_category` adds nullable `macro.series.category TEXT` (+ COMMENT naming the canonical set); every ingest catalog entry (WB / ECB / FiscalData / OECD / Eurostat) declares a category; `_upsert` writes it (and updates it on conflict, like name/unit); after one live ingest, zero NULL categories remain.
2. **Population series:** WB `SP.POP.TOTL` ("Population", unit `millions`, scaled /1e6, labelled conversion) and `SP.POP.GROW` ("Population growth", `% per year`) ingested for US/BRA/EMU/GBR/JPN under category `population` — empty geos omitted by the existing no-data rule, never faked.
3. **API:** `SeriesSummary` + `SeriesDetail` gain `category: str | None`; new `GET /api/macro/categories` returns `[{category, n_series}]` (DISTINCT from the DB, NULL excluded, ordered); `lib/api-types.ts` regenerated against a FRESHLY RESTARTED API (A.1 near-miss rule).
4. **Sidebar submenus:** the active module's sub-items render indented beneath it in the sidebar (Perplexity pattern); sym shows its 7 static items from the shared registry (tab strip unchanged, same single list — no duplicated literals); macro shows its categories (with `n_series` counts) fetched client-side with an `r.ok` guard (A.1 console lesson — a failed fetch shows NO submenu, never an error-envelope-as-data crash).
5. **Macro category routes:** `/macro/<category>` is URL-addressable and filters the series list to that category (unknown category → empty-state message, not a crash); `/macro` stays "all series"; the active category is highlighted in the sidebar submenu; selecting a series still loads its detail chart.
6. **Tests + live:** macro package tests — every catalog entry's category is in the canonical set; categories gateway/router tests (fake conn). Console has no test harness (lint only) — live verification: sidebar expands for macro with 6 categories, `/macro/rates` shows exactly the 6 rate series, sym submenu navigates, types-freshness clean; ledger/epics updated.

## Tasks / Subtasks

- [x] Task 1: Sqitch change `series_category` (AC: 1) — deployed + verified (nullable TEXT + canonical-set COMMENT)
- [x] Task 2: Categories in ingest (AC: 1, 2)
  - [x] `_WB` → 6-tuples (`category`, `scale` added); `_ECB`/`_EUROSTAT` entries gain category; FiscalData/OECD declare theirs at the `_record` call sites; `_record(…, category)` attaches; `_upsert` REFUSES non-canonical categories (loud, attributed) and writes/updates the column
  - [x] `SP.POP.TOTL` (millions via `fetch_worldbank(..., scale=1e-6)`, labelled) + `SP.POP.GROW` — 10 new series, all 5 geos served (incl. EMU)
  - [x] Live ingest — **deviation from "zero NULLs":** Eurostat egress broke mid-story (307 Network Error HTML from the proxy; worked this morning) so `EU:HICP:EA`/`EU:UNEMP:EU27` stay NULL until the next successful ingest; categories are declared in the catalog, no code change needed; ledgered. RESOLVED during the review round: Eurostat egress recovered and a FiscalData retry landed — ALL 33 series categorised (inflation 9 / rates 6 / gdp 3 / employment 4 / debt 1 / population 10), zero NULLs; AC1 fully met
- [x] Task 3: API surface (AC: 3) — `category` on both models; `GET /api/macro/categories` (NULL-excluded, ordered, grep-asserted in gateway SQL test); API restarted FIRST, then `gen:types` — `CategorySummary` + `list_macro_categories` verified present in `lib/api-types.ts`
- [x] Task 4: Console (AC: 4, 5) — read the bundled Next docs first: `params` is a PROMISE in this version; client pages unwrap with React `use()` (dynamic-routes.md)
  - [x] `lib/nav.ts` registry; `sym/layout.tsx` tabs now render from the shared `SYM_SUBNAV`
  - [x] `sidebar.tsx`: active-module auto-expansion (Perplexity pattern), indented sub-items with per-item active state; macro categories fetched client-side with `r.ok` guard + counts as badges; fetch failure → no submenu
  - [x] `/macro/[category]/page.tsx` (client, `use(params)`, decodeURIComponent) → `MacroBrowser category=…`; page body extracted to `components/macro-browser.tsx` with `r.ok` guards on BOTH fetches (in-passing fix per Constraint 4 — the code moved anyway); selection is DERIVED (clicked-if-visible else first-visible — no state-syncing effect, which the repo's eslint `react-hooks/set-state-in-effect` rule rejects); stale-detail guard (`shown` only when it matches the selection); unknown category → honest empty state
- [x] Task 5: Tests (AC: 6) — `test_categories.py` (catalog canonical-set, URL-safe slugs, gateway categories SQL + series category passthrough) + `_upsert` refusal/SQL tests + `run_ingest` category-attachment test (params inspected at the SQL boundary); api route-table tests (categories route exists; macro toggle-off removes the namespace). macro 32/32, api 30/30, ruff + tsc + per-file eslint clean
- [x] Task 6: Live verify + finishers (AC: 6) — categories endpoint live (6 categories); `/macro` `/macro/rates` `/macro/population` `/macro/weather` all 200 (weather = honest empty state); `/macro/rates` EXACT membership = ECB:MRR + 3×UST:AVG_RATE + 2×WB real-rate; sym page renders "Explorer" twice (tab strip + sidebar submenu, SSR-verified); operate 14 / lineage 22 / sym green (the ledgered pre-existing failure is INVOCATION-SPECIFIC — the auditor reproduced 544/544 via `pytest tests -q`; it fails only under certain rootdir/import-mode invocations); ledger + epics updated

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] Detail-fetch race wedges the panel blank: click A then B; A's late response overwrites B's detail, the `shown` staleness guard nulls the pane, and nothing refetches (sel unchanged) — stuck at "Select a series." with B highlighted. Ignore stale responses (capture sel in the effect closure) [macro-browser.tsx detail effect] (MED, blind+edge)
- [x] [Review][Patch] Double-decode crashes `/macro/%25`: Next 16's route matcher ALREADY decodes dynamic params (verified in node_modules route-matcher.js); the page's `decodeURIComponent` is a second decode — URIError on `%`-junk (no error boundary exists in the app), and validly-encoded values are corrupted. Remove the decode [app/macro/[category]/page.tsx] (MED, edge)
- [x] [Review][Patch] Category slugs flow into hrefs unencoded and the column has no shape constraint — the canonical-slug invariant lives only in Python; out-of-band SQL could plant `a/b` and break links. Add a CHECK (NULL or `^[a-z]+$`) to the (uncommitted) migration + encodeURIComponent the href [series_category.sql, sidebar.tsx] (LOW, blind+edge)
- [x] [Review][Patch] Series-fetch failure renders as a DATA FACT ("No series in category 'rates'") and the same text flashes during load — track loading/error/ready and say what actually happened [macro-browser.tsx] (LOW, edge)
- [x] [Review][Patch] Failed detail fetch shows "Select a series." while one IS selected — error rendered as wrong state, no indication [macro-browser.tsx] (LOW, blind)
- [x] [Review][Patch] One failed categories fetch at app load hides the macro submenu for the whole session (no retry on later navigation) [sidebar.tsx] (LOW, blind)
- [x] [Review][Patch] Completion-note corrections: "23 of 25 series categorised" is wrong arithmetic — live DB says 31 of 33 (8+6+3+3+1+10); and the sym-suite "1 known failure" is INVOCATION-SPECIFIC (auditor reproduced 544/544 green via `pytest tests -q`; the ModuleNotFoundError appears under other rootdir/import-mode invocations) [this story file + ledger wording] (LOW, auditor)
- [x] [Review][Patch] The `"rates"` literal at the avg-rates call site is never inspected at the SQL boundary — the run_ingest category test stubs `fetch_fiscaldata_avg_rates` to `[]` while test_categories.py's comment claims coverage [test_ingest.py] (LOW, auditor)

Dismissed as noise (2): "api-types not regenerated" (diff-exclusion artifact — auditor verified `CategorySummary` + `list_macro_categories` in the committed file); AC1 zero-NULL deviation (already documented + ledgered as the Eurostat egress outage).

### Change Request (operator, 2026-06-11 — amends AC4)

> "The submenus should be clickable without loading the content of the main menu — I don't need to click on macro to actually see the submenu. Also it should have a minimal animation, like opening down. Check how Perplexity does it."

- [x] [Change] Expand/collapse is decoupled from navigation: a chevron on the module row toggles the submenu WITHOUT navigating; clicking the module label still navigates; the active module stays auto-expanded (Perplexity: chevron/hover expands sections in place; the label is the nav target)
- [x] [Change] Minimal open-down animation (~200ms ease) on expand/collapse

## Dev Notes

### Constraints

1. **AR-R1/R2 unchanged** — macro owns its DB; the console talks ONLY to the API.
2. **Next.js version warning (CRITICAL):** `apps/web/AGENTS.md` — APIs/conventions/file structure may differ from training data; read `node_modules/next/dist/docs` BEFORE writing the dynamic route or touching layouts. Dynamic-segment `params` handling is a known breaking-change area.
3. **Types regen discipline (A.1):** response models change here → regen REQUIRED, against a restarted API on **8001** (`gen:types` targets `http://127.0.0.1:8001/openapi.json`). Port 8000/3000 are squatted by Docker Desktop this session; console dev server is on 3001.
4. **`r.ok` on every new console fetch** — the existing macro page's unchecked fetches are a known pre-existing smell (A.1 review class); do not replicate in new code. Fixing the page's two existing fetches while you're in the file is in-scope hygiene IF zero-risk, else leave.
5. **Honest counters/empty states:** category counts come from the DB, not the registry; unknown `/macro/<x>` shows "no series in this category", never a fabricated list or a crash.
6. **Category slugs are lower-case URL-safe tokens** (they appear in paths). Canonical set lives in ONE place on the Python side (module-level constant in `ingest.py`, asserted by the catalog test).
7. **Sqitch via Docker** (no local sqitch); the `obs_restatement` change from Q8.4 is the worked example of the full deploy/revert/verify + rework cycle.
8. **Ruff line-length 100, py3.13;** macro test conventions: fixture payloads + FakeConn, no network, no live-DB dependence (autocommit means no rollback cleanup).
9. **Restraint:** no chevron/collapse state, no submenu persistence, no framework extraction, no other modules' submenus, no server-side series filtering.

### Existing code map (READ before writing)

- `apps/web/components/sidebar.tsx` (53 lines) — flat list; active = `pathname === href || startsWith(href + "/")`; this is where sub-items render.
- `apps/web/app/sym/layout.tsx` (43 lines) — the 7-tab static list to lift into the shared registry (tabs use `pathname === t.href` exact match — the registry lift must keep that behavior).
- `apps/web/app/macro/page.tsx` (152 lines) — series table + SVG chart; the category filter wraps its `series` state; `fmt()` renders `unit.includes("%")` — population in `millions` renders plain numbers (fine).
- `apps/web/app/layout.tsx` — server component fetching `/api/platform`; submenu data must NOT move this to client; macro categories fetch belongs inside the client `Sidebar`.
- `packages/macro/src/macro/{ingest,sources,gateway,router}.py` — post-Q8.4 shapes: catalog tuples, meta dicts (`{series_id, source, name, geo, unit, frequency}` → + `category`), `_upsert` series-upsert column list, gateway SELECTs, `SeriesSummary`/`SeriesDetail` models.
- `packages/macro/db/` — sqitch project, 2 changes deployed (`macro`, `obs_restatement`).
- `services/api/tests/` — route-table test patterns (A.1's `test_analytics_boundaries.py` is the model for asserting the new categories route exists).

### Previous story intelligence (Q8.4, fresh — 2026-06-11)

- The Q8.4 review added `_finite()` (non-finite refusal), total-pages pagination, same-date dedup in `_upsert`, and per-series attribution — do not disturb; the catalog-tuple shapes you're extending were JUST reviewed.
- `_upsert`'s series upsert sets `name/geo/unit/frequency` on conflict — `category` joins that SET list (a recategorisation must propagate on re-ingest).
- Docker Desktop must be running for sqitch (started this session); git-bash needs `MSYS_NO_PATHCONV=1` for `-v`/`-w` mounts.
- World Bank euro-area CPI (`EMU`) returns no data as of 2026-06-11 — population for `EMU` may behave the same; the no-data rule handles it (omit, don't fake).
- Live ingest takes ~30s; counts to expect: 23 series before this story, +up to 10 population series after.

### References

- [Source: operator request, this session 2026-06-11 — Perplexity-style submenus; macro categories named: inflation, rates, GDP, population]
- [Source: apps/web/components/sidebar.tsx; apps/web/app/sym/layout.tsx; apps/web/app/macro/page.tsx; apps/web/app/layout.tsx; apps/web/AGENTS.md]
- [Source: packages/macro — Q8.4 as-built (story Q8-4-broaden-macro-coverage.md, commit cf31510)]
- [Source: services/api/src/qrp_api/main.py — PlatformResponse/ModuleInfo; apps/web/package.json — gen:types against 127.0.0.1:8001]
- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md — QH.6 (generic framework deferred; this story deliberately does NOT build it)]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Next.js bundled docs confirmed the breaking change the story warned about: `params` is a Promise; client pages must unwrap with React `use()` — `app/macro/[category]/page.tsx` does exactly that.
- Repo eslint enforces `react-hooks/set-state-in-effect`: the first cut of the selection-follow logic (setState in an effect) was correctly rejected; rewritten as derived state (`sel` = clicked-if-visible else first-visible; `shown` = detail-if-matching). The remaining 12 lint errors are a pre-existing failing baseline in untouched files (ledgered).
- Eurostat egress died mid-story (`ec.europa.eu` → 307 "Network Error" from the proxy; reachable this morning). Handled by the system as designed: per-series attributed failures, old observations intact, the 2 series excluded from the submenu until the next successful ingest.

### Completion Notes List

- **All ACs fully met (post-review):** the Eurostat egress outage resolved during the C.1 review round and a FiscalData retry landed — all 33 series categorised, zero NULLs (AC1 complete; the outage window exercised the designed failure path: attributed errors, old data intact, NULLs excluded from the submenu).
- Submenu mechanism is deliberately two bespoke providers (static registry + macro categories fetch), per the story's no-framework rule; extraction point recorded for module #3.
- `_upsert` now REFUSES non-canonical categories (they appear in URLs) — a misdeclared catalog entry becomes an attributed per-series error, never a row.
- Population series landed for all 5 geos including EMU (35 obs each; head-counts in labelled millions).
- Verification was SSR/HTTP-level (routes, exact category membership, sym submenu markup, proxy); pixel-level look is for Andre's eyes at http://localhost:3001/macro.

### File List

- _bmad-output/implementation-artifacts/C-1-console-submenus.md (this story)
- packages/macro/db/deploy/series_category.sql (new)
- packages/macro/db/revert/series_category.sql (new)
- packages/macro/db/verify/series_category.sql (new)
- packages/macro/db/sqitch.plan (modified)
- packages/macro/src/macro/ingest.py (modified — CATEGORIES, catalog shapes, _record category, _upsert guard + column)
- packages/macro/src/macro/sources.py (modified — fetch_worldbank scale param)
- packages/macro/src/macro/gateway.py (modified — category in series/observations, categories())
- packages/macro/src/macro/router.py (modified — category fields, CategorySummary, /categories route)
- packages/macro/tests/test_ingest.py (modified — category fixtures + 3 new tests)
- packages/macro/tests/test_categories.py (new — 4 tests)
- services/api/tests/test_macro_categories_route.py (new — 2 tests)
- apps/web/lib/nav.ts (new)
- apps/web/lib/api-types.ts (regenerated)
- apps/web/components/sidebar.tsx (modified — submenu rendering + macro categories fetch)
- apps/web/components/macro-browser.tsx (new — extracted page body + category filter + r.ok guards)
- apps/web/app/macro/page.tsx (modified — thin wrapper)
- apps/web/app/macro/[category]/page.tsx (new)
- apps/web/app/sym/layout.tsx (modified — tabs from shared SYM_SUBNAV)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — C.1 section)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — C.1 note)

## Change Log

- 2026-06-11: C.1 implemented — sidebar submenus (active-module expansion), macro category dimension end-to-end (schema → ingest → API → types → routes → submenu), +10 WB population series, 9 new tests. Live-verified at the HTTP/SSR level; Eurostat egress outage left 2 series uncategorised pending the next successful ingest (ledgered).
- 2026-06-11 (review round): 8 code-review patches applied (detail-fetch race guard, double-decode crash fix on `/macro/%25`, DB CHECK slug constraint + encoded hrefs, honest loading/error states, categories-fetch retry on navigation, story-text corrections, avg-rates category literal now tested) + operator change request: expand/collapse decoupled from navigation (chevron toggles in place, label navigates, active module defaults open) with a ~200ms grid-rows open-down animation. Eurostat recovered + FiscalData retry → 33/33 categorised, AC1 fully met. Suites re-green, `/macro/%25` 200, chevron + collapsed submenu SSR-verified on /macro/rates.
