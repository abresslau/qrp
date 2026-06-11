# Story Q8.3: Broaden alt-data sources — generic series model + SEC EDGAR filing activity

Status: done

## Story

As Andre (the operator),
I want the altdata module generalised beyond its single Wikimedia source — a generic entity-keyed series model plus a second, verified-reachable source archetype (SEC EDGAR regulatory-filing activity) —
so that altdata stops being a one-source spike and becomes a real FR-19 store deep enough to feed FR-21 signals (the recorded "develop the databases" priority).

## Background + scope decision

Epic Q8 Story Q8.3 `[NEW]` (epics-qrp-roadmap.md): *"the altdata schema/ingest generalises to ≥1 additional source archetype keyed by sym_id; source provenance recorded; probe-before-build per the env-source rule."*

**Env probe 2026-06-11 (real payloads — see Verified source contracts below):**

| Source | Status | Use |
|---|---|---|
| SEC EDGAR ticker map (`www.sec.gov/files/company_tickers.json`) | ✅ 200, 796KB JSON, no key (User-Agent required) | IN — ticker → CIK resolution |
| SEC EDGAR submissions (`data.sec.gov/submissions/CIK##########.json`) | ✅ 200, JSON, no key, current to 2026-05-29 | IN — per-company filing activity |
| SEC EDGAR submissions archive (`CIK…-submissions-001.json`) | ✅ 200 (AAPL: 1994→2015, 1,234 filings) | OUT of v1 ingest — `recent` block suffices; archive noted for depth later |
| GDELT, IMF SDMX | ⛔ blocked (probed in Q8.4 session, curl 000) | OUT |
| FRED | ⛔ needs API key, none in env (Q8.4 probe) | OUT |
| Job-board / GitHub / social endpoints | not probed (denied by env policy this session) | OUT — re-probe if a third archetype is wanted later |

**Chosen second archetype:** SEC EDGAR **regulatory-filing activity** — daily counts of Form 4 filings (insider-transaction activity, the dominant form: 587 of AAPL's last 1000) and 8-K filings (corporate-event intensity). Genuine alt-data in the PRD's web-scraping/regulatory family: event-driven, per-company, keyed to sym via ticker→CIK→composite_figi, full provenance (CIK recorded per series).

**The generalisation is the point, not just a second adapter.** Today's schema is wiki-shaped (`wiki_map` + `pageview(views BIGINT)`); a second source bolted on as more bespoke tables would multiply, not generalise. This story replaces the wiki-specific pair with a generic entity-keyed `series`/`observation` model (the macro package's proven shape, plus the figi key that makes altdata altdata), migrates the existing Wikimedia data in, and lands EDGAR as the first proof the model generalises.

**Explicitly OUT of scope:** archive-file backfill (pre-`recent` history); any third source (job postings etc. — re-probe then); an Operate op or scheduler for altdata ingest (same restraint as Q8.4 — stays `python -m altdata.ingest`); signal-module consumption (Q9.2, parked); sentiment/NLP on filings (counts only — never synthesize a score this story can't verify); fixing the console page's pre-existing no-`r.ok`-check fetch pattern (A.1-known smell, ledger-worthy, not this story).

## Acceptance Criteria

1. **Generic schema (sqitch change `generic_series`):** `altdata.series` (PK `(composite_figi, source, metric)`; carries `ticker`, `name`, `detail` (source-native key: wiki article / zero-padded CIK), `unit`, `frequency`) + `altdata.observation` (PK `(composite_figi, source, metric, obs_date)`, `value DOUBLE PRECISION NOT NULL`, FK→series ON DELETE CASCADE). The migration MOVES the existing Wikimedia rows in (`source='wikipedia'`, `metric='pageviews'`, `unit='views'`, `detail=article`) and drops `wiki_map`/`pageview`; revert restores the old shape from the generic tables. Row counts preserved across deploy (verify script checks the FK + shape; live check compares obs counts before/after).
2. **Fetchers split out, stdlib-only, never fabricate:** new `altdata/sources.py` (macro's proven layout) holding the moved `fetch_pageviews` plus `fetch_company_ciks` (ticker→10-digit zero-padded CIK from `company_tickers.json`) and `fetch_sec_filing_counts` (submissions `recent` block → per-`filingDate` counts for a given form set, window-filtered). Garbled rows skipped, never invented; non-finite values rejected (`math.isfinite` — the Q8.4 review lesson); SEC's required `User-Agent` set on every request.
3. **EDGAR ingested, source-attributed:** for the curated 10-ticker set, two series per company — `sec_edgar:filings_form4` and `sec_edgar:filings_8k` (daily counts, only dates with filings stored — an absent date is a true derivable zero, documented in `sources.py`). Provenance: `series.detail` = the CIK; per-ticker failures attributed in the summary (existing pattern); unresolved tickers (no figi, or no CIK) skipped + reported, never fabricated. The Wikimedia ingest still works against the generic tables, behavior unchanged.
4. **Honest window metrics for sparse series:** the gateway's 7d/30d comparison becomes sum-over-window ÷ window-days, anchored on each SERIES' own latest `obs_date` (today it averages only present rows against the global latest date — wrong for sparse count series, and the cross-series anchor misattributes staleness). For dense pageviews the number is materially unchanged; for filing counts it is the only honest rate. `attention_spike` stays `avg7/avg30` over the new definitions.
5. **API + console generalised:** `/api/altdata/series` rows gain `source`, `metric`, `unit`, and rename `article`→`detail`, `latest_views`→`latest_value` (float); detail route disambiguates the multi-series-per-figi reality: `GET /api/altdata/series/{figi}?source=…&metric=…` (404 envelope unchanged, O.4). Types regenerated via `gen:types` against a FRESHLY RESTARTED API (A.1 near-miss); `apps/web/app/altdata/page.tsx` renders the series list with source/metric visible, selection keyed by (figi, source, metric), sparkline over `value`, description copy updated (it hardcodes "v1 source: Wikimedia" today). Router/`__init__` docstrings updated (Q8.4 review caught the third stale mention).
6. **Tests (first tests for this package — create `packages/altdata/tests/`):** fixture-driven parser tests (submissions JSON → windowed per-day form counts incl. forms outside the set ignored + window edges; ticker→CIK incl. zero-padding + missing ticker; wiki timestamp parse — all embedded payloads, no network); ingest upsert + summary attribution against a fake recording connection that captures SQL params (the counters must count what they claim); gateway window-rate SQL asserted via the fake conn. Dev group (pytest/ruff) added to altdata's pyproject matching macro's pattern.
7. **Live verification + finishers:** migration deployed (Docker sqitch, `MSYS_NO_PATHCONV=1`); wiki obs count preserved post-migration; `python -m altdata.ingest` loads EDGAR series for the resolvable tickers with zero fabricated rows; `/api/altdata/series` serves both sources; console altdata page renders both; `epics-qrp-roadmap.md` Q8.3 → `[BUILT 2026-06-11]` + FR-19 map line; `deferred-work.md` gains this story's section (incl. the not-probed third-archetype note and the SIC-code breadcrumb below).

## Tasks / Subtasks

- [x] Task 1: Sqitch change `generic_series` (AC: 1)
  - [x] `packages/altdata/db/deploy/generic_series.sql` (+ revert/verify), `generic_series [altdata]` appended to `sqitch.plan` (the `obs_restatement [macro]` / `client_entity [portfolios]` pattern)
  - [x] Deploy via Docker sqitch against the `altdata` DB; record pre/post wiki obs counts — pre: 10 map / 1,210 pageviews → post: 10 series / 1,210 obs (lossless); original change's verify script reworked to schema-only assertion (its tables were retired by this change) — sqitch verify clean on both changes
- [x] Task 2: `altdata/sources.py` (AC: 2) — move `fetch_pageviews` (behavior unchanged); add `fetch_company_ciks` + `fetch_sec_filing_counts`; document the sparse-zero counting convention + the `recent`-block window honesty (~last 1000 filings, varies per company) in docstrings — one submissions fetch serves both metrics (`metrics: dict[name, frozenset[forms]]`); `_finite` guard ported from macro; `zip(strict=True)` makes a malformed payload an attributable error
- [x] Task 3: Generalise ingest (AC: 3) — `_upsert_series`/`_upsert_observations` against the generic tables; wiki catalog + EDGAR catalog (10 tickers × {form4, 8-K}); per-ticker attribution (CIK-map failure attributes ALL EDGAR rows, no wildcard); summary rows gain `source`/`metric`; macro's end-of-run empty-series sweep added
- [x] Task 4: Gateway + router (AC: 4, 5) — series list rates = sum/window-days anchored per series (kept the `avg7`/`avg30` names: with implicit zeros they ARE calendar-day averages — semantics documented in SQL + model comments); detail by `{figi}?source=&metric=` (both required); `article`→`detail`, `latest_views`→`latest_value` (float), `AltObservation.views`→`value`
- [x] Task 5: Types + console (AC: 5) — stale API process killed (it 500'd against the new schema), restarted, `gen:types` regenerated (+24/−9 in `lib/api-types.ts`); `page.tsx` reworked: selection keyed `figi|source|metric`, Series column (source · metric), spark over `value`, provenance in the detail header, new description copy; tsc + eslint clean (no new Next APIs introduced — existing client-component patterns kept)
- [x] Task 6: Tests (AC: 6) — `packages/altdata/tests/` created: 11 source + 5 ingest + 4 gateway = **20 passing** (incl. window-edge, amendment-exclusion, dup-day aggregation, CIK zero-pad, non-finite skip, mismatched-array raise, per-series attribution incl. CIK-map total failure, sweep, SQL param capture, rate-SQL claim assertions); dev group (pytest/ruff) + lint/pytest config matching macro's pattern
- [x] Task 7: Live run + finishers (AC: 7)
  - [x] Live ingest: **all 30 series ok** — 10 wikipedia (120 obs each) + 20 sec_edgar (Form 4: 3–26 filing-days, 8-K: 2–9), 1,382 obs upserted, zero failures, zero fabricated rows; DB: 30 series / 1,442 obs across 2 sources
  - [x] API verified live: list serves 30 rows with `source`/`metric`/`detail`(=CIK)/`unit`; EDGAR detail endpoint; O.4 404 envelope; 422 on missing source/metric params
  - [x] Console `/altdata` 200 on :3001 with the new copy in the SSR HTML
  - [x] `epics-qrp-roadmap.md` Q8.3 → `[BUILT 2026-06-11]` + FR-19 map + NEXT-FOCUS bullet; `deferred-work.md` Q8.3 section (SIC breadcrumb, archive depth, unprobed third archetype, revert semantics, amendment exclusion)

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] Sparse-series spike is structurally biased — anchoring count series on their own latest obs guarantees the 7d window contains an event, so a quarterly filer reports a perpetual ≈4.29× "spike". Fix (decision recorded): true-zero count series (`sec_edgar`) anchor on CURRENT_DATE with NULL-sum→0 (idle filer: avg7 0, spike honest; stale series decay — also resolves the staleness-erasure finding); lag-shaped series (wikipedia) keep the per-series anchor [packages/altdata/src/altdata/gateway.py] (HIGH, blind+edge)
- [x] [Review][Patch] Missing `filings.recent` / `items` block reads as ok:True/obs:0 — a wholly absent block (the likely shape break) must raise an attributable error, only a PRESENT-but-empty block is no-data [sources.py fetch_sec_filing_counts, fetch_pageviews] (MED, blind)
- [x] [Review][Patch] EDGAR `recent`-block truncation can write wrong counts on deep backfills: a window older than the 1000-filing cap yields partial boundary-day counts that upsert over correct rows. Guard: when the block is at cap, drop counts on days ≤ the block's earliest parsed date [sources.py fetch_sec_filing_counts] (MED, blind+edge)
- [x] [Review][Patch] TypeError-shaped garble escapes the per-row skip contract (list-valued `views`, non-string `timestamp`, non-numeric `cik_str` kills ALL EDGAR series) — catch (ValueError, TypeError) per row [sources.py] (LOW, edge)
- [x] [Review][Patch] Wikipedia article interpolated into the URL unencoded — `%`-bearing titles silently fetch a DIFFERENT article (wrong data, ok:True); quote at the boundary [sources.py _PV_URL use] (LOW, blind+edge)
- [x] [Review][Patch] CIK-map failure misattributes sym-unresolved tickers — "unresolved ticker" must take precedence over the map-failure reason [ingest.py run_ingest] (LOW, blind)
- [x] [Review][Patch] Revert script fabricates provenance — `coalesce(detail,'')` invents an empty article to satisfy NOT NULL; refuse loudly instead [db/revert/generic_series.sql] (LOW, blind+auditor)
- [x] [Review][Patch] Stale wiki-table mentions survive: `db/sqitch.conf` comment ("wiki_map/pageview carry their own labels") + epics-qrp-roadmap line 345 still lists Q8.3 as outstanding "Breadth + hardening" work (LOW, auditor)
- [x] [Review][Patch] Console honesty for the sparse archetype: "{n} days" mislabels filing-day counts; a 1-observation series shows a latest value + spike in the list but "No data." in the detail pane [apps/web/app/altdata/page.tsx] (LOW, edge)
- [x] [Review][Patch] AC6 window-edge tests missing — no fixture pins a filing exactly on `start`/`end`; an inclusive→exclusive regression would pass the suite [tests/test_sources.py] (LOW, auditor)
- [x] [Review][Defer] Lineage catalog still models the dropped `wiki_map`/`pageview` and not `series`/`observation` — Constraint 1 kept lineage out of this story; needs its own remap pass, and the bare-name keyspace collision (QL-3 ledger) is now REAL (`altdata.series`/`observation` vs `macro.series`/`observation`) — deferred, ledgered
- [x] [Review][Defer] Console fetches don't check `r.ok` (pre-existing A.1-found pattern, all pages) — this story adds new triggers (404 after sweep-between-list-and-click, 422 on missing params) — deferred, ledgered
- [x] [Review][Defer] Concurrent ingest runs can race the end-of-run sweep (autocommit; FK violation aborts the second run mid-way) — no concurrent runner exists for altdata today; same pattern as macro — deferred, ledgered
- [x] [Review][Defer] Sparkline is index-spaced — for sparse filing series the chart implies continuity through unstored true-zero gaps; needs a time-scaled x-axis — deferred, ledgered

Dismissed as noise (5): API contract change without versioning (deliberate, single-operator platform, console updated in lockstep, story-scoped); migrated obs-less series window (moot — all 10 wiki names had observations and the live ingest+sweep ran); `uv.lock` vs Constraint 1 wording (mechanical fallout of the AC6-mandated dev group, disclosed — Q8.4 precedent); Constraint 11 "verify must prove counts" (self-conflicting with AC1's one-time live check: sqitch verify must hold at ANY future time, so migration-moment counts can't live there — the durable assertions are shape+FK+absence, the count proof is the recorded live check); staleness-erasure (LOW variant resolved by the anchor patch; wiki lag is days and `as_of_date` is served).

## Dev Notes

### Verified source contracts (probed 2026-06-11 — build to THESE, do not re-guess)

**SEC EDGAR ticker map** — `https://www.sec.gov/files/company_tickers.json` (host is www.sec.gov, NOT data.sec.gov)
- Shape: `{"0":{"cik_str":1045810,"ticker":"NVDA","title":"NVIDIA CORP"},"1":{"cik_str":320193,"ticker":"AAPL",...},...}` — dict keyed by stringified rank, NOT a list. `cik_str` is an int → zero-pad to 10 for the submissions URL.
- 796KB; fetch ONCE per ingest run, build `{ticker: cik}` for the curated set only.

**SEC EDGAR submissions** — `https://data.sec.gov/submissions/CIK{cik:010d}.json`
- `filings.recent` is a column-oriented dict of parallel arrays: `form[]`, `filingDate[]` (`YYYY-MM-DD`), `accessionNumber[]`, … — 1000 entries max, newest first (AAPL: 2015-05-13 → 2026-05-29). AAPL top forms: `4` ×587, `8-K` ×105, `424B2`, `144`, `10-Q` ×33…
- Older history lives in `filings.files[]` (e.g. `CIK0000320193-submissions-001.json`, verified 200, flat dict of the same arrays WITHOUT the `filings.recent` wrapper) — OUT of v1 ingest, contract recorded for the backfill follow-up.
- Top-level extras worth knowing: `sic`/`sicDescription` per company (see SIC breadcrumb below), `tickers[]`, `name`.
- **Both hosts require a User-Agent or they 403** — reuse the existing `_UA` dict (`qrp-altdata/1.0 (personal research)` worked; SEC asks for contact info in the UA — include the operator email).
- Form matching: exact string match on the curated set (`{"4"}` / `{"8-K"}`) — do NOT prefix-match (`4/A` amendments and `8-K/A` are deliberate exclusions v1; say so in the docstring).

**Wikimedia** (existing, unchanged) — per-article daily pageviews; `_PV_URL` + `_UA` in today's `ingest.py`; timestamps `YYYYMMDD00`.

### Constraints

1. **AR-R1/AR-R2 unchanged:** altdata owns its own DB; ingest reads sym ONLY to resolve figis over the second connection (`_resolve_figi` — keep as-is); nothing outside `packages/altdata` + `apps/web/app/altdata/page.tsx` + `apps/web/lib/api-types.ts` (regen) + planning docs.
2. **stdlib-only fetchers** (`urllib.request`/`json`) — deps stay `fastapi/pydantic/psycopg`; existing 20s timeout pattern applies to the new fetchers.
3. **Never fabricate:** unresolved ticker/CIK → attributed skip; no zero-filling of absent dates (true zeros stay derivable, not stored); empty series → no series row (or swept — mirror macro's end-of-run rule if you add one).
4. **`obs_date` stays `obs_date`** (time-series observation date — the `as_of_date` canonical rule does NOT apply to it); `as_of_date` in the API = latest obs date (existing convention, keep).
5. **Durability:** `run_ingest` sets `ad_conn.autocommit = True` (keep) — tests CANNOT rely on rollback-to-clean; use fake recording connections (macro's `tests/` show the house style).
6. **Sqitch via Docker** (no local sqitch): `MSYS_NO_PATHCONV=1 docker run --rm -v "C:\Projects\qrp\packages\altdata\db:/repo" -w /repo sqitch/sqitch deploy db:pg://postgres:<pw>@host.docker.internal/altdata` (creds from `.env`; Docker Desktop may need starting).
7. **Types regen is MANDATORY here** (response models change): restart the API first, then `gen:types` — A.1's near-miss baked stale paths from a long-running process. Ports gotcha from Q8.4: 8000/3000 can be squatted by Docker Desktop proxy → API on 8001, console on 3001.
8. **Console:** `apps/web/AGENTS.md` — this Next.js differs from training data; read `node_modules/next/dist/docs/` before editing `page.tsx`. C.1's derive-don't-sync selection pattern (macro-browser) is the house style for the selection state rework.
9. **Error envelope (O.4)** is app-wide in `qrp_api.main` — router raises plain `HTTPException`, nothing else to do.
10. **Ruff line-length 100, Python ≥3.13**; copy macro's pyproject lint/pytest blocks (incl. the `router.py` B008 per-file ignore convention).
11. **Honest counters** (recurring review theme): `obs` counts rows upserted, per-series; if you report a `restated`-style count, it must count value CHANGES only. Migration verify must prove counts, not just table existence.

### Existing code map (READ before writing — all small)

- `packages/altdata/src/altdata/ingest.py` (112 lines) — `_MAP` curated tickers, `_resolve_figi` (sym read), `_fetch_pageviews` (moves to sources.py), `run_ingest` summary shape, `__main__` runner. This story's biggest rewrite.
- `packages/altdata/src/altdata/gateway.py` (65 lines) — `series()` (the window-metric SQL this story replaces — note the global-latest anchor + present-rows avg flaws) + `observations(figi)` (gains source/metric params).
- `packages/altdata/src/altdata/router.py` (61 lines) — `AltSeries`/`AltObservation`/`AltSeriesDetail` models to extend/rename; `_gateway` dependency pattern stays.
- `packages/altdata/src/altdata/db.py` — standalone `.env`-loading connector, untouched.
- `packages/altdata/db/` — single `altdata` change today; this story appends `generic_series`.
- `apps/web/app/altdata/page.tsx` (145 lines) — types from `Schemas["AltSeries"]`; selection state by figi; spark over `views`; the wiki-specific copy.
- `packages/macro/src/macro/sources.py` + `packages/macro/tests/` — the layout, docstring honesty, and test style to mirror.

### Previous story intelligence (Q8.4 — same epic, fresh lessons)

- **Pagination/truncation honesty:** Q8.4 review caught silent truncation reading as complete. EDGAR's `recent` block is a hard 1000-filing window — the docstring and series description must state it (per-company depth varies); do not report it as full history.
- **NaN/Infinity guard everywhere a float enters** (`math.isfinite`) — one bad cell 500s the whole page via starlette's `allow_nan=False`.
- **Dedup before upsert:** double-hitting ON CONFLICT within a run corrupts counters. Counting via a dict/Counter per (date, metric) gives this for free — keep it that way.
- **Per-series failure attribution:** one try per series; a wildcard try around a loop leaves earlier successes mislabeled (Q8.4 review finding).
- **Tests must assert the claim:** fakes capture SQL params; fixture tests assert actual parsed values/dates.
- **Docstrings must be honest** (partial capabilities stated); **typed signatures** on all new fetchers/helpers.
- **Pre-existing sym test failure** (`test_durable_reviews` import, invocation-specific) is on the ledger — NOT this story's diff; expect sym 543/544 under `uv run pytest` from the package dir and don't chase it.

### Breadcrumbs for later stories (record in ledger when closing)

- **SIC codes ride along free:** submissions JSON carries `sic`/`sicDescription` per company — a candidate classification source for US-listed ADRs of Brazilian names (QH.1's gap is IBOV GICS; PBR/VALE/etc. have ADR CIKs). Not this story; ledger it.
- **Archive files** (`filings.files[]`) give pre-2015 filing history per company — contract verified above; a backfill story can extend depth without schema change.

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md — Epic Q8, Story Q8.3 + "NEXT FOCUS — develop the databases" operator priority]
- [Source: _bmad-output/implementation-artifacts/Q8-4-broaden-macro-coverage.md — sibling story: layout, constraints, review lessons]
- [Source: packages/altdata/src/altdata/{ingest,gateway,router,db}.py; packages/altdata/db/]
- [Source: packages/macro/src/macro/sources.py + packages/macro/tests/ — patterns to mirror]
- [Source: _bmad-output/planning-artifacts/architecture-qrp.md — AR-R1 DB-per-package, AR-R2 app-side reads, AR-R4 typed contract]
- [Source: env probes this session, 2026-06-11 — SEC EDGAR (3 endpoints) verified payloads above; GDELT/IMF/FRED blocked per Q8.4 probes; job-board/GitHub probes denied by env policy]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Original `altdata` change's verify script asserted the wiki tables this story drops → sqitch verify failed post-deploy; reworked it to a schema-only assertion (honest comment pointing at `generic_series` for the new shape). Verify clean on both changes after.
- The running API (port 8001, from a previous session) 500'd on `/api/altdata/series` after the migration (stale code, new schema) — killed PID and restarted via `npm run dev:api` BEFORE `gen:types` (the A.1 stale-process lesson, this time observed live).
- `uv sync` couldn't relink `uvicorn.exe` (held by the running API) — packages installed fine; benign.
- Ruff with the macro-pattern select flagged 8 E501s (incl. one pre-existing line in `_resolve_figi` newly covered by the stricter config) — all fixed properly, no ignores added beyond the conventional `router.py` B008.

### Completion Notes List

- **All 7 ACs met.** The generalisation is structural: a third source is now an ingest catalog entry + fetcher, zero schema work. Migration lossless (10 series / 1,210 obs pre == post, then +20 EDGAR series / +182 obs from the live run; wiki refreshed to 1,260).
- **Live: 30/30 series ok, zero fabricated rows.** EDGAR provenance recorded per series (`detail` = zero-padded CIK); amendments excluded by exact form match (documented); the `recent`-block 1000-filing window stated honestly in docstrings.
- **Honest-rate fix shipped with the schema:** the old gateway averaged only stored rows against a GLOBAL latest date — wrong for sparse counts and cross-source staleness; now sum/window-days anchored per series. Kept the `avg7`/`avg30` field names: with implicit zeros these ARE calendar-day averages (documented in SQL + model comments).
- **API contract change handled end-to-end:** `article`→`detail`, `latest_views`→`latest_value` (float), `views`→`value`, + `source`/`metric`/`unit`; detail route requires `?source=&metric=` (a figi now carries several series); types regenerated against a fresh API; console reworked accordingly. tsc + eslint clean on touched files.
- **Suites:** altdata 20/20 (new), macro 32/32, api 30/30, operate 14/14, lineage 22/22, sym 543/544 — the one failure is the ledgered pre-existing invocation-specific import issue (NOT this diff).
- **Sweep semantics:** an obs-less series row is deleted at end of run (macro's rule) — an EDGAR metric with zero filings ever in-window is honest no-data, not an empty UI row.

### File List

- packages/altdata/db/deploy/generic_series.sql (new)
- packages/altdata/db/revert/generic_series.sql (new)
- packages/altdata/db/verify/generic_series.sql (new)
- packages/altdata/db/verify/altdata.sql (modified — schema-only assertion; its tables were retired by generic_series)
- packages/altdata/db/sqitch.plan (modified — `generic_series [altdata]` appended)
- packages/altdata/db/sqitch.conf (modified — review: stale wiki_map/pageview comment)
- packages/altdata/src/altdata/sources.py (new — fetch_pageviews moved here; fetch_company_ciks, fetch_sec_filing_counts, _finite guard)
- packages/altdata/src/altdata/ingest.py (modified — generic upserts, EDGAR catalog, per-series attribution, empty-series sweep)
- packages/altdata/src/altdata/gateway.py (modified — per-series-anchored sum/days rates; detail by (figi, source, metric))
- packages/altdata/src/altdata/router.py (modified — generalised response models; detail query params)
- packages/altdata/src/altdata/__init__.py (modified — docstring source list)
- packages/altdata/pyproject.toml (modified — description; dev group; ruff/pytest config matching macro)
- packages/altdata/tests/test_sources.py (new — 11 tests)
- packages/altdata/tests/test_ingest.py (new — 5 tests)
- packages/altdata/tests/test_gateway.py (new — 4 tests)
- apps/web/app/altdata/page.tsx (modified — multi-source series list + detail)
- apps/web/lib/api-types.ts (regenerated)
- uv.lock (modified — altdata dev group)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — Q8.3 section)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q8.3 `[BUILT 2026-06-11]`, FR-19 map, NEXT-FOCUS bullet)

## Change Log

- 2026-06-11: Story created (probe-first: SEC EDGAR verified with real payloads; generic series model + EDGAR filing-activity archetype scoped).
- 2026-06-11: Q8.3 implemented — generic series/observation schema (wiki data migrated losslessly), SEC EDGAR filing-activity source (Form 4 + 8-K daily counts, CIK provenance), honest sparse-series window rates, generalised API + console, first altdata test suite (20 tests). Live-verified end-to-end (DB → API → console).
- 2026-06-11: Code review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) — 10 patches applied (headline: source-aware window anchors killing the structural 4.29× sparse-series spike — sec_edgar anchors on CURRENT_DATE with zero-fill, verified live: idle KO 8-K now 0.0/None; shape-break payloads raise instead of ok:0; EDGAR cap-truncation guard; TypeError-garble skip; URL-encoding; misattribution precedence; revert refuses to fabricate; stale mentions; console sparse-series honesty; window-edge + 7 more tests → 28), 4 deferred (lineage remap + name-collision now real, console r.ok pattern, sweep race, index-spaced sparkline), 5 dismissed. Suites re-green (altdata 28, api 30, macro 32); story → done.
