# Story: Explorer enrichment — price, volume, market cap, country, multi-source classification

Status: done

<!-- Created via bmad-create-story (2026-06-18). Operator: "the explorer view is too simple it does
not show price, mkt cap, volume, currency, country, the multiple industry classifications." NOT part
of an epic decomposition — like the other Q-module console enhancements (classification-multisource,
nasdaq100-universe) this is tracked as a standalone artifact, not in sprint-status.yaml's epic list. -->

## Story

As the **operator of QRP**,
I want **the Securities Explorer (the list view) and the security-detail view to surface each
security's latest price, trading volume, market cap, currency, country, and industry classification
(including which source classified it)**,
so that **I can size up and compare securities at a glance from the warehouse data already loaded —
without opening each detail page or running a query — and see that classification now comes from
multiple sources**.

## Why (current state — the list is too thin)

The **Explorer LIST** (`apps/web/app/sym/explorer/page.tsx`) currently renders only **5 columns** —
Ticker · Name · Exchange (MIC) · Ccy · Status (`page.tsx:80-98`). No price, no size, no sector. The
backing API (`SecurityRow` / `gateway.securities()`) returns exactly those six scalar fields and
nothing else. That is the core of the complaint: the list shows master metadata but none of the
numbers that let you actually read the universe.

The **DETAIL view** (`apps/web/app/sym/securities/[figi]/page.tsx`) is already richer — it shows EOD
close, market cap (USD + LCY), shares outstanding, the GICS sector/industry/sub-industry breadcrumb,
and the returns table. But it still **omits volume and country**, and it **hides the classification
source** even though `gics_scd` is now source-tagged (financedatabase / b3 / sec_sic / fmp /
yahoo_profile / llm — the recent multi-source classification work).

**Everything requested is already in the warehouse** (probed 2026-06-18) — this is a surfacing
story, not an ingestion one. No migration, no new data source.

| Requested field | Source of truth | Already exposed? |
|---|---|---|
| Price (EOD close) | `prices_raw.close` (+ `session_date`) | detail ✓ · **list ✗** |
| Volume (EOD) | `prices_raw.volume` (BIGINT) | **nowhere ✗** |
| Market cap | `fundamentals.market_cap_usd` / `market_cap_lcy` | detail ✓ · **list ✗** |
| Currency | `securities.currency_code` | list ✓ · detail ✓ (already there) |
| Country | `exchange.country` / `exchange.country_iso` (join via `securities.mic`) | **nowhere ✗** |
| Industry classification | `gics_scd` (sector/industry/sub-industry **+ `source`**, SCD) | detail (names only, **source hidden**) · **list ✗** |

## Scope decision (documented — operator is away; decided with rationale, not deferred to a question)

**"the multiple industry classifications" is read as: surface the GICS classification AND its
multi-source provenance** — because (a) the project just invested heavily in making classification
multi-source (financedatabase → b3 → sec_sic → fmp → yahoo_profile → llm, source-tagged in
`gics_scd`), and (b) the detail view today shows the GICS *names* but hides *which source* supplied
them. Concretely:

- **LIST view:** add a **Sector** column (the effective `gics_scd.sector_name`) — the one
  classification level that is scannable in a dense table. (Industry/sub-industry and per-source
  detail belong on the detail page, not in a 50-row list.)
- **DETAIL view:** keep the existing sector → industry → sub-industry hierarchy, **add the effective
  source tag**, and add a **"Classification by source"** breakdown listing each source's latest
  recorded classification for the security (effective + any superseded source rows still in
  `gics_scd`). THIS is the "multiple industry classifications" surfaced in full.

**Out of scope (documented):** (1) **Live quotes** — price/volume here are **EOD** (`prices_raw`
latest session). A live price source exists (`gateway.quotes()`, QH.2) but fanning it out per row of
a 50-row list is the heatmap's bounded-fan-out problem, not this story's; a LIVE toggle on the
explorer is a clean follow-up. (2) A literal side-by-side of **un-normalized foreign taxonomies**
(raw Yahoo sector vs SIC vs GICS) — all sources are already normalized to the GICS sector taxonomy
in `gics_scd`, so "by source" shows the normalized GICS value each source assigned, which is the
faithful and buildable reading. (3) No new fundamentals/market-cap ingestion — market cap stays as
loaded (NULL where no fundamentals/FX; render gracefully).

## Acceptance Criteria

1. **List API enrichment (`SecurityRow` + `gateway.securities()`).** Each list row additionally
   carries: `price` (latest EOD close, nullable) + `session_date`; `volume` (latest EOD, nullable);
   `market_cap_usd` (nullable); `country` + `country_iso` (from `exchange`, nullable); `sector` (the
   effective `gics_scd.sector_name`, nullable). The existing fields (figi, ticker, name, mic,
   currency, status) and their values are unchanged. Every new field is NULL-safe (a security with
   no price / no fundamentals / no classification / unmapped MIC returns `null`, never errors).
2. **List API performance is not regressed.** The enrichment joins are added to the **ROWS** query
   only. The **`count(*)`** query and the **search `WHERE`** keep using the lean `_SEC_FROM`
   (ticker/name laterals only) — the new price/volume/fundamentals/exchange/gics joins must NOT be
   added to `_SEC_FROM` (they would run for every matched row during counting). The per-row
   enrichment is bounded by the existing `LIMIT`, and uses index-supported lookups (the `prices_raw`
   / `fundamentals` latest-row reads ride their PKs; `exchange` is a PK join on `mic`).
3. **List UI (`explorer/page.tsx`).** The table renders the new columns alongside the existing ones:
   **Sector**, **Price** (with session_date as a hover title), **Volume**, **Mkt cap (USD)**,
   **Country** — plus the existing Ticker · Name · Exchange · Ccy · Status. Numeric columns are
   right-aligned + `tabular-nums`, formatted compactly (price via `toLocaleString`; volume + market
   cap via the compact `fmtCap`-style helper). NULL renders as `—`. Search, debounce, pagination,
   and the row→detail link are unchanged.
4. **Detail API enrichment (`SecurityDetail` + `gateway.security_detail()`).** The detail response
   additionally carries: `volume` (latest EOD, alongside `price`); `country` + `country_iso`; the
   effective classification `source`; and `classifications` — a list of `{source, sector,
   industry, sub_industry, effective}` rows, one per distinct source that has classified the
   security (latest row per source from `gics_scd`, `effective=true` for the currently-effective
   one). Existing fields/values unchanged.
5. **Detail UI (`securities/[figi]/page.tsx`).** The view shows **Volume** (a new metric cell or
   beside Close), **Country** (in the MIC · currency · status meta line), the **effective source**
   next to the classification breadcrumb, and a **"Classification by source"** section listing the
   per-source breakdown. The existing close/market-cap/shares cards and returns table are unchanged.
6. **Typed contract synced + no regressions.** The Pydantic models (`SecurityRow`, `SecurityDetail`,
   a new `ClassificationBySource` model) are updated; `npm run gen:types` is run against the running
   API to refresh `apps/web/lib/api-types.ts`, AND the **local** `Row` / `Detail` types in the two
   pages (the actual consumption point) are updated to match. `tsc`, `eslint`, and `next build` are
   green; `uv run pytest` (API) green.
7. **Tests.** DB-free API gateway tests (fake conn, the `test_sym_quotes.py` pattern) for the
   enriched `securities()` and `security_detail()` — including a fully-populated row, a row with
   NULL price/fundamentals/classification, and the multi-source `classifications` breakdown
   (≥2 sources). A console vitest test (`apps/web/__tests__/explorer.test.tsx`) renders the enriched
   table from a mocked fetch and asserts the new columns appear and degrade to `—` on nulls. No new
   runtime dependency (frontend or backend).

## Tasks / Subtasks

- [x] **Task 1 — List API: enrich `SecurityRow` + `gateway.securities()`** (AC: 1, 2)
  - [ ] `router.py`: extend `SecurityRow` with `price: float | None`, `session_date: str | None`,
    `volume: int | None`, `market_cap_usd: float | None`, `country: str | None`,
    `country_iso: str | None`, `sector: str | None`.
  - [ ] `gateway.py securities()`: leave `_SEC_FROM`, the `count(*)`, and the search `WHERE`
    UNCHANGED. In the **rows** query only, append: `LEFT JOIN exchange ex ON ex.mic = s.mic`;
    `LEFT JOIN LATERAL (SELECT close, volume, session_date FROM prices_raw WHERE composite_figi =
    s.composite_figi ORDER BY session_date DESC LIMIT 1) px ON TRUE`; `LEFT JOIN LATERAL (SELECT
    market_cap_usd FROM fundamentals WHERE composite_figi = s.composite_figi ORDER BY as_of_date DESC
    LIMIT 1) fu ON TRUE`; `LEFT JOIN LATERAL (SELECT sector_name FROM gics_scd WHERE composite_figi =
    s.composite_figi ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1) gx ON TRUE`. Select +
    map the new columns into each row dict (float()/int() coercion + None-guards, matching the
    existing `security_detail` coercion style).
- [x] **Task 2 — List UI: enrich the explorer table** (AC: 3)
  - [ ] Update the local `Row` type and add the new `<th>`/`<td>` columns. Reuse/lift a compact
    number formatter (the detail page's `fmtCap` — extract to `apps/web/lib/format.ts` or inline a
    matching helper; do NOT duplicate divergent logic). Price via `toLocaleString(undefined,
    {maximumFractionDigits: 2})`, NULL → `—`. Keep the `colSpan` on the "No matches" row in sync with
    the new column count.
- [x] **Task 3 — Detail API: enrich `SecurityDetail` + `gateway.security_detail()`** (AC: 4)
  - [ ] `router.py`: add `volume: int | None`, `country: str | None`, `country_iso: str | None`,
    `source: str | None` to `SecurityDetail`; add a `ClassificationBySource` model (`source: str`,
    `sector: str | None`, `industry: str | None`, `sub_industry: str | None`, `effective: bool`) and
    a `classifications: list[ClassificationBySource]` field.
  - [ ] `gateway.py security_detail()`: add `volume` to the existing `prices_raw` read; add an
    `exchange` lookup by `master.mic` for country; replace the single-row gics read so it ALSO
    returns `source`; add a per-source query: `SELECT DISTINCT ON (source) source, sector_name,
    industry_name, sub_industry_name, (valid_to IS NULL) AS effective FROM gics_scd WHERE
    composite_figi = %s ORDER BY source, (valid_to IS NULL) DESC, valid_from DESC` → map to
    `classifications`. Keep `sector`/`industry`/`sub_industry` (effective) as today + add `source`.
- [x] **Task 4 — Detail UI: volume, country, source + per-source breakdown** (AC: 5)
  - [ ] Update the local `Detail` type; render volume, country, the effective source tag on the
    classification line, and a "Classification by source" list. Existing cards/returns unchanged.
- [x] **Task 5 — Typed contract + verify** (AC: 6)
  - [ ] `npm run gen:types` (API is running on :8001) to refresh `lib/api-types.ts`; reconcile the
    local page types. Run `uv run pytest` (API), `npm test` + `npx tsc --noEmit` + `npm run build`
    (web). All green.
- [x] **Task 6 — Tests** (AC: 7)
  - [ ] API: `services/api/tests/test_sym_explorer.py` (or extend an existing sym test) — DB-free
    fake conn (mirror `test_sym_quotes.py`'s `_Conn`), exercise `securities()` (populated + all-null
    enrichment) and `security_detail()` (incl. ≥2-source `classifications`, effective flag).
  - [ ] Console: `apps/web/__tests__/explorer.test.tsx` (vitest + @testing-library) — mock fetch,
    assert the new columns render with values and `—` on nulls.

## Dev Notes

### Current state of files being touched (read in story prep — exact anchors)

- **`apps/web/app/sym/explorer/page.tsx`** (UPDATE) — client component. Local `Row` type (lines
  6-13), debounced fetch of `/api/sym/securities?limit&offset&q` (lines 24-48), 5-column table
  (`<thead>` 79-85, `<tbody>` 87-108), pagination (112-127). `colSpan={5}` on the empty row
  (line 103) must grow with the new columns. Loading/abort idiom (the `alive` flag) is fine — keep it.
- **`apps/web/app/sym/securities/[figi]/page.tsx`** (UPDATE) — **server** component (`async`, uses
  `apiGet`). Local `Detail` type (lines 4-25), helpers `pct`/`retClass`/`fmtCap` (27-40), the four
  metric cards (88-115), classification breadcrumb (76-78), meta line (80-85). `fmtCap` (34-40) is
  the compact formatter to reuse for volume + market cap.
- **`services/api/src/qrp_api/modules/sym/router.py`** (UPDATE) — `SecurityRow` (115-121),
  `SecuritiesPage` (124-128), `FundamentalsInfo` (136-141), `SecurityDetail` (152-165). Endpoints:
  `GET /securities` (312-319) and `GET /securities/{figi}` (322-327). Add the new fields + the new
  `ClassificationBySource` model here.
- **`services/api/src/qrp_api/modules/sym/gateway.py`** (UPDATE) — `_SEC_FROM` (377-389, **leave
  lean**), `securities()` (391-436), `security_detail()` (501-581). The `security_detail` coercion
  style (float()/None-guards, `.isoformat()` on dates) at 547-581 is the pattern to mirror.

### Key constraints (meticulous — the load-bearing ones)

- **Performance: enrichment joins go in the ROWS query ONLY, never `_SEC_FROM`.** `_SEC_FROM` is
  shared by the `count(*)` and feeds the search `WHERE` (which searches ticker/name). Adding the
  price/fundamentals/gics/exchange joins to `_SEC_FROM` would execute them for *every* matched row at
  count time — a real regression at thousands of securities (NFR-5: fast reads at scale). Append the
  new joins after `{self._SEC_FROM} {where}` in the rows SELECT only.
- **EOD, not live.** Price + volume come from `prices_raw` (latest `session_date`). Do NOT call
  `gateway.quotes()` / the Yahoo path from the list or detail — live is explicitly out of scope
  (see Scope decision). This keeps the list a pure warehouse read (the detail page's footer promise:
  "every number ties to the warehouse").
- **NULL-safe everywhere.** Coverage is partial by design — a security may have no price (unpriced),
  no fundamentals (no market cap), no classification (the residual unclassified set), or an unmapped
  MIC (no exchange row). Every new field must coerce to `null`/`—`, never raise. Mirror the existing
  `float(x) if x is not None else None` guards.
- **`gics_scd` is precedence-merged: ONE effective row per figi.** The "by source" breakdown
  reconstructs each source's latest opinion via `DISTINCT ON (source)`. Honesty caveat for the dev:
  AC5's *in-place provenance upgrade* (a higher source with the SAME sector upgrades the existing
  row's `source` in place, no new row) means a same-sector lower source's contribution is not
  separately retained — so "by source" shows the effective source + any *superseded-by-different-
  level* source rows still in the table. Label the section honestly ("as recorded per source"); do
  not claim a complete audit of every source ever consulted.
- **Next.js 16 is NOT the Next you know.** Per `apps/web/AGENTS.md`: this repo runs Next 16 with
  breaking changes — **read `node_modules/next/dist/docs/` before writing/altering any Next code**
  (server vs client component rules, `params` is a Promise in the detail page, etc.). The detail page
  is a server component; the explorer list is a client component — preserve that split.
- **Typed contract is generated.** `npm run gen:types` runs `openapi-typescript
  http://127.0.0.1:8001/openapi.json -o lib/api-types.ts` (needs the API running — it is, on :8001).
  BUT these two pages use **local** `Row`/`Detail` types, not the generated ones (same as
  `heatmap-view.tsx`); update the local types to match the new models. Keep them consistent.
- **No new dependency** — `dev-story` halts on one. All data is SQL over existing tables; UI is
  existing React/Tailwind primitives.

### Testing standards

- **API:** DB-free, fake-conn pattern — mirror `services/api/tests/test_sym_quotes.py` (`_Conn`
  returning canned rows; `DbSymGateway(conn).securities(...)` / `.security_detail(...)` called
  directly). `security_detail` issues several `c.execute(...)` calls, so the fake conn must dispatch
  per query (match on SQL substring or a scripted result queue) — see how `_Conn` is built in
  `test_sym_quotes.py` / `test_sym_live_heatmap.py` and extend it. Each new test fails without its
  change (pin the new fields + the null-degradation + the multi-source breakdown).
- **Console:** vitest + @testing-library (`apps/web/__tests__/`, e.g. `heatmap-view.test.tsx` for the
  fetch-mock + render pattern). New `explorer.test.tsx`: mock the `/api/sym/securities` fetch, render
  `ExplorerPage`, assert the new column headers + a populated row + a null-degraded row.
- Run: `uv run pytest` (from `services/api` or repo root per the existing setup) and `npm test` /
  `npx tsc --noEmit` / `npm run build` (from `apps/web`).

### Project Structure Notes

- All changes are surfacing-only: `router.py` (+1 model), `gateway.py` (2 methods), 2 web pages, 2
  new test files, regenerated `lib/api-types.ts`. **No migration, no schema change, no new data
  source, no sym-package change.** The read-only sym connection already SELECTs these tables.
- Deferred/ledger after this story: a **LIVE price toggle** on the explorer (reuse `gateway.quotes()`
  + the heatmap's bounded fan-out); sortable/filterable columns (sort by mkt cap, filter by
  country/sector); per-source classification on the LIST (kept to detail here for density).

### References

- [Source: apps/web/app/sym/explorer/page.tsx:6-13,79-108] — current list type + 5-column table.
- [Source: apps/web/app/sym/securities/[figi]/page.tsx:4-25,34-40,76-115] — detail type, `fmtCap`, cards.
- [Source: services/api/src/qrp_api/modules/sym/router.py:115-165] — `SecurityRow`/`SecurityDetail` models.
- [Source: services/api/src/qrp_api/modules/sym/gateway.py:377-436,501-581] — `_SEC_FROM`, `securities()`, `security_detail()`.
- [Source: packages/sym/migrations/deploy/exchange.sql:9-21] — `exchange(mic, country, country_iso, currency_code)`.
- [Source: packages/sym/migrations/deploy/price_storage.sql:13-24] — `prices_raw(close, volume, session_date, currency_code)`.
- [Source: packages/sym/migrations/deploy/gics_scd.sql:17-31] — gics_scd columns incl. `source`, `valid_from/to`.
- [Source: packages/sym/src/sym/classification/gics.py SOURCE_PRECEDENCE] — the 6-source precedence ladder.
- [Source: _bmad-output/implementation-artifacts/classification-multisource.md] — multi-source classification design (the "multiple" sources).
- [Source: services/api/tests/test_sym_quotes.py] — DB-free fake-conn API test pattern.
- [Source: apps/web/__tests__/heatmap-view.test.tsx] — vitest fetch-mock + render pattern.
- [Source: apps/web/AGENTS.md] — Next.js 16 breaking-changes warning (read the bundled docs first).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Amelia / bmad-dev-story, autonomous full-loop while operator away)

### Debug Log References

- API: `uv run pytest` → 97 passed (incl. 7 new `test_sym_explorer.py`).
- Web: `npm test` → 43 passed (incl. 2 new `explorer.test.tsx`); `npx tsc --noEmit` clean; `npm run lint` clean; `npm run build` green.
- Live end-to-end (running stack): list + detail enrichment confirmed against the real DB (Samsung ₩322000 / vol 30.1M / $987B / South Korea / IT; HON Industrials/US/$229.58, effective source sec_sic).

### Completion Notes List (2026-06-18)

**Backend** — `router.py`: `SecurityRow` +7 fields (price, session_date, volume, market_cap_usd,
country, country_iso, sector); `PriceInfo` +volume; `SecurityDetail` +country/country_iso/source +
`classifications: list[ClassificationBySource]` (new model). `gateway.py securities()`: enrichment
`LEFT JOIN exchange` + 3 LATERALs (latest price/fundamentals/effective-gics) added to the **rows
query only** (count + search WHERE stay on lean `_SEC_FROM` — the AC2 perf guard). `security_detail()`:
+volume on the price read, +exchange country lookup, +source on the effective gics row, +a
`DISTINCT ON (source)` per-source breakdown.

**Frontend** — new `lib/format.ts` (`fmtCompact`/`fmtPrice`, shared so list + detail format
identically; the detail's old inline `fmtCap` is now an alias). `explorer/page.tsx`: +Sector, Country,
Price, Volume, Mkt cap columns (10 total, colSpan synced), all NULL→"—". `securities/[figi]/page.tsx`:
+Volume card, +Country in the meta line, +"via {source}" tag, +"Classification by source" table.
`gen:types` refreshed `lib/api-types.ts`; local page types updated to match. Next 16 server/client
split preserved (list = client, detail = async server component).

**Tests** — `test_sym_explorer.py` (7): enriched list mapping + null-degradation, the count-query
perf guard, the **rows-query JOIN-before-WHERE SQL-order guard** (regression for the bug below), detail
enrichment + multi-source breakdown, null-safe detail, unknown-figi. `explorer.test.tsx` (2): renders
the new columns + values, null row degrades (≥7 em-dashes).

### Review Findings (independent adversarial review, 2026-06-18)

- **HIGH (found by LIVE verification, fixed) — search returned HTTP 500 (SQL `SyntaxError`).** The
  enrichment `LEFT JOIN`s were initially emitted *after* the `{where}` clause; Postgres rejects a JOIN
  after WHERE. The no-query path worked only because `where=""`. **Fixed:** moved the joins between
  `_SEC_FROM` and `{where}`. Caught because the DB-free fake-conn tests don't validate SQL structure —
  added `test_securities_rows_query_places_enrichment_joins_before_where` as a permanent guard, and
  re-verified the live `q=HON` search now returns 200.
- **LOW (fixed) — vitest null assertion was weak** (`getAllByText("—").length > 0` could pass even if
  enrichment cells didn't degrade). Strengthened to `>= 7` (the null row's enrichment cells).
- **LOW (out of scope, pre-existing) — detail "Market cap (USD)" can render `$—`** when fundamentals
  exist but `market_cap_usd` is NULL. The diff only re-aliased `fmtCap`; this line predates the story.
  Ledger if it bothers; trivial.
- Adversarial pass otherwise found **no High/Med correctness bugs** — unpack arity, `px` 3-tuple
  migration, DISTINCT-ON ordering, `master[1]` MIC lookup, model type match, and the perf guard all
  verified correct and test-pinned.

### File List

- `services/api/src/qrp_api/modules/sym/router.py` (UPDATE) — `SecurityRow`/`PriceInfo`/`SecurityDetail` + `ClassificationBySource`.
- `services/api/src/qrp_api/modules/sym/gateway.py` (UPDATE) — `securities()` enrichment joins (rows-only) + `security_detail()` volume/country/source/by-source.
- `apps/web/lib/format.ts` (NEW) — shared `fmtCompact`/`fmtPrice`.
- `apps/web/app/sym/explorer/page.tsx` (UPDATE) — enriched list columns.
- `apps/web/app/sym/securities/[figi]/page.tsx` (UPDATE) — volume/country/source + classification-by-source.
- `apps/web/lib/api-types.ts` (REGEN) — refreshed from the new OpenAPI schema.
- `services/api/tests/test_sym_explorer.py` (NEW) — 7 gateway tests.
- `apps/web/__tests__/explorer.test.tsx` (NEW) — 2 console tests.

### Change Log

- 2026-06-18: Implemented explorer-enrichment (Tasks 1-6). List + detail now surface price, volume,
  market cap (USD), country, and GICS sector with multi-source provenance. Surfacing-only (no
  migration/new source). Fixed 1 High (search-path SQL JOIN-after-WHERE 500, found via live verify) +
  1 Low test strengthening; 1 Low pre-existing left out of scope. 97 API + 43 web tests green; tsc,
  eslint, build green; verified live against the running stack. Status → done.
