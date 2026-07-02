# Story: Optimiser min-variance long/short (covariance-aware dollar-neutral book)

Status: review

<!-- Created via bmad-create-story 2026-07-02. The follow-on to backtest-lowvol-longshort-sharpe
(that story's "Follow-on story" section is the authoritative scope seed). Replaces the inverse-vol
weighting heuristic with a TRUE min-variance dollar-neutral solve that exploits the covariance
(correlations), pushing book vol lower than per-name inverse-vol can. Spans the `optimiser` package
(a new long/short min-variance solve reusing its projected-gradient machinery) + the `backtest`
engine (a new `weighting='min_variance'` mode that calls it per rebalance) + a short `borrow_bps`
holding cost. The KEY insight that makes this tractable: the Sharpe SELECTION pre-signs each name
(long/short), so the projection is CONVEX — two independent capped-simplex projections per side, NOT
the NP-hard general long/short cardinality problem. -->

## Story

As a quant researcher,
I want the low-vol long/short book weighted by a **true min-variance solve** (covariance-aware) rather
than the per-name inverse-vol heuristic,
so that the dollar-neutral portfolio exploits correlations/diversification to reach a materially lower
realised book volatility — the literal "targeting 0 vol" — while staying market-neutral and
Sharpe-ranked.

## Background / current state (read THIS before coding)

### What already shipped (the predecessor, on `main`)

`backtest-lowvol-longshort-sharpe` (done, merged) built: the `signals.sharpe_tr` factor; the backtest
long/short engine — `_select_long_short` (sticky Sharpe-ranked selection), `_neutral_weights` (signed
dollar-neutral weighting: `equal` | `inverse_vol`), the net-zero `_daily_weighted` GROSS-denominator
fix, book diagnostics, and `weighting ∈ (equal, cap, inverse_vol)`. This story adds a FOURTH weighting
mode, `min_variance`, and its optimiser backend. **Do not re-touch the selection or the net-zero
P&L logic — they are correct and tested.** The min-variance mode only changes how the *weights* are
computed once the longs/shorts are chosen.

### The convexity insight (why this is tractable, not NP-hard)

A general long/short min-variance with free signs is non-convex (cardinality/sign is combinatorial).
But here the **sign of every name is already decided by the Sharpe selection** (longs = best
`sharpe_tr`, shorts = worst). With signs fixed, the problem is a convex QP:

> minimise `wᵀΣw` s.t. `Σ_{i∈long} wᵢ = +long_mass`, `Σ_{i∈short} wᵢ = −short_mass`,
> `0 ≤ wᵢ ≤ cap` for longs, `−cap ≤ wᵢ ≤ 0` for shorts.

The feasible set is the **product of two capped simplices** (the long weights on a `+long_mass`
capped simplex; the short *magnitudes* on a `short_mass` capped simplex, then negated). Euclidean
projection onto a product set = project each block independently — and the optimiser ALREADY has
`_project_capped_simplex` / `_project_simplex_mass`. So `_pgd` converges with a per-side projection;
**no new hard math.** Dollar-neutral default: `long_mass = short_mass = 0.5` → net 0, gross 1.

### The three components + their EXACT current seams

**optimiser** (`packages/optimiser/src/optimiser/engine.py`) — the mean-variance solver:
- `_pgd(cov, mean, lam, tilt, cap, iters)` (266–280): projected-gradient minimiser; builds `project`
  internally as `_project_capped_simplex` (cap) or `_project_simplex` (no cap). The min-variance path
  uses `lam=1e6`, `tilt=None` → grad `= 2·lam·Σw`, so the projection carries all the constraints.
- `_project_capped_simplex(v, cap)` (221–248) and `_project_simplex_mass(v, mass)` (251–263): the
  reusable projection primitives — the long/short projection composes TWO of these.
- `_mean_cov` (123–137) + `_const_corr_shrinkage` (140–209, Ledoit-Wolf, the default): the risk model.
- `solve(...)` (316–497): `method ∈ METHODS = ("min_variance","max_sharpe")` (41). Selects names by
  latest mcap (`_select_names`), builds the aligned return matrix (`_return_matrix`), the covariance,
  runs `_pgd`, persists `optimiser.solution` + `optimiser.weight` + the spec. **`METHODS` (line 41)
  and the router method check gate the allowed methods — both are code-only (no DB CHECK).**
- **`optimiser.weight.weight` is a bare `DOUBLE PRECISION NOT NULL` — NO CHECK — so negative weights
  are accepted with NO migration** (`packages/optimiser/db/deploy/optimiser.sql:25–31`; `method` has
  no CHECK either). Only a COMMENT update is warranted.
- `_return_matrix` (76–120) reads `fact_returns` bounded at `max(as_of_date) − lookback` — i.e. the
  GLOBAL latest date. **This is fine for the optimiser's own "solve as of today" use, but is a
  LOOK-AHEAD trap if reused verbatim inside a historical backtest rebalance** (see the critical
  guardrail below).

**backtest** (`packages/backtest/src/backtest/engine.py`) — the walk-forward engine:
- `WEIGHTINGS = ("equal","cap","inverse_vol")` (33) — add `"min_variance"`.
- `_neutral_weights(eq_conn, longs, shorts, d, weighting, long_mass, short_mass)` (~107–155): today
  branches `inverse_vol` (reads `fact_asset_metrics`) vs `equal`. Add a `min_variance` branch that
  builds a covariance for `longs ∪ shorts` AS OF `d` and calls the optimiser helper. Keep the
  net-0/gross-1 contract and the no-history drop-and-count (mirrors `dropped_no_vol`).
- Rebalance loop (~423–468): `want_shorts` path already computes `longs, shorts` and passes
  `long_mass, short_mass`. The min-variance weights slot in exactly where inverse-vol does.
- Cost model (485–538): `turnover_at[d] = 0.5·Σ|Δw|` → `cost_on_date` (a ONE-TIME per-rebalance
  turnover charge). The short **borrow cost is a PERIODIC HOLDING charge**, structurally different —
  accrued per day on the short leg's gross exposure (see AC-4).
- `score_weights` (optimiser's out-of-sample scorer) already routes through `_daily_weighted`, so a
  signed min-variance vector scores correctly with the gross-denominator fix.

**optimiser router/gateway** (`packages/optimiser/src/optimiser/router.py`, `gateway.py`):
- `OptSolveRequest` (79–94): `method: str` (bare), validated at `solve_ep` (109–111) against
  `("min_variance","max_sharpe")` → 422. Add the new method + long/short sizing fields.

### The design (how it maps to code)

1. **Optimiser core — a reusable pure helper** `min_variance_long_short(cov, long_idx, short_idx, *,
   long_mass=0.5, short_mass=0.5, cap=None, iters=800)` → signed weight vector. Internally: `_pgd`
   with `lam=1e6`, `mean`/`tilt` zeroed, and a NEW projection `_project_long_short(v, long_idx,
   short_idx, long_mass, short_mass, cap)` that (a) projects `v[long_idx]` onto the `+long_mass`
   (capped) simplex, (b) projects `−v[short_idx]` (the short magnitudes) onto the `short_mass`
   (capped) simplex and negates, (c) reassembles the full vector. Convex → converges. Feasibility:
   `cap·|long| ≥ long_mass` and `cap·|short| ≥ short_mass` (validate; mirror the existing cap check).

2. **Optimiser `solve` gains `method='min_variance_long_short'`** — selects a candidate pool, ranks it
   by a signals factor (default `sharpe_tr`), takes the top `long_n`/`long_pct` as longs and the
   bottom `short_n`/`short_pct` as shorts, builds the covariance over the union AS OF the train end,
   calls the helper, and persists a SIGNED solution (net≈0, gross≈1). New spec fields: the ranking
   `factor` (default `sharpe_tr`), `long_n`/`long_pct`, `short_n`/`short_pct`, `net_target` (default
   0.0), `gross_target` (default 1.0), `cap`. Reuses the signal seam (`raw_factor`) already imported.

3. **Backtest `weighting='min_variance'`** — at each rebalance, `_select_long_short` gives the signed
   name sets; `_neutral_weights`'s new branch builds the covariance for those names AS OF `d`
   (bounded read — see guardrail) and calls `min_variance_long_short`. Names lacking aligned history
   are dropped and counted (`dropped_no_cov`, alongside `dropped_no_vol`). If a leg empties, skip the
   rebalance (existing guard). Weights are net-0/gross-1 signed → the P&L and turnover paths are
   unchanged.

4. **Short borrow cost** — `borrow_bps` (annual, on short gross) accrues as a DAILY holding drag:
   `borrow_drag[d] = short_gross(period(d)) · (borrow_bps/1e4) / 252`, added to `cost_on_date[d]` for
   every common day (not just rebalance days). Report `borrow_cost_total` and keep the turnover cost
   separate. Long-only and non-borrow runs are unaffected (`borrow_bps=0` default).

### CRITICAL guardrails (do NOT deviate without noting why)

- **Look-ahead in the backtest covariance is the #1 risk.** The optimiser's `_return_matrix` bounds on
  the GLOBAL `max(as_of_date)`. Inside a historical rebalance at date `d`, the covariance MUST read
  `fact_returns` with `as_of_date <= d AND as_of_date > d - lookback` — exactly the as-of bounding
  `_raw_vol`/`_neutral_weights` already use. **Write a backtest-local as-of-bounded return-matrix
  builder (or pass `d` as the upper bound); do NOT call the optimiser's global-max `_return_matrix`
  verbatim.** A behavioural test MUST assert the covariance read is upper-bounded by the rebalance
  date.
- **Signs come from the SELECTION, never the solve.** `min_variance_long_short` takes pre-signed
  `long_idx`/`short_idx`; it never decides a sign. This is what keeps it convex.
- **Dollar-neutral net-0/gross-1 by construction** (`long_mass=short_mass=0.5`); do not renormalise by
  net Σw (the predecessor's net-zero trap). The signed vector flows through the unchanged
  `_daily_weighted` gross path.
- **Performance:** `_const_corr_shrinkage` is O(n²·t) pure-Python; a 98+98=196-name book over ~25
  monthly rebalances is ≈ 300× the optimiser's single n≲60 solve — acceptable (~seconds) but real.
  Cap the covariance name count via a `cov_names_cap` guard (default e.g. 120) and/or allow
  `cov_method='sample'`; `log`/report if the cap trimmed names. Do NOT silently truncate.
- **Keep long-only + the existing L/S weightings byte-identical** — all new behaviour is gated behind
  `weighting=='min_variance'` (backtest) / `method=='min_variance_long_short'` (optimiser) and
  `borrow_bps>0`.
- **No numpy, no factor-model covariance, no PIT universe selection, no tilt on the L/S solve** — all
  ledgered follow-ons.

## Acceptance Criteria

1. **Optimiser projection + helper.** A pure `_project_long_short(v, long_idx, short_idx, long_mass,
   short_mass, cap)` returns a vector whose long block sums to `+long_mass` (each in `[0,cap]`) and
   short block sums to `−short_mass` (each in `[−cap,0]`); and `min_variance_long_short(cov,
   long_idx, short_idx, ...)` returns a signed min-variance weight vector via `_pgd` over that
   product set. Unit-tested: net≈0, gross≈1, sign-correct, cap respected, and that a
   negatively-correlated long/short pair gets LOWER book variance than the inverse-vol weights would
   (the covariance actually being exploited).
2. **Optimiser solve mode.** `solve(method='min_variance_long_short', ...)` ranks a candidate pool by
   the `factor` (default `sharpe_tr`, direction-aware), splits long/short by `long_n`/`long_pct` &
   `short_n`/`short_pct`, solves the signed min-variance book, and persists `optimiser.solution` +
   negative-weighted `optimiser.weight` rows + the spec (`factor`, leg sizes, `net_target`,
   `gross_target`, `cap`, `cov_method`). `METHODS` + the router method-check accept the new method
   (422 otherwise). No DB migration for negatives (add only the `optimiser.weight` sign comment).
3. **Backtest weighting mode.** `weighting='min_variance'` builds a covariance for the selected
   longs∪shorts **as of the rebalance date** (as-of-bounded read — no look-ahead) and weights the
   book by the min-variance solve; net≈0, gross≈1; names with insufficient aligned history are
   dropped and counted (`dropped_no_cov`). Long-only and the `equal`/`cap`/`inverse_vol` paths stay
   byte-identical. `WEIGHTINGS` gains `"min_variance"`; router/spec accept it; `cap` weighting still
   rejected with shorts.
4. **Short borrow cost.** `borrow_bps` (annual, default 0) accrues a daily holding drag on the short
   leg's gross exposure, added to the net daily return for EVERY common day of the holding period
   (not just rebalance days); `borrow_cost_total` reported in the summary, separate from the turnover
   `cost_drag_total`. `borrow_bps=0` and long-only runs are unaffected.
5. **Reproducible spec + API.** `BacktestRunRequest`/`StrategySpec` gain `borrow_bps` (and accept
   `weighting='min_variance'`); `OptSolveRequest` gains the L/S fields + method. The persisted spec
   round-trips. Router validates: `weighting` enum includes `min_variance`; `min_variance` requires a
   short selector; `borrow_bps` range-checked; optimiser long/short XOR sizing validated.
6. **Lower book vol than inverse-vol (the payoff), measurably.** A live sp500 smoke compares three
   dollar-neutral books over the SAME window/selection: `inverse_vol` vs `min_variance` (both vs the
   long-only top-Sharpe book). The min-variance book's realised annualised vol is **≤** the
   inverse-vol book's (the covariance buys diversification); net≈0/gross≈1 for both. Record the
   numbers in the Dev Agent Record. (If min-variance does NOT beat inverse-vol on the sample, record
   that honestly with the likely cause — estimation error — rather than fabricating a win.)
7. **Tests + gates.** Unit tests: the signed projection (mass/bounds/sign), the min-variance helper
   (covariance-exploited variance reduction), the optimiser solve mode (persists signed weights +
   spec, method 422), the as-of-bounded backtest covariance read (no look-ahead), the borrow-cost
   accrual (periodic, short-gross, separate from turnover), and the weighting/borrow validation.
   optimiser + backtest + signals suites green; ruff clean; `sym validate` unchanged.

## Design decisions & guardrails (recap for the dev agent)

- Convex because signs are pre-set by selection → product-of-two-capped-simplices projection; reuse
  `_project_capped_simplex`/`_project_simplex_mass`. `_pgd` with `lam=1e6`, zero mean/tilt.
- As-of-bound the backtest covariance read at the rebalance date (NOT the optimiser's global max) —
  the load-bearing no-look-ahead fix. Test it.
- Net-0/gross-1 signed weights flow through the UNCHANGED `_daily_weighted` gross path.
- Borrow cost is a periodic holding charge (short gross × bps/252/day), distinct from turnover cost.
- Cap covariance name count (perf); never silently truncate — report it.
- Gate everything behind the new method/weighting; keep all existing paths byte-identical.

## Tasks / Subtasks

- [x] **Optimiser projection + helper** (AC: 1) — `_project_long_short` (compose two capped-simplex
  projections, negate the short block) + `min_variance_long_short(cov, long_idx, short_idx, *,
  long_mass, short_mass, cap, iters)` via `_pgd`; feasibility check (`cap·|leg| ≥ mass`). Unit tests
  incl. a negatively-correlated pair getting lower variance than inverse-vol.
- [x] **Optimiser solve mode** (AC: 2, 5) — `method='min_variance_long_short'` in `solve`: factor-rank
  → sign → union covariance → helper → persist signed weights + spec; extend `METHODS`, the router
  `OptSolveRequest`/validation, and the `optimiser.weight` sign COMMENT (no migration).
- [x] **Backtest weighting mode + as-of covariance** (AC: 3) — a backtest-local as-of-bounded
  return-matrix/covariance builder (upper bound = rebalance date `d`); `_neutral_weights`
  `min_variance` branch calling `min_variance_long_short`; drop+count no-history names
  (`dropped_no_cov`); `WEIGHTINGS += "min_variance"`; `cov_names_cap` guard.
- [x] **Short borrow cost** (AC: 4) — `borrow_bps` periodic holding drag on short gross across every
  common day of each holding period; `borrow_cost_total` in the summary, separate from turnover.
- [x] **Spec + router** (AC: 5) — `borrow_bps` + `weighting='min_variance'` on
  `BacktestRunRequest`/`StrategySpec`; L/S fields + method on `OptSolveRequest`; validation
  (weighting enum, min_variance-requires-shorts, borrow_bps range, optimiser L/S XOR).
- [x] **Tests + live smoke + docs** (AC: 6, 7) — the unit tests above + the inverse-vol-vs-min-variance
  sp500 smoke (AC-6); note the min-variance mode + borrow cost in `docs/data-conventions.md`.

## Dev Notes

- **Read before coding** (UPDATE files): `optimiser/engine.py` (`_pgd` 266–280, `_project_capped_simplex`
  221–248, `_project_simplex_mass` 251–263, `_mean_cov` 123–137, `_const_corr_shrinkage` 140–209,
  `solve` 316–497, `_return_matrix` 76–120 — the look-ahead trap, `METHODS` 41), `optimiser/router.py`
  (`OptSolveRequest` 79–94, `solve_ep` method check 109–111), `backtest/engine.py`
  (`_neutral_weights`, the `want_shorts` rebalance branch, the cost block 485–538, `WEIGHTINGS` 33),
  `backtest/router.py` (`BacktestRunRequest`/`StrategySpec`/`Summary`).
- **No DB migration for negatives** — `optimiser.weight.weight`/`solution.method` have no CHECK
  (verified). Add only the sign COMMENT.
- **Look-ahead**: do NOT reuse the optimiser's `_return_matrix` verbatim in the backtest — bound the
  read at the rebalance date.
- **Don't "fix" the net-zero `_daily_weighted` or the sticky selection** — both are correct/tested from
  the predecessor.
- **Environment**: `python3` not on PATH → `uv run --project packages/<pkg> …`; ruff line limit 100;
  Docker/sqitch down → apply any migration directly (none expected here). The backtest smoke needs
  `fact_asset_metrics` populated for sp500 (already backfilled for 562 members, 2024-07..2026-07).
- **Test fixtures**: optimiser tests use the `_RoutedConn`/`_Cur` SQL-substring routing
  (`packages/optimiser/tests/test_optimiser_engine.py:21–58`); backtest tests the same pattern. Model
  the projection tests on `test_capped_projection_respects_mass_and_bounds` and `test_pgd_respects_the_cap`.

### References

- [Source: `packages/optimiser/src/optimiser/engine.py` — _pgd 266–280, _project_capped_simplex 221–248,
  _project_simplex_mass 251–263, _const_corr_shrinkage 140–209, solve 316–497, _return_matrix 76–120,
  METHODS 41]
- [Source: `packages/optimiser/src/optimiser/router.py` — OptSolveRequest 79–94, solve_ep 109–111]
- [Source: `packages/optimiser/db/deploy/optimiser.sql` — weight table 25–31 (NO CHECK), method 15]
- [Source: `packages/backtest/src/backtest/engine.py` — WEIGHTINGS 33, _neutral_weights, want_shorts
  rebalance branch, cost model 485–538, _daily_weighted gross path]
- [Source: `packages/backtest/src/backtest/router.py` — BacktestRunRequest/StrategySpec/Summary]
- [Spec: `backtest-lowvol-longshort-sharpe.md` "Follow-on story" section — the scope seed]
- [`docs/data-conventions.md` — the long/short backtest conventions section to extend]

## Follow-on (OUT OF SCOPE here)

- **Factor-model / numpy covariance** for larger n (the O(n²·t) pure-Python shrinkage caps practical
  book size); incremental/cached covariance across rebalances.
- **PIT universe selection** in the optimiser (currently latest-mcap/current-member — a stated
  selection-look-ahead caveat).
- **Tilt-aware L/S** (a max-Sharpe long/short, or a return term in the L/S objective).
- **Financing/rebate modelling** beyond a flat `borrow_bps` (per-name borrow, hard-to-borrow tiers).

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Opus 4.8, 1M context) — bmad-dev-story.

### Debug Log References

- `python3` not on PATH → `uv run --project packages/<pkg> …`. ruff gate = `src` (limit 100).
- New workspace dependency: `backtest` now depends on `optimiser` (min_variance delegates to the
  optimiser's covariance solve). The optimiser already depends on backtest (`score_weights`), so
  this is a two-way workspace dep — uv resolves it fine, and the runtime import cycle is avoided by
  a FUNCTION-LOCAL import inside `_min_variance_weights` (both modules are fully loaded by call time).
- No DB migration: `optimiser.weight.weight` / `solution.method` have no CHECK (verified) — negatives
  and the new method insert freely; only a doc COMMENT was added.

### Completion Notes List

- **AC-1 projection + helper.** `_project_long_short` = Euclidean projection onto the product of two
  (capped) simplices (long block → +mass; short magnitudes → mass, negated); `_project_capped_simplex`
  generalised with a `mass` param (default 1.0 → long-only byte-identical). `min_variance_long_short`
  solves the signed book via `_pgd` (generalised to accept an injected `project`) over that set —
  convex because signs are pre-fixed. Tested: masses/bounds/signs, cap per leg, and that a
  negatively-hedged pair reaches strictly lower book variance than the inverse-vol vector.
- **AC-2 optimiser solve mode.** `method='min_variance_long_short'` (`_long_short_solve`): ranks the
  roster by `factor` (default sharpe_tr), top→long / bottom→short, builds the union covariance,
  solves, persists SIGNED `optimiser.weight` rows + spec (factor, leg sizes, net/gross target). Router
  + engine accept/validate the method; `METHODS` extended.
- **AC-3 backtest weighting.** `weighting='min_variance'` → `_min_variance_weights` builds a shrinkage
  covariance over the selected longs∪shorts via `_aligned_returns_asof` (read strictly `<= d` — the
  look-ahead guardrail; NOT the optimiser's global-max `_return_matrix`) and calls the helper. Per-leg
  `cov_leg_cap` (60) keeps it tractable; no-history names dropped/counted (`dropped_no_cov`). Long-only
  + equal/cap/inverse_vol paths byte-identical.
- **AC-4 borrow cost.** `borrow_bps` accrues a per-day short-gross financing drag across every common
  day of the holding period (distinct from the one-time turnover cost); `borrow_cost_total` reported
  separately; any modelled cost (turnover OR borrow) flips the headline to net (`costed`).
- **AC-5 spec/API.** `BacktestRunRequest`/`StrategySpec`/`Summary` gain `borrow_bps` (+ min_variance
  cov fields, borrow_cost_total, dropped_no_cov) and accept `weighting='min_variance'` (requires
  shorts); `OptSolveRequest`/`SolveSpec` gain the L/S fields + method. Router validation covers the
  new combos. `backtest.run`/`optimiser.*` schema unchanged.
- **AC-6 live smoke (sp500, monthly, 2024-07-01…, cost_bps=0, sharpe_tr, 40/40 legs).** PASS:
  L/S `min_variance` ann_vol **8.51%** (run 37, net≈0/gross 1, 29L/29S after alignment,
  dropped_no_cov=968) vs L/S `inverse_vol` **12.98%** (run 36, 40L/40S) — ratio **0.66**, the
  covariance materially lowers book vol — both far below long-only top-Sharpe **17.53%** (run 38). The
  strict 252-day common-date alignment trims the book (honestly counted via `dropped_no_cov`); a
  looser/pairwise covariance is a ledgered follow-on.
- **AC-7 tests + gates.** optimiser 27 (+6 new), backtest 55 (+6 new), signals 17 green; ruff `src`
  clean. `sym validate` not re-run (no schema/identity change).

### File List

- `packages/optimiser/src/optimiser/engine.py` (M) — `_project_capped_simplex` mass param,
  `_project_long_short`, `_pgd` injected-projector, `min_variance_long_short`, `_long_short_solve`,
  `solve` L/S branch + params, `METHODS`.
- `packages/optimiser/src/optimiser/router.py` (M) — L/S request/spec fields + method validation +
  passthrough.
- `packages/optimiser/src/optimiser/gateway.py` (M) — L/S params passthrough.
- `packages/optimiser/db/deploy/optimiser.sql` (M) — signed-weight COMMENT + method comment (no DDL
  change).
- `packages/optimiser/tests/test_optimiser_engine.py` (M) — projection/helper/solve/router tests.
- `packages/backtest/src/backtest/engine.py` (M) — `WEIGHTINGS += min_variance`, cov constants,
  `_aligned_returns_asof`, `_min_variance_weights`, run params, validation, rebalance branch, borrow
  cost, summary/spec fields.
- `packages/backtest/src/backtest/gateway.py` (M) — `borrow_bps` passthrough.
- `packages/backtest/src/backtest/router.py` (M) — `borrow_bps` + `min_variance` enum +
  requires-shorts validation + Summary/Spec fields.
- `packages/backtest/tests/test_engine.py` (M) — min-variance + borrow-cost + as-of + validation tests.
- `packages/backtest/pyproject.toml` (M) — `optimiser` workspace dependency.
- `docs/data-conventions.md` (M) — min_variance + borrow-cost conventions.

### Change Log

- 2026-07-02 — Implemented the optimiser min-variance long/short solve (bmad-dev-story): the convex
  per-side projection + `min_variance_long_short` helper + `min_variance_long_short` optimiser method;
  the backtest `weighting='min_variance'` mode (as-of-bounded covariance, no look-ahead) + short
  `borrow_bps` holding cost. No DB migration (negative weights already allowed). optimiser 27 +
  backtest 55 + signals 17 green; ruff clean. AC-6 smoke: min_variance 8.51% vs inverse_vol 12.98%
  ann vol (ratio 0.66).
