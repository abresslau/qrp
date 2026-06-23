# Story: Multi-country yield curves — pull every FX-matrix currency's rates from its central bank

Status: ready-for-dev

<!-- Created via bmad-create-story 2026-06-23 (Andre: "now that you learned how to pull rates with the
UK example, pull the data for all countries displayed in the FX matrix, ideally directly from the
respective central banks. Do this overnight without my assistance; I'll check at 7am."). This generalises
the UK rates store (commits 0c48904 store / 882ad17 analytics / 19927fa curve view) to every currency on
the FX matrix. AUTONOMOUS overnight run — probe-first, attempt-all, never block, log what's blocked. -->

## Story

As a fixed-income analyst on QRP,
I want **historical yield curves for every country behind the FX matrix** (the euro area **broken down
by country** — Germany, France, Italy, Spain, … — not a single EUR aggregate), pulled (ideally)
**directly from each central bank** into the `rates` store, **all standardised** so I can **switch
between countries and compare their curves** on the Curve & spreads page,
so the curve/spread/timelapse tooling I have for the UK works across — and *across* — every country.

### What "done by morning" means (Andre's clarifications)
- **Switch between countries on `/rates` (Curve & spreads).** A country selector is a HARD requirement,
  not deferrable. Each shows its **historical** curve (backfill, not just the latest day).
- **Standardise everything** so curves are directly comparable — same schema, same units (% p.a.),
  same page. The existing comparison overlays should be able to overlay **different countries**
  (e.g. DE vs FR vs IT), not just different dates. One standardised page; add another page only if a
  cross-country *board* genuinely needs it (keep it standardised either way).
- **EUR → per country, most important first:** Germany (Bunds — the euro benchmark) → France (OATs) →
  Italy (BTPs) → Spain (Bonos) → Netherlands → Belgium → … Pull as many as reachable, in that order.
- The dimension is therefore **country**, not currency (EUR maps to many countries).

## Autonomy mandate (read first)

This runs **overnight, unattended**. Therefore:
- **Probe before build, per currency.** Each central bank is a *different* source with *unknown*
  in-env reachability (the sim-2026 env reaches some external hosts and blocks others —
  [[reference_env_external_sources]]: ECB SDMX / WorldBank / B3 / yfinance-EOD reachable; FRED + live
  quotes blocked; most CB sites UNTESTED). Probe each, record the exact URL + result +
  re-test trigger ([[feedback_name_the_probe_retest]]).
- **Attempt ALL currencies; NEVER let one failure abort the run.** Per-currency `try/except`; a blocked
  or unparseable source is logged and skipped, not fatal. Maximise how many currencies land.
- **Prefer the central bank** ("ideally directly"). Where a CB source is genuinely unreachable/unusable
  in-env, a clearly-labelled fallback (ECB for the euro area; a yfinance government-bond-yield proxy) is
  acceptable **only as a flagged second choice**, never silently.
- **Leave a morning report** (`packages/rates/PULL_REPORT.md`) Andre can read at 7am: per currency —
  source, reachable?, built?, coverage (dates × tenors), or blocked + the re-test trigger. Commit work
  incrementally so partial progress survives.
- Do NOT ask questions — execute with reasonable defaults ([[feedback_execute_dont_quiz]]).

## Background / current state (reuse, do NOT reinvent)

- The `rates` package (own Postgres DB, [[project_rates_package_decision]]) already stores the **UK** BoE
  curves in `rates.curve_point` and has the full pipeline: `sources/boe.py` (download + xlsx parse +
  layout assertion), `ingest.py` (`fill_curve`: tail/backfill, two-vintage upsert, plausibility→review,
  atomic per-day), `validate/checks.py` (`CheckResult`: staleness / band / inflation=nominal−real /
  forward↔spot identity), `cli.py` (`rates curve load|coverage`, `rates validate`), `gateway.py`/`router.py`
  (`/api/rates/curve` + spreads + `/curve/movie`). **Generalise this, don't fork it.**
- **Schema today is UK-specific:** `curve_point` PK `(curve_set, basis, rate_type, tenor, as_of_date)`,
  `curve_set CHECK IN ('glc','ois','blc')`, `rate_type CHECK IN ('spot','forward')`, value band
  `(-10,30)`. There is **no country/currency dimension** — that's the core schema change.
- **FX-matrix currencies** (`services/api/.../sym/gateway.py:71` `DEFAULT_FX_MATRIX`): EUR, JPY, **GBP✓**,
  CHF, CAD, AUD, NZD, SEK, NOK, DKK, HKD, SGD, MXN, CNY, BRL, USD. (15 to add; GBP done.)
- **FX ingest precedent** (`packages/sym/src/sym/fx/`) shows the multi-source adapter + reconcile/restate
  pattern QRP already uses; `macro` already pulls **US Treasury FiscalData** and **BCB (Brazil)** + ECB —
  reuse those source learnings.

## Candidate central-bank sources (probe each in-env first — these are starting points, not gospel)

| Ccy | Central bank / source (starting candidate) | Notes |
|---|---|---|
| EUR→**DE** | **Bundesbank** time-series (listed-federal-securities / term-structure) | euro benchmark — do FIRST; probe |
| EUR→**FR** | **Banque de France** / ECB per-country / market source (OAT yields) | probe |
| EUR→**IT** | **Banca d'Italia** / MEF (BTP yields) | probe |
| EUR→**ES** | **Banco de España** / Tesoro (Bonos yields) | probe |
| EUR→NL,BE,… | national CB / ECB per-country long-term rates | probe, lower priority |
| EUR (agg) | **ECB SDMX** `YC` (euro-area AAA aggregate) | env-reachable — FALLBACK if per-country sources fail, clearly flagged as the aggregate |
| USD | **US Treasury** par-yield curve (treasury.gov XML/CSV; or `macro` FiscalData) | FRED blocked; Treasury direct likely reachable; rate_type = **par** |
| JPY | **MoF Japan** JGB interest rates (CSV) / BOJ | probe |
| CHF | **SNB** data portal `data.snb.ch` (rates API) | probe |
| CAD | **Bank of Canada** Valet API (bond yields) | probe — clean JSON API |
| AUD | **RBA** statistical table F2 (CSV) | probe |
| NZD | **RBNZ** B2 wholesale interest rates (CSV) | probe |
| SEK | **Riksbank** API (govt bond yields) | probe |
| NOK | **Norges Bank** API (govt bond yields) | probe |
| DKK | **Danmarks Nationalbank** (statbank API) | probe (DKK ~ EUR-pegged) |
| HKD | **HKMA** Exchange Fund Bills/Notes yields | probe |
| SGD | **MAS** SGS benchmark yields API | probe |
| MXN | **Banxico** SIE API | may need a free token → if so, log as blocked-needs-token |
| CNY | **ChinaBond / PBoC** gov bond yield curve | likely hard/blocked — probe, log |
| BRL | **BCB** (`macro` already feeds BCB) / Anbima / Tesouro | probe; reuse macro's BCB access |
| GBP | Bank of England — **DONE** (`sources/boe.py`) | — |

## Acceptance Criteria

1. **Schema generalised to multi-country (sqitch migration).** `curve_point` (+ `curve_point_review`)
   gain a **`country CHAR(2)`** column (ISO-3166 alpha-2 — the sovereign issuer, so EUR fans out to DE,
   FR, IT, ES, …) plus a **`currency CHAR(3)`** attribute (for grouping/labels: DE→EUR, GB→GBP). PK becomes
   `(country, curve_set, basis, rate_type, tenor, as_of_date)`. `curve_set`/`rate_type` CHECKs broadened to
   the union needed (e.g. `curve_set` in {`govt`,`ois`,`glc`,…}; `rate_type` add `par`). Existing UK rows
   **backfilled `country='GB'`, `currency='GBP'`** (curve_set left `glc`/`ois`). Value band widened if a
   probe shows higher historical rates. Deploy via the Docker sqitch flow ([[reference_sqitch_deploy_docker]]);
   Docker down → apply to the dev DB directly with idempotent SQL, flag sqitch pending (ticker-region-codes
   precedent). UK `rates validate` stays green after the migration.
2. **Per-currency source probe recorded.** For each of the 15 currencies, the chosen CB source is probed
   in-env; `packages/rates/PULL_REPORT.md` records URL, reachable (HTTP/format), and the data shape
   (tenors, rate_type, history). Maintenance-plan discipline ([[feedback_index_maintenance_plan]]).
3. **Adapters built for every reachable CB source.** A `sources/<ccy>.py` (or a config-driven adapter)
   per reachable source, normalised to `CurvePoint(currency, curve_set, basis, rate_type, tenor,
   as_of_date, value)`; loaded via the generalised `fill_curve` (currency-aware), with the layout
   assertion + plausibility gate. Source-tagged (`source` = the CB).
4. **Attempt-all, never block.** The load orchestration iterates all currencies; a per-currency failure
   (unreachable / parse error / needs-token) is caught, logged to `PULL_REPORT.md` with a re-test
   trigger, and the run continues. Success = the currency's curve in `curve_point`; report coverage
   (distinct dates × tenors). Target: **maximise** currencies landed; GBP must remain intact.
5. **Validate generalises per currency.** `rates validate` runs the existing checks **per currency**
   (staleness, plausible band, forward↔spot where both published; inflation=nominal−real only where a
   real curve exists). Per-currency PASS/WARN/FAIL. No false FAIL on currencies that only publish one
   rate_type/basis.
6. **Schedules.** Each built source gets a daily Dagster `ScheduleDefinition` with an **explicit
   `execution_timezone`** matching the CB's publish timezone ([[feedback_schedule_explicit_timezone]]),
   `default_status=STOPPED`. (A single multi-currency schedule that loops the reachable sources is
   acceptable if cleaner — still one explicit tz per logical job.)
7. **Read API + page country switcher (REQUIRED — Andre checks this at 7am).** `GET /api/rates/curve`
   (+ `/curve/series`, `/curve/movie`, `/spreads`) gain a `country` param (default `GB` for back-compat);
   `curve_sets()` lists every pulled country's series. The **`/rates` Curve & spreads page gets a country
   selector** (grouped by currency/region) so the curve chart + comparison overlays + timelapse work for
   **any** pulled country, showing its **historical** data. **Standardised + cross-country comparison:**
   the comparison overlays must be able to overlay **other countries' curves** (e.g. DE vs FR vs IT on the
   same axes), not only other dates — that's the whole point. This page item is NOT deferrable; it is the
   primary thing Andre will look at. (If a cross-country *board* page helps, add it — standardised.)
8. **No regression + green + morning report.** UK curve/analytics/page unchanged for `GB`; `ruff`/`pytest`
   green for `rates`; `PULL_REPORT.md` complete; work committed incrementally. Derive-on-read analytics
   (spreads etc.) extend to any country with data — no per-country analytics code.

## Tasks / Subtasks

- [ ] **Task 1 — Probe ALL central-bank sources in-env (GATE; fan out) (AC: #2)**
  - [ ] For each of the 15 currencies, probe the candidate CB source (HTTP reachability + fetch a sample
    + inspect format/tenors/rate_type/history). Parallelise (subagents) — they're independent.
  - [ ] Write `PULL_REPORT.md` §Probe: per currency — chosen URL, reachable?, format, data shape, or
    blocked + reason + re-test trigger. Decide build-order (reachable + clean first).
- [ ] **Task 2 — Generalise the schema (currency dimension) (AC: #1)**
  - [ ] sqitch `add_currency.sql` (deploy/revert/verify): add `currency CHAR(3)` to `curve_point` +
    `curve_point_review`, re-key the PK, broaden `curve_set`/`rate_type` CHECKs, widen value band if
    needed; backfill existing rows `currency='GBP'`. Idempotent; apply directly if Docker down.
  - [ ] Update `ingest.py`/`gateway.py`/`validate` references to include `currency` (UK path unchanged
    behaviourally; GBP validate still green).
- [ ] **Task 3 — Generalise the ingest/source framework (AC: #3)**
  - [ ] `CurvePoint` + `fill_curve` become currency-aware; a `CurveSource` protocol so each CB adapter
    yields normalised points. Keep the BoE adapter working (now tagged `currency='GBP'`).
- [ ] **Task 4 — Build each reachable adapter + load + validate (AC: #3, #4, #5)**
  - [ ] Per reachable currency: `sources/<ccy>.py`, `rates curve load --currency <CCY>` (or an
    `--all` loop), validate, record coverage in `PULL_REPORT.md`. try/except per currency; never abort.
- [ ] **Task 5 — Schedules (AC: #6)**
  - [ ] Daily schedule(s) for the built sources, explicit `execution_timezone`, STOPPED.
- [ ] **Task 6 — API + page currency support (AC: #7)**
  - [ ] `currency` param on the rates read endpoints; `/rates` currency selector (defer ONLY if overnight
    time runs out — flag in the report).
- [ ] **Task 7 — Morning report + verify + commit (AC: #8)**
  - [ ] Finalise `PULL_REPORT.md` (what landed, coverage table, blocked + re-test triggers, any deferrals).
    `ruff`/`pytest` green; UK unchanged. Commit incrementally (one commit per milestone so partial
    overnight progress is saved).

## Dev Notes

### Critical conventions
- **Generalise the existing `rates` pipeline; don't fork it.** The BoE adapter/ingest/validate/CLI/gateway
  are the template — add a `currency` dimension through them.
- **Probe-first + attempt-all + log-don't-abort** — the autonomy mandate above. A blocked CB is a logged
  line in `PULL_REPORT.md`, not a failed run.
- **Prefer the central bank**; fallbacks (ECB-for-EUR, yfinance gov-bond proxy) only as flagged second
  choice. Reliable-source + derive-don't-store posture carries over.
- **Canonical `as_of_date`** = the curve's stated date ([[feedback_as_of_date_canonical_name]]); per-source
  units canonicalised to % p.a.; **schedules set `execution_timezone`** explicitly
  ([[feedback_schedule_explicit_timezone]]); `conn.autocommit=True` durability
  ([[feedback_psycopg_per_figi_durability]]); explicit-delete not rollback in tests
  ([[feedback_db_validation_rollback]]).
- **GBP must not regress** — its rows, validate, page, and analytics keep working throughout.

### Explicitly OUT of scope
- Bond reference-data / specific-instrument pricing; live intraday marks; a 2nd source + divergence per
  currency (FX-style); perfect/complete coverage (best-effort overnight); deep history backfill for every
  currency (pull what's cleanly available — recent history is enough to be useful; note depth per ccy).
- Per-currency derived-analytics code — the existing derive-on-read spreads/curve/timelapse generalise
  automatically once `curve_point` has the data + the API carries `currency`.

### References
- [Source: packages/rates/src/rates/{sources/boe.py, ingest.py, validate/checks.py, cli.py, gateway.py, router.py}] — the UK pipeline to generalise.
- [Source: packages/rates/db/deploy/curve_point.sql] — the schema to add `currency` to.
- [Source: packages/sym/src/sym/fx/{source.py,ingest.py,reconcile.py}] — multi-source adapter/reconcile pattern.
- [Source: packages/macro/src/macro/sources.py] — ECB SDMX + US Treasury FiscalData + BCB access already working in-repo (reuse the reachability + parsing learnings).
- [Source: services/api/.../sym/gateway.py:71] — `DEFAULT_FX_MATRIX` (the currency universe).
- Memories: [[project_rates_package_decision]], [[project_fi_curves_brainstorm]], [[reference_env_external_sources]], [[feedback_name_the_probe_retest]], [[feedback_index_maintenance_plan]], [[feedback_schedule_explicit_timezone]], [[feedback_as_of_date_canonical_name]], [[reference_sqitch_deploy_docker]], [[feedback_execute_dont_quiz]], [[feedback_minimize_dev_churn]].

## Open Questions (defaults chosen — non-blocking, autonomous run)
1. **CB vs fallback:** default = central bank where reachable, else a flagged fallback (ECB/yfinance). Pull what's available rather than nothing.
2. **History depth:** default = whatever the CB cleanly publishes (recent years min); deep backfill per ccy is out of scope.
3. **Page selector vs data-only:** default = build the data + API for all reachable ccys; the `/rates` currency selector is the only deferrable item if overnight time runs out.
4. **curve_set naming:** default = `govt` for each country's sovereign curve (UK keeps `glc`/`ois`); harmonise later if wanted.

## Dev Agent Record
### Agent Model Used
### Debug Log References
### Completion Notes List
### File List

## Change Log
| Date | Change |
|---|---|
| 2026-06-23 | Created (bmad-create-story, Andre: "pull all FX-matrix countries' rates from their central banks, overnight, unattended, check 7am"). Generalise the UK `rates` store to all 16 FX-matrix currencies: add a `currency` dimension to `curve_point`, probe each central-bank source in-env (attempt-all, never block), build adapters for reachable CBs, load + validate per currency, schedules with explicit tz, currency-aware API/page, and a `PULL_REPORT.md` morning summary. Probe-first + log-don't-abort autonomy mandate. Status → ready-for-dev. |
