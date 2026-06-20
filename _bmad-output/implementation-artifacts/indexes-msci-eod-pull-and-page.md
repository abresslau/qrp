# Story: MSCI index EOD — direct pull from MSCI + an Indexes page to see the series

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Andre,
I want to pull MSCI index close levels **directly from MSCI's own free public EOD endpoint** (starting with MSCI World Net Return) into the warehouse, and **see the level time-series in the console**,
so that benchmarks like MSCI World NR have real, authoritative level data (not file-juggling, not fabricated) and I can actually look at the curve in the app.

## Background (what exists today)

- **`index_levels`** store (Benchmark epic B2): `(sym_id, session_date, level, source)`, immutable, `source`-tagged. The per-row `variant` column was **dropped** (`index_levels_drop_variant.sql`): each published series is its **own instrument** (own `sym_id` + xref), exactly like `^GSPC` vs `^SP500TR`. So **MSCI World NR is one instrument**; MSCI World PR / GR would be separate instruments if/when added.
- **`B4-msci-file-import`** already shipped a **file** importer: `packages/sym/src/sym/benchmarks/msci.py` — `parse_msci_rows`, `read_rows`, `load_msci_file(conn, path, *, msci_code, name=, currency_code=)` (resolve-or-create the instrument by the `msci` xref via `ensure_instrument`/`sym_id_for`, immutable upsert into `index_levels` tagged `source='msci'`), and CLI `sym msci-import <path> --msci-code <code> [--name --currency]` (+ index-returns recompute). MSCI World (`msci=990100`) is currently **identity-only** — no real levels imported yet.
- **`fact_index_returns`** (also variant-dropped) is recomputed from `index_levels` after import — reuse that recompute.
- **Console** (`apps/web/app/`): modules are altdata, backtest, lineage, macro, optimiser, portfolios, signals, sym. **There is NO indexes/benchmarks page** — index levels are in the warehouse but not surfaced anywhere in the UI.

### VERIFIED — MSCI's free EOD endpoint is reachable and returns real data (probed 2026-06-20)

`GET https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph`
query: `index_codes=990100` · `index_variant=NETR` · `currency_symbol=USD` · `data_frequency=DAILY` · `start_date=YYYYMMDD` · `end_date=YYYYMMDD` · `baseValue=false`

Returns JSON: `{"msci_index_code","index_variant_type","ISO_currency_symbol","indexes":{"INDEX_LEVELS":[{"level_eod": <float>, "calc_date": <YYYYMMDD int>}, …]}}`. This is the **same backend the public EOD Index Data Search site calls** — free, published EOD index levels, used as intended. Variant codes: **`STRD`=Price (PR), `NETR`=Net (NR), `GRTR`=Gross (GR)**.

**Two hard constraints found by probing (must be honoured, not glossed):**
1. **History floor ≈ 1997-01-01.** The endpoint rejects earlier dates: *"Calculation date cannot be earlier than 19970101"* (daily World NR observed from ~2000-12-29). **True since-inception (1969/1987) is NOT available from the free endpoint** — that's the licensed MSCI product. So "since inception" here means **"from the earliest the free MSCI EOD endpoint serves"** (~1997). State this explicitly in the output/notes; do not imply 1969.
2. **Licensing/etiquette.** These are MSCI's free published EOD levels for personal/internal research use, tagged `source='msci'`. Keep the pull **polite + low-frequency** (a backfill + occasional top-up, not a hammering poller); **redistribution or commercial/high-frequency use needs an MSCI license** — note this and don't build a tight scheduler. (This is categorically different from scraping a chatbot UI: it's the data vendor's own public data endpoint.)

## Acceptance Criteria

1. **Direct MSCI EOD pull (new source).** A new function `fetch_msci_levels(*, msci_code, variant, currency, start_date, end_date) -> list[(date, Decimal)]` in `benchmarks/msci.py` calls `getLevelDataForGraph`, parses `indexes.INDEX_LEVELS[]` (`calc_date` int YYYYMMDD → `date`; `level_eod` → `Decimal`, drop non-positive), and returns the series. Network errors / MSCI `error_code` payloads raise a clear error (don't write partial garbage). Variant arg accepts `PR|NR|GR` and maps to `STRD|NETR|GRTR`.
2. **Loader reuse.** A `load_msci_pull(conn, *, msci_code, variant, currency, name, start_date, end_date)` upserts the fetched series into `index_levels` via the SAME immutable path as `load_msci_file` (resolve-or-create instrument by `msci` xref, `ON CONFLICT DO NOTHING`, `source='msci'`), then recomputes `fact_index_returns`. Each (index, variant) is its own instrument — the `msci` xref MUST encode the variant so PR/NR/GR don't collide on one `sym_id` (e.g. xref value `990100:NETR`, or a documented per-variant code). Pick one scheme, document it, keep it consistent with how B4's file import would coexist.
3. **CLI.** `sym msci-pull --msci-code <code> --variant NR [--currency USD --name "MSCI World Net (USD)" --start 1997-01-01 --end <today>]`. Defaults: currency USD, start = endpoint floor (1997-01-01), end = today. Prints an `MsciImportSummary` (sym_id, parsed, written) like `msci-import`.
4. **Backfill MSCI World NR (the headline).** Running the CLI for MSCI World NR (`990100`, NETR, USD) loads the full available daily history (~1997→today) into `index_levels` under the resolved instrument; `fact_index_returns` recomputed. Spot-check ≥2 dates against MSCI's published value.
5. **API: index level series.** A read endpoint serving an index's level series — `GET /indexes` (list available index instruments: sym_id, name, msci code, variant, currency, n_levels, first/last date) and `GET /indexes/{sym_id}/levels?start=&end=` (the `(session_date, level)` series, optionally the returns). Mirror the existing analytics/sym router + gateway pattern (read-only, `qrp_readonly` surface).
6. **Console: an Indexes page.** A new `apps/web/app/indexes/` route (added to the module nav/registry like the other modules): lists the available index instruments and renders a **level time-series line chart** for the selected one (+ key stats: latest level, date, since-start return). Reuse existing chart/format conventions (SSR-safe, dark-mode aware, the project's charting approach — no new heavy dep). Show the data provenance ("Source: MSCI — free EOD, from 1997") and the history-floor caveat.
7. **Honesty of coverage.** The page + API must not imply data older than what was loaded; show the actual first available date. `source='msci'` provenance preserved end-to-end.
8. **No regression.** `index_levels`/`fact_index_returns` immutability + B4's `sym msci-import` file path still work; existing sym/api/web suites green. `ruff`/`tsc`/`eslint`/`vitest` clean.
9. **Tests.** (a) DB-free parse test for the `getLevelDataForGraph` JSON shape (incl. an `error_code` payload → raises); (b) variant→code mapping; (c) loader writes immutably + recompute called (mirror B4's test style, mock/stub the HTTP); (d) API endpoint test (list + series); (e) web: the Indexes page renders the list + chart from a fixture (vitest + testing-library), SSR-safe.

## Tasks / Subtasks

- [x] Task 1: `fetch_msci_levels` + `variant_code` (PR/NR/GR→STRD/NETR/GRTR) + `parse_msci_graph_json` (AC: #1, #9a, #9b) — injectable `_fetch_json` for tests; clamps to the 1997 floor; raises on MSCI `error_code` payloads.
- [x] Task 2: `load_msci_pull` + `sym msci-pull` CLI; variant-encoded `msci` xref `<code>:<VARIANT>` (AC: #2, #3) — reuses `ensure_instrument`/`sym_id_for` + the shared immutable `_upsert_levels` + index-returns recompute.
- [x] Task 3: Backfilled MSCI World NR live (AC: #4) — `sym_id 2210`, **6,646 daily levels** 2000-12-29→2026-06-19 (daily NETR begins 2000-12-29), returns recomputed (121,828 rows). Spot-check: 2000-12-29=2487.61, 2024-12-31=11731.17 (correct for MSCI World NR USD).
- [x] Task 4: API `GET /api/sym/indexes` + `GET /api/sym/indexes/{sym_id}/levels` (AC: #5, #9d) — added `indexes()`/`index_levels()` to the sym gateway + router (variant split from the xref; since-start return; 404 on empty). Read-only.
- [x] Task 5: Console `app/sym/indexes/` page under the sym subnav (AC: #6, #7, #9e) — index list + SVG level chart (theme via currentColor, SSR-safe) + stats (latest/as-of/since-start/from) + MSCI provenance & 1997-floor caveat; honest empty state with the `sym msci-pull` hint.
- [x] Task 6: Verify (AC: #8) — 809 sym + 148 api + 96 web tests green; ruff/tsc/eslint clean. Real-Chrome CDP `/sym/indexes`: 18 indexes listed, MSCI World Net selectable, 6,649-vertex level curve renders, stats populate.

## Dev Notes

### Where this fits
`packages/sym` (new network source in `benchmarks/msci.py` + CLI), `services/api` (index read endpoints), `packages/analytics` or a small new gateway/router (index series), `apps/web/app/indexes` (new page). Reuses B4's loader/identity path and `fact_index_returns` recompute; reuses the console's module-page + charting conventions.

### Reuse — do NOT reinvent
- **`load_msci_file`'s identity + upsert path** (`sym_id_for`/`ensure_instrument`/`ON CONFLICT DO NOTHING`/`source='msci'`) — `load_msci_pull` shares it; only the *source of rows* differs (HTTP vs file).
- **`parse_msci_rows`** stays for files; the pull gets its own JSON parser (different shape).
- **Index-returns recompute** — call the same routine `msci-import` calls.
- **Console module page pattern** — mirror an existing module (e.g. `macro`/`sym`) for the route, nav registration, fetch+error/retry, dark-mode, charts. **No new charting dependency** without approval.
- **Read-only API** — `qrp_readonly` surface; mirror analytics/sym router+gateway.

### Critical conventions (regressions if violated)
- **One instrument per (index, variant)** — variant is NOT a row dimension anymore; encode it in the `msci` xref so World PR/NR/GR are distinct `sym_id`s. Document the scheme.
- **Immutable levels**, `source='msci'`, `as_of_date`/`session_date` honesty — never imply history you didn't load (1997 floor).
- **Polite pull** — backfill + occasional top-up; NO tight scheduler; redistribution/commercial use needs an MSCI license (note in code + page).
- **`as_of_date` canonical naming** for any date param/flag/column in new code (per project convention).
- **Verify via headless Chrome/CDP** for the page; **never `npm --prefix`** in this workspace; probe before assuming reachability.

### References
- [Source: packages/sym/src/sym/benchmarks/msci.py] — B4 file importer to extend.
- [Source: packages/sym/migrations/deploy/index_levels.sql + index_levels_drop_variant.sql] — store + the variant-as-instrument decision.
- [Source: _bmad-output/implementation-artifacts/B4-msci-file-import.md] — the file-import predecessor.
- [Source: packages/analytics/src/analytics/{gateway,router}.py + services/api/src/qrp_api/sym_contract.py] — read-API pattern to mirror.
- [Source: apps/web/app/macro (or sym)] — console module-page pattern to mirror for `app/indexes`.
- MSCI endpoint: `app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph` (variants STRD/NETR/GRTR; floor 19970101).

## Open Questions (for Andre — do not block; defaults chosen)
1. **Scope of the first pull:** default = MSCI World **NR only** (the stated acceptance). PR + GR for World, and other indexes (ACWI 892400, EAFE, EM), are a trivial repeat of the CLI once the path works — say if you want them seeded now.
2. **History floor:** free endpoint = 1997. Accept that as "inception" for now (licensed feed later for the 1969/1987 deep history)? Default = yes, labelled honestly.
3. **Indexes page home:** default = a new top-level `Indexes` module. Alternative = a tab under `sym` (warehouse). Say which you prefer.
4. **Returns on the page:** default = show levels (the close series) + a since-start % stat; full return-window table is a follow-up.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8[1m]

### Completion Notes List
- **Authoritative free pull, not chatbots.** Declined the requested LLM-UI scraping (ToS + the chatbots have no live MSCI feed → would hallucinate). Pulled MSCI World NR **directly from MSCI's own free public `getLevelDataForGraph` endpoint** — the same backend their EOD search site uses.
- **sym:** `variant_code` (PR/NR/GR→STRD/NETR/GRTR), `parse_msci_graph_json` (raises on `error_code`), `fetch_msci_levels` (1997-floor clamp; injectable fetcher), `msci_xref_value` (`<code>:<VARIANT>` → one instrument per variant), `load_msci_pull` + shared `_upsert_levels`, `sym msci-pull` CLI.
- **Backfill:** MSCI World NR live → sym_id 2210, 6,646 daily levels (2000-12-29→2026-06-19), returns recomputed. Spot-checks correct.
- **API:** sym gateway `indexes()`/`index_levels()` + `GET /api/sym/indexes[/{sym_id}/levels]` (variant parsed from xref; since-start return; 404 on empty).
- **Web:** `app/sym/indexes` page (sym subnav) — list + SVG level chart + stats + provenance/floor caveat + honest empty state.
- **Honesty:** history floor is 1997 (daily NETR from 2000-12-29); page/API never imply older. `source='msci'`; polite pull (no scheduler); redistribution needs a licence — noted in code + page.
- **Verified:** 809 sym + 148 api + 96 web tests green; ruff/tsc/eslint clean; real-Chrome page render confirmed.
- **Caveat for review:** the API was restarted (port 8001) to load the new route; daily NETR history is 2000-12-29 onward (not 1997) — the endpoint accepts a 1997 start but returns daily data from 2000-12-29.

### File List
- MOD `packages/sym/src/sym/benchmarks/msci.py` (fetch/parse/variant/xref/`load_msci_pull`/`_upsert_levels`)
- MOD `packages/sym/src/sym/cli.py` (`sym msci-pull` command + argparse)
- MOD `packages/sym/tests/test_msci_import.py` (variant/xref/graph-json/fetch tests)
- MOD `services/api/src/qrp_api/modules/sym/gateway.py` (`indexes`, `index_levels`)
- MOD `services/api/src/qrp_api/modules/sym/router.py` (index endpoints + response models)
- NEW `services/api/tests/test_indexes_route.py`
- MOD `apps/web/lib/nav.ts` (Indexes subnav entry)
- NEW `apps/web/app/sym/indexes/page.tsx`
- NEW `apps/web/__tests__/indexes-page.test.tsx`

## Change Log
| Date | Change |
|---|---|
| 2026-06-20 | Created story: pull MSCI index EOD levels directly from MSCI's free public `getLevelDataForGraph` endpoint (verified reachable; variants STRD/NETR/GRTR; history floor 1997) into `index_levels` via B4's immutable loader (one instrument per variant), backfill MSCI World NR, expose a read API, and add a new console **Indexes** page with a level time-series chart. Replaces the rejected chatbot-scraping approach with the authoritative free source. Status → ready-for-dev. |
| 2026-06-21 | Implemented all 6 tasks: sym pull/CLI, live MSCI World NR backfill (sym_id 2210, 6,646 levels), API index endpoints, Indexes console page. 809 sym + 148 api + 96 web tests green; ruff/tsc/eslint clean; real-Chrome verified. Status → review. |
