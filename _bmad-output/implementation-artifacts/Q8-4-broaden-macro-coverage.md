# Story Q8.4: Broaden macro coverage — US Treasury, OECD, Eurostat (+ restatement visibility)

Status: done

## Story

As Andre (the operator),
I want the macro module to carry indicators from sources beyond World Bank + ECB — US Treasury (daily + monthly), OECD and Eurostat (monthly) — with restatements made visible,
so that the macro database is deep enough to be a real FR-21 signal input (the recorded "develop the databases" priority) instead of a 13-series curated spike.

## Background + scope decision

Epic Q8 Story Q8.4 `[NEW]` (epics-qrp-roadmap.md): *"add indicators/sources beyond World Bank + ECB (e.g. a FRED adapter when reachable, US Treasury); each source-attributed; monthly/daily frequencies handled."*

**Env probe 2026-06-11 (all verified with real payloads — see Verified source contracts below):**

| Source | Status | Use |
|---|---|---|
| US Treasury FiscalData (`api.fiscaldata.treasury.gov`) | ✅ 200, JSON, no key, current to 2026-06-09 | IN — daily + monthly series |
| OECD SDMX (`sdmx.oecd.org/public/rest`) | ✅ 200, SDMX-CSV, no key | IN — monthly CPI per country |
| Eurostat (`ec.europa.eu/eurostat/api/dissemination/statistics/1.0`) | ✅ 200, JSON-stat 2.0, no key | IN — monthly euro-area series |
| FRED (`api.stlouisfed.org`) | ⛔ answers 400 (needs API key, none in env); keyless `fredgraph.csv` returns empty | OUT — adapter when a key exists on deploy |
| `home.treasury.gov` (par yield curve CSV) | ⛔ empty response | OUT — no yield curve; FiscalData avg interest rates are the rate proxy |
| IMF SDMX, GDELT | ⛔ blocked (curl 000) | OUT |

**Folded in (chunk-1 ledger item):** *"macro observations carry `source` but no release/vintage date — restatements indistinguishable [macro/ingest.py:38-55]"*. Minimal honest fix here: `observation.last_changed_at` stamped only when the VALUE actually changes, + a per-series `restated` count in the ingest summary. A full vintage/revision-history table stays deferred (no consumer needs point-in-time macro yet; record that explicitly in the ledger when closing this).

**Explicitly OUT of scope:** FRED adapter (no key), an Operate op for macro ingest (the O.2 executor is sym-CLI-only by design — macro ingest stays `python -m macro.ingest`), API response-model changes (none needed — keep `SeriesSummary`/`SeriesDetail` as-is so NO types regen is required), point-in-time vintage table, Q8.3 (altdata breadth — separate story; note SEC EDGAR probed 200 with a User-Agent header for when that story is created).

## Acceptance Criteria

1. **Fetchers (stdlib-only, never fabricate):** `macro/sources.py` gains `fetch_fiscaldata` (JSON, paginated), `fetch_eurostat` (JSON-stat 2.0), and OECD support via a **shared SDMX-CSV parser** that `fetch_ecb` is refactored onto (both formats are `TIME_PERIOD`/`OBS_VALUE` CSV). ECB behavior is unchanged after the refactor — including the policy-rate change-point compression — and garbled/partial rows are skipped, never invented.
2. **Curated starter set ingested, source-attributed:** ingest catalogs extended with
   - `fiscaldata`: total public debt outstanding (daily, `debt_to_penny`), average interest rates (monthly, one series each for Treasury Bills / Notes / Bonds);
   - `oecd`: CPI YoY (monthly) for USA, GBR, JPN (+ BRA if the flow serves it — if empty it is omitted by the existing no-data rule, not faked);
   - `eurostat`: euro-area HICP YoY (`prc_hicp_manr`) and unemployment rate (`une_rt_m`).
   Every series row carries its source (`worldbank|ecb|fiscaldata|oecd|eurostat`); per-series failures are attributed in the summary (the existing `_WB` try/except-per-series pattern); the existing 13 WB/ECB series still load.
3. **Frequencies handled + dated honestly:** `frequency` recorded per series (`daily|monthly|annual`); monthly `obs_date` follows the source's own dating (SDMX `YYYY-MM` → first-of-month via the existing `_parse_period`; FiscalData `record_date` stored as-is, i.e. month-end for `avg_interest_rates`) — the convention difference is documented in `sources.py`.
4. **Restatement visibility:** sqitch change `obs_restatement` adds `macro.observation.last_changed_at TIMESTAMPTZ NOT NULL DEFAULT now()`; the upsert bumps it ONLY when the value actually changes (`IS DISTINCT FROM`), an unchanged re-ingest does not touch it; `run_ingest` summary gains a per-series `restated` count; ledger item marked folded-here.
5. **Tests (first tests for this package — create `packages/macro/tests/`):** parser tests for all three new formats from embedded fixture payloads (FiscalData JSON incl. string-numbers + pagination, Eurostat JSON-stat sparse value dict, SDMX-CSV shared parser against both an ECB and an OECD sample); upsert/restatement logic (new value vs changed value vs unchanged value) against a fake recording connection. No live network in tests.
6. **Live verification:** migration deployed (Docker sqitch); `python -m macro.ingest` run — series count grows from 13 with the new sources attributed and zero fabricated rows; `/api/macro/series` serves them; the macro console page's description copy updated (it hardcodes "World Bank, ECB" twice — page + router docstring); `deferred-work.md` ledger + `epics-qrp-roadmap.md` Q8.4 status updated.

## Tasks / Subtasks

- [x] Task 1: Sqitch change `obs_restatement` (AC: 4)
  - [x] `packages/macro/db/deploy/obs_restatement.sql` (+ revert/verify), appended to `sqitch.plan` with `[macro]` dependency — copy the `client_entity [portfolios]` pattern from `packages/portfolios/db/sqitch.plan`
  - [x] Deploy via the Docker sqitch image against the `macro` DB — deployed + `sqitch verify` clean (had to start Docker Desktop and pass `MSYS_NO_PATHCONV=1` for the git-bash mount paths)
- [x] Task 2: Shared SDMX-CSV parser + ECB refactor (AC: 1) — `parse_sdmx_csv(text, ref_area=None)`; `fetch_ecb` unchanged in signature/compression/meta; `ref_area` guard added for OECD wildcard-merge protection
- [x] Task 3: `fetch_fiscaldata` (AC: 1, 2, 3) — `fetch_fiscaldata_rows` (pagination loop, `fields=` trim), `fetch_fiscaldata_debt` (scaled to USD trillions, labelled), `fetch_fiscaldata_avg_rates` (Marketable-only, Bills/Notes/Bonds; Non-marketable namesakes excluded)
- [x] Task 4: `fetch_eurostat` (AC: 1, 2, 3) — single-series shape asserted (any non-time dim with size ≠ 1 raises, so a bad pin is attributed per-series, not silently merged/omitted); sparse flat index mapped via `time.category.index`; geo label extracted from the pinned category
- [x] Task 5: Wire into ingest (AC: 2, 3, 4) — `_OECD_CPI_GEOS` + `_EUROSTAT` catalogs; `_upsert` → `(n_obs, n_restated)` with conditional `DO UPDATE … WHERE o.value IS DISTINCT FROM EXCLUDED.value` + `RETURNING (xmax <> 0)`; summary rows gain `restated`; **deviation:** unemployment is `EU:UNEMP:EU27` (geo `EU27_2020`) because Eurostat serves NO euro-area aggregate for `une_rt_m` (EA/EA19/EA20 probed empty)
- [x] Task 6: Tests (AC: 5) — `packages/macro/tests/` created: 10 source tests + 5 ingest tests, all fixture/fake-driven, no network; dev group (pytest/ruff) added to macro's pyproject matching sym's pattern
- [x] Task 7: Live run + finishers (AC: 6)
  - [x] Migration deployed; live ingest: **23 series / 12,043 obs processed (was 13/453), 5 sources, all ok, `restated: 0`** (453 pre-existing equal values re-ingested untouched — the conditional upsert proven live)
  - [x] `/api/macro/series` serves all 10 new series (UST:DEBT daily to 2026-06-09); detail endpoint + O.4 404 envelope verified; console `/macro` 200 on :3001 with the data proxied and the new copy in the SSR HTML
  - [x] Page copy + router docstring updated; ledger chunk-1 item marked folded + new Q8.4 deferral section; epic Q8.4 → `[BUILT 2026-06-11]`

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] OECD returns HTTP 404 `NoRecordsFound` for an unserved geo — the "empty → omitted" docstring/comment is FALSE (verified live with geo=ZZZ); an unserved area would surface as `ok: False` error noise, not a quiet omission. Catch HTTPError 404 in `fetch_oecd_cpi` → empty obs; other HTTP errors still raise [sources.py fetch_oecd_cpi; ingest.py _OECD_CPI_GEOS comment] (MED, blind+verified)
- [x] [Review][Patch] NaN/Infinity pass every parser (`float("NaN")`, `"inf"`, `"1e999"`; stdlib json also accepts NaN tokens), persist to DOUBLE PRECISION, then starlette's `allow_nan=False` 500s `/api/macro/series` and the console page crashes on the envelope — one bad cell takes down the whole macro page. Guard with `math.isfinite` in all three parse paths (skip as garbled) [sources.py parse_sdmx_csv, _fiscaldata_obs, fetch_eurostat] (MED, edge)
- [x] [Review][Patch] FiscalData pagination silently truncates: if the server caps `page[size]` below the requested 10000 (or returns an envelope without `data`), a capped-but-full page reads as a short page → one page ingested, reported `ok: True`. Drive the loop off `meta.total-pages`; also reject `page_size < 1` (infinite-loop guard) [sources.py fetch_fiscaldata_rows] (MED, blind+edge)
- [x] [Review][Patch] Duplicate same-period rows double-count `n` and fabricate `restated`: the second row hits ON CONFLICT against the first within the same run — a vendor restatement that never happened, corrupting exactly the signal this story introduces. Dedup per series before the upsert loop [ingest.py _upsert] (MED, blind+edge)
- [x] [Review][Patch] Migration backfills `last_changed_at` with deploy time on all pre-existing rows — the column COMMENT ("insert time, re-stamped only on change") is false for the whole pre-migration corpus, indistinguishable from a mass restatement. Change is uncommitted → rework the deploy script's COMMENT to state the backfill artifact and revert+redeploy [db/deploy/obs_restatement.sql] (LOW, blind+edge)
- [x] [Review][Patch] `UST:AVG_RATE:*` wildcard failure attribution: one try wraps fetch + all three upserts, so a mid-loop DB failure leaves earlier series `ok: True` plus a wildcard row matching no catalog id — deviates from the per-series attribution pattern AC2 cites [ingest.py run_ingest] (LOW, blind+auditor)
- [x] [Review][Patch] Spec-legal JSON-stat array encodings (`value` as array, `category.index` as array) crash with a cryptic `AttributeError` instead of a clear attributed error [sources.py fetch_eurostat] (LOW, edge)
- [x] [Review][Patch] `_parse_period` accepts trailing junk — `"2025-06-30-99"` parses as 2025-06-30 (4th part silently ignored). Reject >3 parts [sources.py _parse_period] (LOW, edge)
- [x] [Review][Patch] Stale source list survives in `macro/__init__.py` docstring ("World Bank, ECB") — the third live mention the AC's "twice" count missed (LOW, auditor)
- [x] [Review][Defer] Mid-series partial failure understates committed state: autocommitted rows persist but the summary reports `obs: 0, ok: False` for that series — accounting-under-failure needs a design (pairs with the run-log up-front ledger item) [ingest.py run_ingest/_upsert] — deferred
- [x] [Review][Defer] Quarterly/weekly SDMX periods (`2025-Q1`, `2025-W23`) are skipped as garbled — a misconfigured non-monthly dataset yields a silently-empty series (`ok: True, obs: 0`), indistinguishable from no-data. Frequency-aware period parsing when a quarterly source is actually wanted [sources.py _parse_period] — deferred

Dismissed as noise (3): sqitch revert/code asymmetry (loud UndefinedColumn, standard migration coupling); review-diff artifact omitting ledger/epic/uv.lock hunks (auditor verified all three in-tree); `uv.lock` vs Constraint 1's literal scope wording (mechanical fallout of the AC5-mandated dev group, disclosed in File List).

## Dev Notes

### Verified source contracts (probed 2026-06-11 — build to THESE, do not re-guess)

**FiscalData** — `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/{dataset}?page%5Bsize%5D=N&sort=-record_date`
- `debt_to_penny` (daily): `{"data":[{"record_date":"2026-06-09","tot_pub_debt_out_amt":"39241722848798.66",...}],"meta":{...}}`
- `avg_interest_rates` (monthly): `{"data":[{"record_date":"2026-05-31","security_type_desc":"Marketable","security_desc":"Treasury Bills","avg_interest_rate_amt":"3.690",...}}` — multiple rows per month (one per security_desc); select the field per dataset, numbers arrive as strings.
- Choose `fields=` query param to trim payloads (e.g. `fields=record_date,tot_pub_debt_out_amt`). `meta.count` / `meta.total-pages` available for pagination.
- Debt history is ~8k rows from 1993 → one `page[size]=10000` request covers it today, but implement the pagination loop anyway (it is the generic adapter).

**OECD SDMX-CSV** — `https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/{GEO}.M.N.CPI.PA._T.N.GY?startPeriod=1990-01&format=csvfile`
- Columns include `REF_AREA, TIME_PERIOD, OBS_VALUE`; `TIME_PERIOD` is `YYYY-MM`; rows may arrive DESCENDING — sort (the existing parsers already sort).
- Verified row: `...,USA,M,N,CPI,PA,_T,N,GY,2025-06,2.669213,A,,,,2`. The key is positional (`REF_AREA.FREQ.METHODOLOGY.MEASURE.UNIT_MEASURE.EXPENDITURE.ADJUSTMENT.TRANSFORMATION`): `GY` = YoY growth.
- Same `TIME_PERIOD`/`OBS_VALUE` columns as ECB csvdata → the shared parser. An unknown GEO returns no data rows → empty obs → series omitted (existing rule).

**Eurostat JSON-stat 2.0** — `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}?format=JSON&lang=en&geo=EA&...&sinceTimePeriod=1996-01`
- Verified (`prc_hicp_manr?geo=EA&coicop=CP00&unit=RCH_A`): `{"version":"2.0","value":{"0":2.5,"1":2.3,...},"id":["freq","unit","coicop","geo","time"],"size":[1,1,1,1,12],"dimension":{"time":{"category":{"index":{"2025-01":0,...}}}}}`
- `value` keys are stringified flat indices and SPARSE (missing periods absent — skip, never fill). With all non-time dims pinned to one category, flat index == time index; assert this shape.
- For `une_rt_m` pin the dimensions analogously (e.g. `geo=EA20`, `s_adj=SA`, `age=TOTAL`, `sex=T`, `unit=PC_ACT`) — probe the exact category codes during dev with one curl; if a pin 400s the API error names valid codes.

### Constraints

1. **AR-R1/AR-R2 unchanged:** macro owns its own DB; this story touches NOTHING outside `packages/macro` + console copy + planning docs. No sym reads, no cross-DB anything.
2. **stdlib-only fetchers** (`urllib.request`/`csv`/`json`) — package deps stay `fastapi/pydantic/psycopg`; do NOT add `requests`/`httpx`. Existing `_UA` + `_TIMEOUT` apply to all new fetchers.
3. **Never fabricate:** empty obs → series omitted (`_upsert` returns 0, end-of-run sweep deletes obs-less catalog rows — keep both); sparse periods skipped; per-series errors attributed, not swallowed.
4. **`obs_date` stays `obs_date`** — it is the time-series observation date, NOT an as-of/business date; the `as_of_date` canonical-naming rule does not apply to it and nothing here should introduce `asof`/`as_of` names.
5. **Durability:** `run_ingest` sets `conn.autocommit = True` (keep) — per-statement commits are real commits; tests therefore CANNOT rely on rollback-to-clean — use fake recording connections, not the live DB.
6. **Sqitch via Docker** (no local sqitch): `docker run --rm -v "C:\Projects\qrp\packages\macro\db:/repo" -w /repo sqitch/sqitch deploy db:pg://postgres:<pw>@host.docker.internal/macro` (resolve creds from `.env`).
7. **API surface frozen:** `SeriesSummary`/`SeriesDetail`/paths unchanged → no `gen:types` regen needed. IF you do end up changing any response model, regen against a FRESHLY RESTARTED API — A.1's near-miss: regenerating against the stale running process baked old paths into `lib/api-types.ts`.
8. **Console:** `apps/web/AGENTS.md` warns this Next.js version differs from training data — the only change here is description copy in `apps/web/app/macro/page.tsx` (line ~89 mentions "World Bank, ECB"), keep it to text. (Known pre-existing smell, do NOT fix here: the page's fetches don't check `r.ok` — that's the A.1-found console pattern, ledger-worthy if it bothers you, not this story.)
9. **Error envelope (O.4)** is app-wide in `qrp_api.main` — router untouched, nothing to do.
10. **Ruff line-length 100, Python ≥3.13** (`packages/macro/pyproject.toml`).
11. **Restraint:** no scheduler/Dagster hook for macro ingest in this story (would need explicit `execution_timezone` and a design pass — out of scope), no Operate op, no FRED.

### Existing code map (READ before writing)

- `packages/macro/src/macro/sources.py` (109 lines) — fetcher conventions: meta dict shape `{series_id, source, name, geo, unit, frequency}`, obs `list[(date, float)]`, pure I/O, callers persist; `_parse_period` already handles `YYYY|YYYY-MM|YYYY-MM-DD`.
- `packages/macro/src/macro/ingest.py` (97 lines) — catalog lists, `_upsert` (this story's restatement change lands here), per-series error attribution, end-of-run empty-series sweep, `__main__` runner.
- `packages/macro/src/macro/gateway.py` / `router.py` — read path; untouched except the router's module docstring copy.
- `packages/macro/db/` — sqitch project (single `macro` change today); deploy/revert/verify triple per change.
- `packages/operate/tests/test_operate_hardening.py`, `services/api/tests/test_analytics_boundaries.py` — house test style: fake recording connections, tests that assert the actual claim (e.g. params reaching SQL), stdlib pytest.

### Previous story intelligence (A.1, S.1, O.4 reviews — recurring findings to pre-empt)

- **Honest counters:** every count you report must be the thing it claims (S.1/O.2 reviews repeatedly caught counters that lied). The new `restated` count must count VALUE CHANGES only, not touched rows.
- **Tests must assert the claim:** A.1's review caught a grep-test checking one module while the AC claimed the package, and a fake that ignored SQL params. Fixture tests here should assert actual parsed values/dates, and the fake conn should capture params so the upsert test proves the conditional `last_changed_at` SQL.
- **Typed signatures:** annotate the new fetchers/helpers fully (A.1 review: "the seam is the least-typed code in the diff").
- **Docstrings must be honest:** if a capability is partial (e.g. Eurostat parser only supports single-category dims), say so in the docstring (established "honest docstring" convention from chunk reviews).

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md — Epic Q8, Story Q8.4 + "NEXT FOCUS — develop the databases" operator priority]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-1 "macro observations carry source but no release/vintage date" (folded here)]
- [Source: packages/macro/src/macro/{sources,ingest,gateway,router}.py; packages/macro/db/sqitch.plan]
- [Source: packages/portfolios/db/sqitch.plan — follow-up-change pattern (`client_entity [portfolios]`)]
- [Source: _bmad-output/planning-artifacts/architecture-qrp.md — AR-R1 DB-per-package, AR-R2 app-side reads, typed-seam/types-regen rule]
- [Source: env probes this session, 2026-06-11 — FiscalData/OECD/Eurostat verified payloads above; FRED/IMF/GDELT/home.treasury.gov blocked]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Docker daemon was down → `docker desktop start`; git-bash mangled `-w /repo` → `MSYS_NO_PATHCONV=1`.
- Port 8000/3000 are squatted (Docker Desktop proxy started this session); the QRP API is `dev:api` on **8001**, console came up on **3001**. Both started in background for live verification and left running.
- `une_rt_m` probe: EA/EA19/EA20 all return an empty geo dimension (size 0) — EU27_2020 + DE verified working; EU27_2020 configured.
- Lint: enabling sym's ruff select on macro flagged the pre-existing FastAPI `Depends` idiom (B008) → conventional per-file ignore for `router.py`; my-code findings (E501 ×3, B905) fixed properly (`zip(..., strict=True)` — a malformed `id`/`size` payload now raises and is attributed per-series).

### Completion Notes List

- **All 6 ACs met.** Live: 13 → 23 series, 453 → ~12k observations, 5 sources, every series attributed, zero fabricated rows; `restated: 0` on a run that re-ingested all 453 pre-existing values proves the equal-value-leaves-row-untouched semantics in production, not just in tests.
- **Deviation from AC2 wording:** Eurostat unemployment is `EU:UNEMP:EU27` (geo `EU27_2020`), not EA — Eurostat's `une_rt_m` serves no euro-area aggregate (probed; recorded in the ingest catalog comment + ledger).
- **Pre-existing regression-suite failure (NOT this story):** `sym` `test_durable_reviews.py::test_fx_coverage_warns_on_open_rejections` fails on clean HEAD (`from tests.test_fx_coverage import …` with no `tests/__init__.py`). Verified by stash-and-rerun; ledgered with the one-line fix; left out of this macro-only diff. All other suites green: macro 15/15 (new), api 28/28, operate 14/14, lineage 22/22, sym 543/544 (the pre-existing one).
- API response models untouched → no `gen:types` regen needed (grep: `SeriesSummary`/`SeriesDetail` unchanged).
- Vendor honesty notes ledgered: OECD JPN CPI ends 2021-06; WB euro-area CPI returns no data (never had any — `EU:HICP:EA` covers the need); ECB change-point compression can strand one stale row (+1 obs drift, real values).

### File List

- packages/macro/db/deploy/obs_restatement.sql (new)
- packages/macro/db/revert/obs_restatement.sql (new)
- packages/macro/db/verify/obs_restatement.sql (new)
- packages/macro/db/sqitch.plan (modified — `obs_restatement [macro]` appended)
- packages/macro/src/macro/sources.py (modified — shared SDMX-CSV parser; FiscalData, OECD, Eurostat fetchers; module-docstring dating convention)
- packages/macro/src/macro/ingest.py (modified — new catalogs, `_upsert` restatement counting, summary `restated`/`total_restated`)
- packages/macro/src/macro/router.py (modified — docstring source list only)
- packages/macro/pyproject.toml (modified — description; dev group pytest/ruff; ruff lint + pytest config matching sym's pattern)
- packages/macro/tests/test_sources.py (new — 10 tests)
- packages/macro/tests/test_ingest.py (new — 5 tests)
- apps/web/app/macro/page.tsx (modified — description copy only)
- uv.lock (modified — macro dev group)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — chunk-1 item folded; new Q8.4 section)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q8.4 `[BUILT 2026-06-11]`, FR-20 map line)

## Change Log

- 2026-06-11: Q8.4 implemented — three new macro sources (FiscalData, OECD, Eurostat), restatement visibility (`last_changed_at` + `restated` counter), first macro test suite (15 tests), live-verified end-to-end (DB → API → console).
