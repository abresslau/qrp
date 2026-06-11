# Story Q6.3 + Q9.4(backtest): Parameterised strategy spec; signals drive backtests

Status: done

## Story

As Andre (the operator),
I want backtests driven by a reproducible strategy spec (factor — including the signals package's cross-module factors — selection rule, weighting, rebalance cadence) instead of the hard-coded EW top-quintile,
so that FR-18's "defined strategy" exists and the research loop's signals→backtest link closes with one factor-definition source instead of two drifting copies.

## Background + scope decision

Research-loop link 2 (un-parked 2026-06-11; Q9.2 done). Two epic items land together because the same seam serves both:

- **Q6.3** `[NEW]` (FR-18): *"a strategy spec drives the engine (factor or signal input, top-N/quintile, EW/cap-weight, rebalance freq); reproducible from the spec."*
- **Q9.4 backtest half** (FR-21): *"a signal's scores are selectable as inputs to backtest (Q6.3 selection rule)."* The optimiser half stays with Q7.3/Q7.4 (next story).

**The architecture finding (read 2026-06-11):** `backtest.engine._factor_at` re-implements mom_12_1/vol_1y/size — the SAME definitions `signals.compute` owns (and signals now has the cross-module factors + traceability). Two copies have already begun drifting (backtest's vol is un-annualised). The honest Q9.4 isn't "backtest reads signals.score rows" — stored scores exist for ONE as_of_date, useless for walk-forward history, and reading them would freeze the no-look-ahead recompute principle the engine is built on. **The honest form: signals exposes a public `raw_factor(key, members, as_of_date, *, sym_conn, alt_conn, macro_conn)` seam and backtest delegates to it at every rebalance** — single definition source, recompute-at-date preserved, cross-module factors (fiscal_sens etc.) usable wherever their input history is deep enough, and the coverage gate keeps thin factors honest (wiki_attention's 126-day/10-name data cannot pass a broad-universe gate — by design, not by error).

**Spec design (FR-18 "defined strategy"):**
`{factor, universe, selection: top_pct | top_n, weighting: "equal" | "cap", rebalance: "monthly" | "quarterly", start/end}` — persisted whole as `backtest.run.spec` JSONB (legacy columns kept for the existing list UI). Cap-weighting uses market_cap_usd at the rebalance date (the size raw, via the same seam); weights held constant between rebalances (platform convention, Q5.2 precedent). Baseline stays EW-of-roster.

**Explicitly OUT of scope:** optimiser signal tilts + optimiser→portfolio (Q7.3/Q7.4 next); short/long-short strategies; transaction costs; reading stored `signals.score` rows (recompute-at-date is the principle); console chart changes beyond the new controls.

## Acceptance Criteria

1. **Signals seam:** `signals.compute.raw_factor(key, members, as_of_date, *, sym_conn, alt_conn=None, macro_conn=None) -> dict[str, float]` + `required_modules(key) -> frozenset[str]` (parsed from FACTORS inputs prefixes) + direction lookup. Unknown key → ValueError; a required module conn missing → ValueError naming the module (never a silent sym-only result).
2. **Engine delegates:** `_factor_at`'s bespoke SQL is GONE — the engine calls the seam for every factor (the 3 legacy keys give the same selections as before; backtest's drifted un-annualised vol is reconciled to signals' annualised definition — ranks identical, monotone scale). Engine accepts any signals factor; the existing coverage gate (≥ max(20, 0.5·roster)) applies unchanged.
3. **Strategy spec:** engine + API accept `top_n: int>0` XOR `top_pct` (422 if both), `weighting: equal|cap`, `rebalance: monthly|quarterly`; cap-weights ∝ market_cap_usd at the rebalance date (names without mcap at d are dropped from the holding, counted in the run output — never zero-weighted silently); strategy daily return = weight-fixed mean between rebalances. Migration `strategy_spec` adds `backtest.run.spec JSONB`; the run persists the FULL spec; the API serves it.
4. **Cross-module run works end-to-end:** a `fiscal_sens` backtest on sp500 runs (macro conn supplied by the router only when `required_modules` demands it), persists, and its spec reproduces it; a `wiki_attention` sp500 run fails the coverage gate with the honest error (documented expectation).
5. **Console:** the backtest page's factor list is fetched from `/api/signals/factors` (no more hardcoded 3), plus weighting/rebalance/top-N controls; run list shows the spec'd parameters. Types regenerated (restarted API).
6. **Tests:** signals seam (registry/raise behavior incl. missing-module naming); backtest (first package tests): quarterly rebalance dates, top_n vs top_pct selection XOR, cap-weight math incl. missing-mcap drop + count, delegation params reach the seam, spec persisted to SQL. House style.
7. **Live verification + finishers:** migration deployed; legacy-equivalent run (mom EW quintile monthly) matches the prior result shape; a cap-weighted quarterly `fiscal_sens` top-50 run on sp500 persists with its spec; epic Q6.3 `[BUILT]`, Q9.4 → `[PARTIAL — backtest half]`; FR-18/FR-21 map; ledger.

## Tasks / Subtasks

- [x] Task 1: signals public seam — `raw_factor` (validates key, names missing module conns), `required_modules` (parsed from declared inputs — Q9.3's metadata is load-bearing), `factor_direction`; 3 seam tests (signals suite 11 → 14) (AC: 1)
- [x] Task 2: `strategy_spec` migration (deployed + verified) + engine rewrite — `_factor_at`/`_DIRECTION` deleted, delegation via the seam (vol reconciliation noted in the module docstring: monotone rescale, identical ranks); `top_n` XOR `top_pct`, `weighting equal|cap` (`_cap_weights` drops + counts capless names; `dropped_no_mcap` in the summary), `rebalance monthly|quarterly`; `_daily_mean` → `_daily_weighted` (fixed weights, renormalised over priced names per date — the platform convention); full spec persisted (AC: 2, 3)
- [x] Task 3: router/gateway — 422 on both selections; unknown factor 422 via `required_modules`; alt/macro conns opened ONLY when the factor's declared inputs demand (AR-R2, mirrors the save_portfolio conditional pattern); `spec` (`StrategySpec` model) on run responses; backtest gains the `signals` workspace dep (AC: 3, 4)
- [x] Task 4: backtest tests (first for the package, 9): monthly/quarterly rebalance dates; top_n exact-N by direction + capped-at-len; top_pct unchanged; cap weights proportional + dropped-counted; weighted daily series incl. renormalise-over-priced; engine rejects unknown factor/weighting/rebalance, neither-selection, and a signals factor without its module conn (error NAMES the module) (AC: 6)
- [x] Task 5: console + types + live (AC: 5, 7)
  - [x] Live: legacy-equivalent run #8 (mom EW quintile monthly) ok; **run #9 `fiscal_sens` cap-weighted quarterly top-50 on sp500** — spec persisted whole `{factor: fiscal_sens, top_n: 50, weighting: cap, rebalance: quarterly, ...}`, strategy +30.7% ann / Sharpe 2.05 vs baseline +12.0% (3 rebalances, 170 days); both-selections → 422; `wiki_attention` on sp500 → honest coverage-gate refusal (the documented expectation)
  - [x] Console: factor menu fetched from `/api/signals/factors` (hardcoded 3 gone), weighting/rebalance/top-N controls, run-error banner, spec'd parameters in the run list; types regenerated twice (restarted API; second pass after `dropped_no_mcap` was added to the `Summary` model — the response model had filtered it); tsc + eslint clean; `/backtest` 200
  - [x] Epic: Q6.3 `[BUILT]` (FR-18 ✅ complete), Q9.4 `[PARTIAL — backtest half]`; suites api 45 / backtest 9 / signals 14 green

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] `dropped_no_mcap` accumulates from rebalances that are then SKIPPED (`+=` before `if not w: continue`) — the honesty counter overstates; count only for rebalances that enter the run [engine.py] (HIGH, blind+edge)
- [x] [Review][Patch] Engine XOR is a silent top_n preference (`top_pct = None` before the check makes both-given unreachable) and `top_n<1`/unknown-universe are unguarded at the library surface (negative slice selects all-but-N; typo'd universe reads as "insufficient history") — engine: both-given → error, neither → documented quintile default, `top_n>=1` guard, empty-members → named universe error [engine.py] (MED, blind+edge+auditor)
- [x] [Review][Patch] `raw_factor` dispatch falls through to `_raw_fiscal_sens` for any future unhandled key — explicit branch + terminal raise (guards the single-definition claim) [signals/compute.py] (MED, blind)
- [x] [Review][Patch] `_cap_weights` mislabels: `total<=0` counts cap-BEARING names as "no mcap" (defensive branch; the seam's `>0` filter makes zero-caps absent already) — count = names absent from positive caps; docstring "no positive market cap" [engine.py] (MED, blind)
- [x] [Review][Patch] "Weights fixed between rebalances" overclaims: applying target weights daily IS daily-rebalancing-to-target, not buy-and-hold drift (the old EW engine did the same) — docstring honesty + ledger the buy-and-hold variant as a design option [engine.py] (MED, blind)
- [x] [Review][Patch] `module_conns` kwarg synthesis hardcodes the altdata→alt rename and TypeErrors on any future module; a module-DB connect failure 500s unattributed — explicit module→kwarg map (unknown → 422), connect wrapped → 503 naming the module [router.py] (MED, blind+edge)
- [x] [Review][Patch] Legacy `top_pct` 0.0 sentinel served as data for top_n runs — serve None (model `float | None`) [gateway.py, router.py] (LOW, blind+edge)
- [x] [Review][Patch] `_select_top` tie-break is dict-order — add the figi as secondary sort key (spec reproducibility at quantile cuts) [engine.py] (LOW, blind)
- [x] [Review][Patch] Console: invalid top-N input silently runs a quintile; 422 `detail` unread (generic "run failed"); a thrown fetch leaves the button stuck busy; error-object render hole — validate input client-side with the error banner, read error/detail defensively as strings, try/finally around the run [page.tsx] (MED, blind+edge+auditor)
- [x] [Review][Patch] AC6's promised "delegation params reach the seam" + "spec persisted to SQL" tests missing (auditor F3); quarterly docstring overpromises Jan/Apr/Jul/Oct anchors — add both tests + reword [tests, engine.py] (MED, auditor)
- [x] [Review][Patch] Ledger section missing (auditor F1) + Dev Agent Record empty (F2) — write both [deferred-work.md, story] (LOW, auditor)
- [x] [Review][Defer] Saved paper portfolios hardcode `base_currency="USD"` (pre-existing Q6.4 behavior, wrong label for BRL universes) — deferred, ledgered
- [x] [Review][Defer] Size-definition drift (auditor F4): signals' `_raw_size` filters `> 0`, the deleted engine SQL didn't — 0 of 713,592 live rows affected; signals' definition is the better one; recorded, not reverted — deferred, noted in completion notes

Dismissed as noise (3): "spec stores null dates" (disproven — the locals are reassigned by the defaulting code before the spec is built; run 9 was a defaulted run and persisted concrete dates, and the auditor's spec-replay produced a byte-identical run); repo-wide eslint RED (the C.1-ledgered pre-existing baseline; touched files clean); engine validating weighting/rebalance as 200-error vs router 422 (the engine's error-dict IS its library contract — the run endpoint's ok:false envelope is the established shape for run-time refusals like the coverage gate).

## Dev Notes

### Existing code map (READ before writing)

- `packages/backtest/src/backtest/engine.py` — `_factor_at` (to delete), `_select_top` (gains top_n), `_daily_mean` (baseline keeps; strategy side becomes weighted), `_rebalance_dates` (gains quarterly), `run_backtest` (spec params + persistence), `_DIRECTION` (dies — signals owns direction).
- `packages/signals/src/signals/compute.py` — `FACTORS` (has inputs/method since Q9.2 — `required_modules` parses input prefixes), `_raw_*` functions (the seam wraps them).
- `packages/backtest/src/backtest/{gateway,router}.py`; `apps/web/app/backtest/page.tsx` (FACTORS hardcoded at line 11).
- `packages/backtest/db/` — single change; append `strategy_spec [backtest]`.

### Constraints

1. AR-R2 unchanged: per-module read-only conns; the router opens alt/macro ONLY when the chosen factor requires them (mirror the save_portfolio conditional-connect pattern).
2. No look-ahead: the seam recomputes at each rebalance date (the whole point); never read stored scores.
3. Library-first cross-package reuse = import the signals package (the analytics→portfolios.gateway precedent).
4. Honest counters: dropped-for-no-mcap names counted per rebalance in the run output.
5. Sqitch via Docker (backtest DB); types regen on a restarted API; `uv sync --all-packages` if the venv needs repair (Q9.2 lesson).
6. Ruff 100; suites green (api 45, signals 11, sym 590+1 ledgered, others).
7. Review-theme pre-emption: param ordering pinned in tests; XOR validation is a 422 not a silent preference; docstrings state the vol-definition reconciliation.

### References

- [Source: epics-qrp-roadmap.md — Q6.3, Q9.4, un-park build order]
- [Source: Q9-2-cross-module-signals.md — the FACTORS registry + inputs prefixes this seam builds on]
- [Source: packages/backtest/src; packages/signals/src/signals/compute.py]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Live runs 8/9 + the auditor's spec-replay (run 9's spec -> byte-identical run 10, then deleted) predate the review patches; the patched engine's behavior is pinned by the 13-test suite (incl. the two AC6 tests the auditor caught missing).
- The spec-persistence test needed two fixture iterations (quarterly cadence needs >1 quarter of days; descending raws so the top-N holding has returns) — the engine itself was correct both times.

### Completion Notes List

- **All 7 ACs met (review-hardened).** FR-18 complete: a reproducible strategy spec (any signals factor / top_pct XOR top_n / equal|cap / monthly|quarterly) drives the engine and persists whole; the auditor live-proved reproducibility (spec replay -> byte-identical run). Q9.4's backtest half closed: the engine's bespoke factor SQL is gone — it delegates to `signals.compute.raw_factor` at every rebalance (single definition source; cross-module `fiscal_sens` ran live, cap-weighted quarterly top-50, Sharpe 2.05).
- **Review patches:** dropped_no_mcap no longer counts skipped rebalances; engine XOR errors on both (no silent top_n preference) + top_n>=1 + named unknown-universe guards; `raw_factor` dispatch ends in a raise (future factors can't silently compute the wrong definition); explicit module->kwarg map (unknown module 422, down module 503 naming it); legacy top_pct 0.0 sentinel served as null; deterministic tie-break (figi secondary key); daily-rebalanced-to-target semantics stated honestly (not buy-and-hold); console validates top-N input, reads error/detail defensively, never sticks busy.
- **Auditor's drift audit:** momentum byte-identical; vol monotone (ranks identical); size's `>0` filter is the one drift — 0 live rows affected, recorded.
- Suites: backtest 13/13 (first for the package), signals 14/14, api 45/45; ruff/tsc/eslint clean on touched surfaces.

### File List

- packages/backtest/db/{deploy,revert,verify}/strategy_spec.sql (new) + sqitch.plan (modified)
- packages/backtest/src/backtest/engine.py (rewritten — seam delegation, spec params, honest weighting/counters)
- packages/backtest/src/backtest/gateway.py (modified — spec passthrough, sentinel-null top_pct)
- packages/backtest/src/backtest/router.py (modified — spec request/response models, XOR 422, module conn map)
- packages/backtest/pyproject.toml (modified — signals dep, dev group, lint/pytest config)
- packages/backtest/tests/test_engine.py (new — 13 tests)
- packages/signals/src/signals/compute.py (modified — raw_factor/required_modules/factor_direction seam + terminal dispatch raise)
- packages/signals/tests/test_compute.py (modified — 3 seam tests)
- apps/web/app/backtest/page.tsx (modified — signals-fed factor menu, weighting/rebalance/top-N controls, validated input + error banner)
- apps/web/lib/api-types.ts (regenerated)
- uv.lock (modified)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q6.3 BUILT/FR-18 complete; Q9.4 PARTIAL-backtest)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — Q6.3 section)

## Change Log

- 2026-06-11: Story created (loop link 2: strategy spec + signals→backtest via a public raw_factor seam — one factor-definition source, recompute-at-date preserved).
- 2026-06-11: Implemented + live-verified (runs 8/9; spec persisted; wiki_attention honest refusal); review (3 layers): 11 patches (counter honesty, XOR/topn/universe guards, dispatch raise, module map + 503, sentinel null, deterministic ties, weighting-semantics honesty, console input validation, the two missing AC6 tests, ledger+record), 2 deferred, 3 dismissed (one disproven live). backtest 13/13, signals 14/14, api 45/45. Status -> done.
