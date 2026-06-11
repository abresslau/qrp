# Story Q9.2 (+ Q9.3 fold): Signals from macro + altdata inputs, with traceability

Status: done

## Story

As Andre (the operator),
I want signals derived from the `macro` and `altdata` modules — not just sym returns — with every factor's inputs and method recorded and surfaced,
so that FR-21's defining feature ("a derived Signal from sym + macro + altdata, inputs+method traceable") actually exists and the research loop has real cross-module signals to consume.

## Background + scope decision

**Research loop UN-PARKED (operator decision 2026-06-11)** — this is link 1 of the build order (Q9.2 → Q9.4 → Q7.3/Q7.4). Epic Q9 Story Q9.2 `[PARKED→active]`: *"a signal can name inputs across modules (sym + macro + altdata), read each from its own DB (app-side, AR-R2), and compute a derived score; this is the FR-21 differentiator vs the raw modules."* The epic's own examples: *"an attention-spike factor from altdata, a rate-regime factor from macro."*

**Q9.3 folded here** (`[PARTIAL]`: *"each signal records its named inputs and method so it's reproducible and never fabricated; surfaced in the UI"*): the traceability schema is exactly what cross-module factors need on arrival — landing them separately would mean touching the same catalog twice.

**Current state (read 2026-06-11):** `signals.factor` (key/name/description/direction) + `signals.score` (cross-sectional raw/z/rank/pctile per universe×date); `compute.py` computes 3 sym-only factors (mom_12_1, vol_1y, size) with the pattern: per-factor raw dict → winsorise → orient → store. Coverage gaps are absent rows (house rule). No tests exist for this package.

**The two new factors (designed against live data, probe-verified by the Q8.3/Q8.4 stories):**
1. **`wiki_attention` (altdata input):** 7d÷30d average Wikipedia pageviews per name as of the scoring date (altdata `wikipedia/pageviews`, ~126 days × 10 curated names, lag-aware: observations ≤ as_of_date only). Direction `high` (rising attention). Sparse coverage (10 names) is HONEST coverage — absent rows, the established rule.
2. **`fiscal_sens` (macro × sym input):** trailing-1Y beta of each name's daily return (sym `fact_returns` 1D) to the daily %-change in US total public debt outstanding (macro `UST:DEBT` — the one DAILY macro series; ~8k obs from 1993, live to 2026-06-09). ≥60 matched days required. Direction `low` (low fiscal-flow sensitivity = defensive orientation — a DEFINITION choice, stated in the method text, not an empirical claim).

**Explicitly OUT of scope:** consumption by optimiser/backtest (Q9.4, next); composite multi-factor blends (a later signal once the loop closes); any new macro/altdata ingestion; point-in-time vintage awareness (macro obs are served as-is — noted in method text); scheduler/Operate op for compute (stays `python -m signals.compute`).

## Acceptance Criteria

1. **Traceability schema (sqitch `factor_traceability`):** `signals.factor` gains `inputs JSONB NOT NULL DEFAULT '[]'` (module-qualified input refs, e.g. `["altdata:wikipedia:pageviews", "sym:universe_membership"]`) and `method TEXT`; catalog upsert writes both for ALL five factors (the 3 sym factors get honest entries too — Q9.3 covers the whole catalog, not just the new rows).
2. **Cross-module compute (AR-R2):** `compute_universe` accepts optional `alt_conn` / `macro_conn` (each module's OWN database, read-only, app-side joins — never cross-DB SQL); a missing connection SKIPS that factor with an attributed reason in the summary (never a silent zero); the `__main__` runner connects all four DBs.
3. **`wiki_attention`:** per-figi 7d÷30d mean pageviews from altdata observations ≤ as_of_date (windows anchored at as_of_date; ≥5 obs in the 7d window and ≥15 in the 30d required, else absent); winsorised/oriented/stored through the existing `_store` path.
4. **`fiscal_sens`:** per-figi OLS beta (cov/var) of sym 1D `pr` vs UST:DEBT daily %-change over (as_of−365d, as_of], matched on date, ≥60 matched days; computed app-side from two reads; absent on insufficient data.
5. **API + console surface (Q9.3):** `FactorSummary`/`FactorRanking` gain `inputs: list[str]` + `method: str | None`; types regenerated (restarted API); the signals console page shows inputs + method per factor.
6. **Tests (first for this package — `packages/signals/tests/`):** pure-math tests (winsorise bounds/order, orientation/rank/pctile via `_store` against a recording conn incl. params, OLS beta on a hand-computable series); raw-factor tests with fake conns (attention windows + minimum-obs gates, beta date-matching incl. unmatched dates dropped); skip-attribution when a conn is absent; catalog upsert carries inputs JSONB + method. Dev group (pytest/ruff) matching the macro/altdata pattern.
7. **Live verification:** migration deployed (Docker sqitch, signals DB); `python -m signals.compute` over sp500/ibov/ibx — `wiki_attention` scores the curated names (~9–10 on sp500, 0 on ibov/ibx — honest), `fiscal_sens` scores broadly (US names; ibov/ibx limited by data — served as-is); `/api/signals/factors` shows 5 factors with inputs/method; console renders; epic Q9.2 `[BUILT]` + Q9.3 `[BUILT]` (folded) + FR-21 map; ledger updated.

## Tasks / Subtasks

- [x] Task 1: `factor_traceability` migration + catalog inputs/method for all 5 factors (AC: 1) — deployed + verified; the 3 sym factors got honest inputs/method entries too; `fiscal_sens` method states the direction DEFINITION choice + current-vintage caveat
- [x] Task 2: cross-module compute — conn plumbing + skip attribution + the two raw-factor functions (AC: 2, 3, 4) — `alt_conn`/`macro_conn` optional params, missing → `skipped: {factor: reason}`; `_raw_wiki_attention` (SQL-side windows bounded ≤ as_of, ≥5/≥15 gates, finite-guard); `_raw_fiscal_sens` (app-side date-matched OLS, ≥60 matched days, zero-variance + non-finite → absent); `__main__` connects all four DBs
- [x] Task 3: API models + console surface (AC: 5) — `inputs`/`method` on `FactorSummary` + `FactorRanking`; console: per-module colour-coded input chips + method line + raw formatting for the new factor shapes (ratio ×, bare beta); drive-by count fix in `factors()` (`count(*)` → `count(s.factor_key)` — a scoreless factor row was counting 1, hit by the new factors existing before scores; ledgered)
- [x] Task 4: tests (AC: 6) — `packages/signals/tests/test_compute.py`: 11 tests (first for this package): catalog declares module-qualified inputs+method for every factor incl. the stated caveats; upsert params carry JSONB inputs; winsorise clip+order; `_store` orientation (rank/pctile/z by direction); attention ratio + min-obs gates + bounded-read assertion; **fiscal beta recovers a known beta=2.0 from a constructed series**; <60-matched-days absent; zero-variance absent; empty macro series short-circuits; skip attribution. Dev group + ruff/pytest config (macro pattern)
- [x] Task 5: deploy + live run + types regen + finishers (AC: 7)
  - [x] Live compute: sp500 503 members — mom 499 / vol 502 / size 501 / **wiki_attention 10** (all curated names; GOOGL 1.05× top) / **fiscal_sens 502**; ibov/ibx 0 members at the global as-of (build-forward membership from 2026-06-08 vs returns max 2026-06-05 — pre-existing, honest, ledgered with the per-universe as-of design note)
  - [x] `/api/signals/factors` serves 5 factors with inputs/method; ranking endpoints verified; types regenerated (restarted API — and a venv repair en route: `uv sync` without `--all-packages` had stripped workspace deps); console `/signals` 200, tsc + eslint clean
  - [x] Epic Q9.2 + Q9.3 `[BUILT 2026-06-11]`, FR-21 map; ledger: B3 date-starvation, winsorisation cap ties, count fix

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] `fiscal_sens` direction-low rewards the most-NEGATIVE beta while the description claims "low sensitivity = defensive" — a 0.0 beta (truly insensitive) ranked behind −3.54. Fix: raw = |beta| (absolute sensitivity); direction low then genuinely favours insensitive names; method text updated; re-run live [compute.py] (HIGH, blind)
- [x] [Review][Patch] Console signals page crashes on ranking 404s (no `r.ok` check + unguarded `data.constituents.length` at the empty-state row) — guaranteed by the new sparse factors on ibov/ibx. Guard the fetch + the render [apps/web/app/signals/page.tsx] (HIGH, edge)
- [x] [Review][Patch] The attributed-skip path is unreachable from the shipped runner: a down altdata/macro DB aborts everything before scoring and leaks `sym_conn`. Runner: per-module connect in try/except → None (the documented contract), close with guards [compute.py `__main__`] (MED, blind+edge)
- [x] [Review][Patch] "No look-ahead" overstated for UST:DEBT publication lag (obs for date d publishes d+1; a score as-of d embeds an availability lag) — the bound is on observation dates. State the caveat in the module docstring + the factor method [compute.py] (MED, blind)
- [x] [Review][Patch] Attention test asserts SQL text only — parameter ORDERING (the classic bug in that query shape) unasserted; assert the params tuple [tests] (LOW, blind)
- [x] [Review][Patch] Story File List empty — fill the record [story] (LOW, auditor)
- [x] [Review][Defer] Lineage `signals.score` deps still sym-only (no altdata/macro edges) — extends the ledgered Q8.3 lineage-remap item (altdata's lineage assets are stale wholesale; one remap pass) — deferred, ledgered
- [x] [Review][Defer] Per-name betas over different matched windows (only ≥60 enforced) + multi-day debt deltas at calendar gaps matched to 1-day returns — estimation-noise design choices; a common-date intersection / max-gap guard when the factor's precision matters — deferred, ledgered
- [x] [Review][Defer] Absent SOURCE (vs absent connection) reads as `scored: 0` unattributed — the run output is honest but the skip contract covers connections only; a source-presence pre-check is a design add — deferred, ledgered
- [x] [Review][Defer] Stale ibov/ibx sym-factor scores from the pre-rebuild roster still stored/served (`_store` never retracts) — pre-existing; pairs with the B3 date-starvation ledger item — deferred, ledgered

Dismissed as noise (2): `count(*)` vs `count(value)` in the attention gates (`altdata.observation.value` is NOT NULL by schema — verified); winsorisation-cap tie ordering (already ledgered pre-review; the |beta| patch changes which names tie but ties at caps are inherent to the documented clip).

## Dev Notes

### Existing code map (READ before writing)

- `packages/signals/src/signals/compute.py` — FACTORS dict (gains `inputs`+`method` per entry), `_ensure_catalog` (upsert gains 2 columns), `_winsorize`/`_store` (REUSE unchanged), `compute_universe` (gains conns + skip reasons), `__main__`.
- `packages/signals/src/signals/gateway.py` `factors()`/`ranked()` — add the 2 columns; `router.py` models.
- `packages/signals/db/` — single `signals` change; append `factor_traceability [signals]`.
- `packages/altdata` schema: `altdata.series`/`altdata.observation` keyed `(composite_figi, source, metric, obs_date)` — Q8.3's generic model; wiki rows are `source='wikipedia', metric='pageviews'`.
- `packages/macro` schema: `macro.series`/`macro.observation` keyed `series_id` — UST:DEBT obs are `(obs_date, value)` in USD trillions.
- Console signals page: `apps/web/app/signals/page.tsx` (read before editing; AGENTS.md Next-version warning applies).
- House test style: `packages/macro/tests/`, `packages/altdata/tests/` (fake conns, params asserted, no network/DB).

### Constraints

1. AR-R2: one read-only conn per module, app-side assembly; signals writes ONLY its own DB.
2. Never fabricate: minimum-obs gates make names absent, not zero-scored; skipped factors attributed.
3. `as_of_date` canonical; obs_date stays obs_date (time-series date).
4. Sqitch via Docker (signals DB); types regen against a FRESHLY RESTARTED API (8001/3001 squat gotcha).
5. Ruff 100, Python ≥3.13; dev-group pattern from macro/altdata pyprojects.
6. Method text must state definition choices honestly (the `fiscal_sens` direction is a choice; macro obs are current-vintage, not point-in-time).
7. Suites green: api 45, sym 590+1 ledgered, macro 32, altdata 28, operate 14, lineage 22.

### Previous story intelligence (recurring review themes — pre-empt)

- Look-ahead discipline (Q5.2's HIGH finding): both new factors read STRICTLY ≤ as_of_date; the vol factor's upper-bound precedent (compute.py `_raw_vol`) is the in-package model.
- Shape-break honesty (Q8.3): an absent macro series (UST:DEBT missing) → factor skipped with reason, not ok-0.
- Honest counters; typed signatures; docstrings state partial capabilities (sparse altdata coverage).
- Q8.4: NaN guard — beta math on degenerate series (zero variance) → absent, not NaN/inf scores (starlette allow_nan would 500).

### References

- [Source: epics-qrp-roadmap.md — Q9.2/Q9.3/Q9.4, un-park decision 2026-06-11]
- [Source: packages/signals/src + db; packages/{altdata,macro} schemas as built by Q8.3/Q8.4]
- [Source: architecture-qrp.md — AR-R1/AR-R2/AR-R4]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- `uv sync` (bare) stripped workspace deps mid-story (click/uvicorn gone — the venv had been syncd while the running API held uvicorn.exe); `uv sync --all-packages` is the repair. Watch for this when the API is running.
- ibov/ibx scored 0 members: build-forward B3 membership (valid_from 2026-06-08) vs fact_returns max 2026-06-05 — pre-existing PIT honesty, ledgered with a per-universe as-of design note.

### Completion Notes List

- **All 7 ACs met.** FR-21's core exists: factors that name inputs across modules, read each module's own DB read-only (AR-R2), and compute derived scores — `wiki_attention` (altdata, 10 names, GOOGL 1.05x top) and `fiscal_sens` (macro x sym, 502 betas) live on sp500; Q9.3 traceability folded (inputs JSONB + method on all 5 factors, served + rendered as module chips).
- **Review's HIGH catch was conceptual:** the signed beta under direction-low ranked the most-NEGATIVE beta best — the opposite of "low sensitivity = defensive". raw is now |beta|; live rank 1 went from a -3.54 winsorisation-cap artifact to FFIV at |beta| 0.01 (genuinely insensitive). The magnitude test pins both +2x and -2x names to 2.0.
- **Honesty hardening from review:** publication-lag caveat stated (UST:DEBT publishes d+1 — the as_of bound is on observation dates); the runner degrades a down input module to the attributed skip instead of aborting (and stops leaking conns); console survives the 404s sparse factors guarantee.
- Suites: signals 11/11 (first for the package), api 45, macro 32, altdata 28; ruff/tsc/eslint clean.

### File List

- packages/signals/db/deploy/factor_traceability.sql (new)
- packages/signals/db/revert/factor_traceability.sql (new)
- packages/signals/db/verify/factor_traceability.sql (new)
- packages/signals/db/sqitch.plan (modified)
- packages/signals/src/signals/compute.py (modified — FACTORS inputs/method, two cross-module factors, conn plumbing + skip attribution, resilient runner)
- packages/signals/src/signals/gateway.py (modified — inputs/method columns + scoreless-count fix)
- packages/signals/src/signals/router.py (modified — models + docstring)
- packages/signals/pyproject.toml (modified — dev group + lint/pytest config)
- packages/signals/tests/test_compute.py (new — 11 tests)
- apps/web/app/signals/page.tsx (modified — input chips, method line, raw formats, 404 guard)
- apps/web/lib/api-types.ts (regenerated)
- uv.lock (modified — signals dev group)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q9.2/Q9.3 BUILT, FR-21 map)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — Q9.2 section + review deferrals)

## Change Log

- 2026-06-11: Story created (research loop un-parked; Q9.3 traceability folded; factors designed against live Q8.3/Q8.4 data: wiki_attention + fiscal_sens).
- 2026-06-11: Implemented + live-verified; status review.
- 2026-06-11: Code review (3 layers) — 6 patches: fiscal_sens raw is now |beta| (the signed version ranked the most-negative beta best, contradicting the defensive reading — live rank 1 went from a -3.54 cap artifact to FFIV |beta| 0.01); console 404 guard; resilient runner (attributed skip reachable, no conn leak); publication-lag honesty; param-ordering test pin; record filled. 4 deferred (lineage edges, beta estimation-noise choices, source-vs-connection skip, stale B3 scores), 2 dismissed. signals 11/11; status done.
