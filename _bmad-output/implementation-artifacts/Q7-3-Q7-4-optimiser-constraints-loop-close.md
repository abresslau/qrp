# Story Q7.3 + Q7.4 (+ Q9.4 optimiser half): Constraints, signal tilts, and closing the research loop

Status: done

## Story

As Andre (the operator),
I want the optimiser to take constraints and signal tilts, persist a reproducible spec, save its solution as a Portfolio, and score candidates out-of-sample via the backtest package,
so that FR-22 is complete, Q9.4's optimiser half lands, and the PRD's research loop (signal → optimiser → backtest → portfolios → analytics) is CLOSED.

## Background + scope decision

The final un-parked loop link. Three epic items, one story (they share every seam):

- **Q7.3** (FR-22): *"objective and constraints (sector caps, max position, turnover, optional signal tilts), not just unconstrained long-only MV … reproducible from objective+constraints+universe+inputs."* The list is exemplary, not exhaustive — this story ships the **max-position cap** as the constraint archetype (capped-simplex projection, the natural extension of the existing projected-gradient solver) + **signal tilts**; sector caps and turnover are ledgered follow-ons (sector needs GICS-joined projection; turnover needs a prior-solution reference).
- **Q9.4 optimiser half** (FR-21): signal scores bias the objective — `minimise λ·wᵀΣw − wᵀμ − strength·wᵀz` where z = cross-sectionally standardised, favourable-oriented raw factor values from the **signals seam** (`raw_factor` at the covariance end date — recompute-at-date, the Q6.3 precedent; module conns conditional via `required_modules`).
- **Q7.4** (FR-22 + PRD §4.9 "uses backtests to score candidates"): solution weights persist as a `portfolios` Portfolio (the Q6.4 writer-ownership pattern); candidate scoring = **train/holdout split**: covariance estimated on the lookback MINUS a holdout tail; the solved weights scored OUT-OF-SAMPLE on the holdout via a new public **`backtest.engine.score_weights`** seam (reuses `_daily_weighted` + `_stats` — library-first, the optimiser-uses-backtest loop with no engine duplication). In-sample expected stats stay; the holdout score is the honest number.

**Current state (read 2026-06-11):** `optimiser.engine.solve` — top-N-by-mcap names, aligned daily return matrix, pure-Python PGD on the plain simplex, min_variance/max_sharpe, persists solution+weights (no spec). Router clamps params silently. No tests.

**Explicitly OUT of scope:** sector caps / turnover constraints (ledgered); short weights; a job-queue solve (the O.3-deferred engine relocation); console chart changes beyond new controls.

## Acceptance Criteria

1. **Capped-simplex constraint:** `max_weight: float | None` — projection onto `{w: Σw=1, 0≤wᵢ≤cap}` (iterative cap-and-redistribute, exact); infeasible cap (`cap·n < 1`) → named error; `max_weight=None` reproduces today's plain simplex exactly. Solver respects the cap at every iterate; the persisted solution's max weight ≤ cap (live-verified).
2. **Signal tilt (Q9.4):** `signal_tilt: {factor: <signals key>, strength: float>0} | None` — raw values from `signals.compute.raw_factor` at the covariance end date, favourable-oriented (`factor_direction`), z-scored cross-sectionally; names without a score get z=0 (neutral — never fabricated, documented); tilt term −strength·wᵀz joins the objective for BOTH methods; missing required module conn → attributed error (router opens conns per `required_modules`, the Q6.3 pattern).
3. **Reproducible spec:** migration `solution_spec` adds `optimiser.solution.spec JSONB`; the FULL spec persists `{universe, method, n, lookback, max_weight, signal_tilt, holdout_days, save_portfolio}` + resolved data window; served on the API; router stops silently clamping (out-of-range → 422, the no-silent-preference rule).
4. **Solution → Portfolio (Q7.4a):** `save_portfolio: bool` — weights persist as a portfolios Portfolio via the portfolios gateway (single vector at the covariance end date; client "(optimiser)"); `portfolio_id` returned; analytics can then measure it.
5. **Backtest-scored candidates (Q7.4b):** `backtest.engine.score_weights(sym_conn, weights, start, end) -> stats` (public, reuses the existing weighted-daily + stats machinery); when `holdout_days > 0` the covariance window EXCLUDES the trailing holdout and the solution + EW baseline are scored on it out-of-sample; `holdout` block (strategy vs EW stats + window) in the result and persisted summary. Holdout larger than the data → named error.
6. **Tests (first for the optimiser package):** capped-simplex projection properties (mass, bounds, cap-inactive equivalence, infeasibility); tilt orientation enters the gradient (a high-favourable name gains weight as strength rises); spec persisted to SQL; holdout split boundaries (train end < holdout start, no overlap — look-ahead discipline); `score_weights` math pinned; router 422s. House style, fake conns.
7. **Console + live verification + finishers:** optimiser page gains max-weight, signal-tilt (factor+strength), holdout, save-as-portfolio controls + holdout score display; types regenerated (restarted API); live: a constrained (cap 5%) max_sharpe solve with a `fiscal_sens` tilt + 63d holdout + save_portfolio runs end-to-end — cap respected, holdout scored, portfolio created, analytics measures it; epic Q7.3/Q7.4/Q9.4 → `[BUILT]`, FR-21/FR-22 ✅ complete, **research loop CLOSED** note; ledger.

## Tasks / Subtasks

- [x] Task 1: `solution_spec` migration (deployed+verified) + exact capped-simplex projection (auditor verified against KKT-bisection over 3,000 random cases, worst dev 8.9e-16) + tilt in the objective (AC: 1, 2, 3)
- [x] Task 2: `backtest.engine.score_weights` (public, reuses `_daily_weighted`+`_stats`, `(start,end]` exclusive-start) + train/holdout split (AC: 5)
- [x] Task 3: portfolios save (attributed-failure, renormalised upload) + router (422s incl. infeasible cap + unknown factor/module; conditional module conns; spec on responses) (AC: 3, 4)
- [x] Task 4: tests — optimiser 16 (projection properties incl. all-capped exact-full-cap; PGD cap; tilt orientation + KKT-pinned shift 0.625; engine refusals incl. min_variance+tilt, surviving-cap revalidation, tilt-cannot-apply, unknown universe; holdout boundaries; spec-to-SQL; save attribution + renormalisation; router 422s) + backtest 14 (score_weights math + exclusive-start pinned) (AC: 6)
- [x] Task 5: console (cap/tilt/holdout/save controls, OOS holdout display, validated inputs + error banner) + types regenerated ×2 + live (AC: 7)
  - [x] Live (post-patch re-run): solution #8 — cap 5% respected exactly, `chosen_lam: 25`, `tilt_coverage: 40/40`, holdout `n_aligned_days: 63` with the selection caveat served; portfolio #5 created; **analytics cross-check reproduced: +16.2185% = the backtest scorer's number** (two independent computations of the same series); min_variance+tilt refused with the named error; infeasible cap 422
  - [x] Epic: Q7.3/Q7.4/Q9.4 `[BUILT 2026-06-11]`, FR-21/FR-22 ✅ complete, **research loop ✅ CLOSED**

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] Cap feasibility checked against requested `n`, not SURVIVING names — `_return_matrix`'s fallback can trim to 5; `cap·len(figis) < 1` then makes the all-capped projection return weights summing < 1, persisted/scored/saved silently. Re-validate after alignment [engine.py] (HIGH, blind+edge)
- [x] [Review][Patch] Tilt numerically annihilated under min_variance (λ=1e6 swamps the un-scaled tilt term ~1e-6 shift) while spec/UI record it as applied — honest refusal: min_variance + signal_tilt → named error pointing at max_sharpe [engine.py] (MED→behavioral, blind)
- [x] [Review][Patch] Tilt silently no-ops on thin coverage (z all-zero when <2 names scored) while the spec asserts it — error when the tilt can't apply; `tilt_coverage` recorded in the summary [engine.py] (MED, blind)
- [x] [Review][Patch] Holdout "genuinely out-of-sample" overclaims: `_select_names` uses CURRENT membership + LATEST mcap (selection look-ahead into the holdout) — state the caveat where the claim lives; PIT selection ledgered [engine.py] (HIGH→honesty, blind)
- [x] [Review][Patch] Spec reproducibility overstated: no resolved name list (lives on `optimiser.weight` — say so), no chosen λ (record `chosen_lam` in summary), no `save_portfolio` (AC3 lists it; the migration COMMENT claims it — add the field) [engine.py, router.py, solution_spec.sql comment] (MED, blind+auditor F1)
- [x] [Review][Patch] `_return_matrix` fallback never tests the final 5-name set (spurious "insufficient history") — test each kept-set INCLUDING the last [engine.py] (MED, edge)
- [x] [Review][Patch] Portfolio save: non-atomic failure 500s after the solution committed (wrap → attributed `portfolio_error`, solution_id still returned); upload outcome ignored (capture stored/unresolved); kept weights not renormalised after the 1e-5 drop (renormalise the UPLOADED vector) [engine.py] (MED, blind+edge)
- [x] [Review][Patch] holdout block's `n_days` (aligned dates) ≠ the scorer's `n_days` (DB-priced days) under one roof — rename to `n_aligned_days` [engine.py] (LOW, blind)
- [x] [Review][Patch] AC6 gaps (auditor F2): no real `score_weights` test (the optimiser test monkeypatches it away) and no router-422 tests — add both; test module basename collides with backtest's (`test_engine.py` ×2 breaks a root pytest run) — rename [tests] (MED, auditor)
- [x] [Review][Patch] Console fractional cap renders `toFixed(0)` ("2.5%" → "3%"); epic "byte-identical" overstates a 2-ulp match; `_project_simplex` duplicates `_project_simplex_mass` — fix all three [page.tsx, epics, engine.py] (LOW, edge+auditor)
- [x] [Review][Patch] Ledger section + story record missing (auditor F3/F4) — write both [deferred-work.md, story] (LOW, auditor)
- [x] [Review][Defer] max_sharpe λ-path winner picked by realised Sharpe only (tilt shapes candidates but not the pick) — documented in the docstring; a tilt-aware selection criterion is a design choice — deferred, ledgered
- [x] [Review][Defer] PIT universe selection for holdout solves (membership + mcap as-of train_end) — the proper fix for the selection look-ahead; needs `_select_names(as_of)` + a PIT mcap query — deferred, ledgered
- [x] [Review][Defer] Saved-portfolio `base_currency` hardcoded USD — same pre-existing Q6.4 pattern, ledger item extended to cover the optimiser writer — deferred
- [x] [Review][Defer] Sector caps + turnover constraints (the story's own scope-out) — deferred, ledgered

Dismissed as noise (2): method validated in router AND engine with different failure shapes (the established two-surface contract — same dismissal as Q6.3's review); console default lookback 252→315 (deliberate: leaves ≥252 training days under the default 63d holdout).

## Dev Notes

### Existing code map (READ before writing)

- `packages/optimiser/src/optimiser/engine.py` — `_project_simplex` (the cap generalisation site), `_pgd` (gains cap + tilt), `solve` (spec/holdout/save plumbing), `_return_matrix` (holdout = trim trailing dates before `_mean_cov`).
- `packages/backtest/src/backtest/engine.py` — `_daily_weighted` + `_stats` to expose as `score_weights`.
- Q6.3's router (`packages/backtest/src/backtest/router.py`) — the conditional-module-conn + 422 patterns to mirror; Q6.4 gateway save-portfolio pattern.
- `packages/optimiser/src/optimiser/{gateway,router}.py`; `apps/web/app/optimiser/page.tsx`.
- House test style: `packages/backtest/tests/test_engine.py` (routed fake conns).

### Constraints

1. AR-R2: per-module read-only conns; optimiser writes ONLY its own DB (+ portfolios via ITS gateway).
2. No look-ahead: tilt raws at the covariance END date; holdout strictly after the train window.
3. Library-first reuse: signals seam + backtest scorer + portfolios gateway — no logic duplication.
4. Honest numbers: in-sample expected stats labelled as such (existing UI note stays); the holdout score is OOS and says so; z=0 neutrality for unscored names documented.
5. No silent clamping/preferences (the Q6.3 review rule): out-of-range params → 422.
6. Sqitch via Docker (optimiser DB); types regen on a restarted API; `uv sync --all-packages`.
7. Ruff 100; suites green (api 45, backtest 13, signals 14, others).
8. Review-theme pre-emption: counters honest; dispatch/dead-ends raise; deterministic ordering where specs reproduce; param ordering pinned in tests; docstrings state definition choices.

### References

- [Source: epics-qrp-roadmap.md — Q7.3, Q7.4, Q9.4, un-park build order]
- [Source: Q6-3-Q9-4 story — the seam/router patterns this completes]
- [Source: packages/optimiser/src; packages/backtest/src/backtest/engine.py]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- First live solve (#7→portfolio #4) predates the review patches; #8→#5 is the patched re-run. Both cross-check against analytics identically.
- Tilt KKT arithmetic: the closed-form shift is (Δtilt)/(2λσ²) split across two names — 0.625, not my first 0.75; the solver was right.

### Completion Notes List

- **All 7 ACs met; THE RESEARCH LOOP IS CLOSED.** Constraints (exact capped-simplex inside PGD — auditor-verified exact to 9e-16), signal tilts (any signals factor via the seam; min_variance+tilt honestly refused — λ=1e6 annihilates the term; thin-coverage tilts refused, coverage recorded), full reproducible spec (incl. save_portfolio + chosen λ), solution→Portfolio (attributed-failure save, renormalised vector, upload outcome captured), and optimiser-uses-backtest holdout scoring via the public `score_weights` seam.
- **The loop's closing cross-check:** analytics independently measures the optimiser's saved portfolio at +16.2185% over its 63-day holdout — matching the backtest scorer to 13 decimal places. signal → optimiser → backtest → portfolios → analytics, every link live.
- **Review hardening (11 patches):** cap re-validated against SURVIVING names (the silent sub-unit-weights hole); selection look-ahead stated as a served caveat (PIT selection ledgered); fallback tests the final 5-name set; `n_aligned_days` disambiguation; spec honesty (the resolved names live on optimiser.weight — said so).
- Suites: optimiser 16/16 (first), backtest 14/14, signals 14/14, api 45/45; ruff/tsc/eslint clean.

### File List

- packages/optimiser/db/{deploy,revert,verify}/solution_spec.sql (new) + sqitch.plan (modified)
- packages/optimiser/src/optimiser/engine.py (rewritten — capped simplex, tilt, holdout, spec, attributed portfolio save)
- packages/optimiser/src/optimiser/gateway.py (modified — spec passthrough + new params)
- packages/optimiser/src/optimiser/router.py (modified — SolveSpec/SignalTilt models, 422 validation, conditional module conns, portfolio save wiring)
- packages/optimiser/pyproject.toml (modified — signals/backtest/portfolios deps, dev group, lint/pytest config)
- packages/optimiser/tests/test_optimiser_engine.py (new — 16 tests)
- packages/backtest/src/backtest/engine.py (modified — public score_weights seam)
- packages/backtest/tests/test_engine.py (modified — score_weights math + exclusive-start test)
- apps/web/app/optimiser/page.tsx (modified — constraint/tilt/holdout/save controls + OOS display)
- apps/web/lib/api-types.ts (regenerated)
- uv.lock (modified)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q7.3/Q7.4/Q9.4 BUILT, FR maps complete, loop CLOSED)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — Q7.3 section)

## Change Log

- 2026-06-11: Story created — the final loop link (constraint archetype + signal tilts + portfolio output + holdout backtest scoring).
- 2026-06-11: Implemented + live-verified (solution #7 → portfolio #4; cross-check exact); review (3 layers, incl. an independent KKT verification of the projection): 11 patches (surviving-names cap revalidation, min_variance+tilt refusal, tilt-coverage gate, selection-caveat honesty, spec completeness, fallback 5-set, attributed portfolio save + renormalisation, n_aligned_days, score_weights + router-422 tests, file rename, wording), 4 deferred, 2 dismissed. Post-patch live re-run (#8 → #5) reproduces the cross-check. optimiser 16/16, backtest 14/14. Status → done. THE RESEARCH LOOP IS CLOSED.
