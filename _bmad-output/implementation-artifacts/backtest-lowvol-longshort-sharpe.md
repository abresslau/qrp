# Story: Low-volatility long/short backtest, Sharpe-ranked (market-neutral, inverse-vol)

Status: done

<!-- Created via bmad-create-story 2026-07-02. The follow-on to asset-risk-metrics-vol-sharpe-fwd
(Andre: "backtest creating a portfolio with low volatility (targeting 0) with long and shorts, I
don't know which proportion, relative stable turnover, and based on sharpe (best sharp for longs)
and worst sharp for short"). Standalone story spanning the `signals` + `backtest` packages; consumes
equity.fact_asset_metrics (the just-landed per-window vol + Sharpe). The heavier OPTIMISER
min-variance long/short solve is deliberately the NEXT story (see "Follow-on" + Saved Questions). -->

## Story

As a quant researcher,
I want a **long/short backtest that goes long the best-Sharpe names and short the worst-Sharpe names,
held market-neutral and weighted to keep book volatility low, with stable turnover**,
so that I can test a low-volatility, market-neutral strategy driven by the asset-level Sharpe/vol I
just built — without market beta, and without the churn a naive top/bottom screen produces.

## Background / current state (read THIS before coding)

### What this consumes (just landed, on `main`)

`equity.fact_asset_metrics(composite_figi, window_id, as_of_date, vol_pr, vol_tr, sharpe_pr,
sharpe_tr, n_obs, gated)` — per-window annualized volatility + Sharpe (rf=0, ×√252) on the pr and tr
daily series. **`window_id = 11` is the 1Y window.** Flag handling: a row's `gated=true` iff its
as-of snapshot date was under an unreviewed `prices_review` flag (interior flags are excluded from
the sample, not gated); a valid row has `gated=false` and non-NULL values. This story ranks on
`sharpe_tr` and weights on `vol_tr` (both 1Y), reading only `gated=false` rows.

### The three packages + their EXACT current seams

**signals** (`packages/signals/src/signals/compute.py`) — the factor engine:
- `FACTORS` dict (lines 31–81): each entry has `name`/`description`/`direction` (`"high"`|`"low"`)/
  `inputs` (module-qualified refs)/`method`. Existing: `mom_12_1`, `vol_1y`, `size`, `wiki_attention`,
  `fiscal_sens`.
- `raw_factor(factor_key, members, as_of_date, *, sym_conn, eq_conn, alt_conn=None, macro_conn=None)`
  (106–145): the single raw-value dispatch; one branch per factor. `_raw_vol` (187–201) is the
  template — it reads `fact_returns` and returns `dict[figi, float]`.
- `_store` (315–341): winsorize p1/p99 → z-score/rank/pctile by `direction` → `signals.score`. Reused
  unchanged. `required_modules(factor_key)` (84–96) → non-sym/universe modules (empty for a
  fact_asset_metrics reader; equity is always available to the backtest).
- **No signals schema change** — `signals.factor`/`signals.score` already generic.

**backtest** (`packages/backtest/src/backtest/engine.py`) — the walk-forward engine:
- `_select_top(raw, direction, top_pct, top_n)` (83–93): returns the **top slice only** — the
  long-only bottleneck. Needs a long+short variant.
- `_run_backtest(...)` (212–229) + the rebalance loop (287–308): per rebalance → `_members` (PIT
  roster) → `raw_factor` → coverage gate (`< max(20, 0.5·|mem|)` skips) → `_select_top` →
  `_cap_weights` (cap) or equal `1/n` → `weights_at[d]`.
- `_cap_weights(conn, eq_conn, figis, d)` (96–113): mcap weights, positive only.
- `_daily_weighted(conn, weights, lo, hi)` (116–138): daily portfolio return =
  `Σ(wᵢ·prᵢ)/Σwᵢ` over present names. **The `Σwᵢ` (`cw`) normalization + the `if cw > 0` gate
  (line 138) are the NET-ZERO TRAP** — see the critical guardrail below.
- `score_weights(eq_conn, weights, start, end)` (141–162) + `_stats` (165–186): the Sharpe formula
  `(mu/sd)·√252` is CORRECT (annualizes once — NOT the cancel-to-daily bug I worried about). `_stats`
  handles negative daily returns fine.
- Turnover (319–325): `turnover_at[d] = 0.5·Σ|Δw|` — **already correct for signed weights**. Cost
  model (341–347): flat `cost_bps` on one-way turnover; **no short borrow cost** (follow-on).
- `backtest.run`/`backtest.point` schema: **no change** — the strategy `spec` JSONB (Q6.3) carries
  the params. `StrategySpec`/`BacktestRunRequest` (router.py 59–70, 98–111) need the new long/short
  fields.

**optimiser** — NOT touched by this story. The min-variance long/short *weighting* is the follow-on.

### The design (how "targeting 0 vol / don't know the proportion / stable turnover" maps to code)

- **Market-neutral (dollar-neutral) removes the dominant vol source (market beta).** Longs get
  positive weight summing to +0.5, shorts negative weight summing to −0.5 → **net Σw = 0, gross
  Σ|w| = 1**. That is the "targeting 0 [systematic] vol" backbone.
- **"I don't know which proportion" → the weights are DATA-DRIVEN, not guessed:** within each side,
  weight ∝ **inverse volatility** (`1/vol_tr` from `fact_asset_metrics`, 1Y), normalized to the
  side's ±0.5 mass. Inverse-vol down-weights the noisy names → lower book vol. (Plain equal-weight
  per side is the simpler fallback mode.) The 50/50 long/short split is dollar-neutral by
  construction; the *per-name* proportions come from inverse-vol, so nothing is hand-guessed.
- **Sharpe-ranked selection:** longs = top by `sharpe_tr` (`direction='high'`), shorts = bottom by
  `sharpe_tr`. `long_pct`/`long_n` + `short_pct`/`short_n`.
- **Relatively stable turnover → sticky selection (hysteresis):** a name entering the long book needs
  to be in the top `long_pct`, but a *currently-held* long is KEPT while it stays within a wider
  `keep` band (e.g. top `1.5×long_pct`); symmetric for shorts. This damps the name churn a hard
  top/bottom cutoff produces at each rebalance. Turnover is reported (already computed).
- **True min-variance weighting** (which also exploits the covariance/correlations to push book vol
  lower than inverse-vol can) is the **follow-on** (needs the optimiser long/short solve). Inverse-vol
  + dollar-neutral is the tractable low-vol construction that ships here and uses both new metrics.

### CRITICAL guardrail — the net-zero `_daily_weighted` trap (the #1 correctness risk)

`_daily_weighted` today returns `Σ(wᵢ·prᵢ) / Σwᵢ` per day and gates `if cw > 0`. For a **dollar-neutral
book `Σwᵢ = 0`**, `cw = 0` → every day is dropped (empty backtest) AND the normalization is
meaningless. The long/short daily P&L is the **raw inner product `Σ wᵢ·prᵢ`** (weights already scaled
so gross `Σ|wᵢ| = 1`), NOT a `÷Σw` weighted average. For PARTIAL coverage (some name has no price that
day), rescale by the **gross weight present** (`Σ|wᵢ|` over priced names), never the net. So:
`daily_ret[d] = Σ_present(wᵢ·prᵢ) × (1 / Σ_present|wᵢ|)`. For a long-only book (`Σw=1`, all wᵢ≥0)
this reduces to the existing `Σ(w·pr)/Σw`, so keep the long-only path byte-identical and branch the
long/short path. A behavioral test MUST assert a dollar-neutral book produces a non-empty daily series.

## Acceptance Criteria

1. **Sharpe factor.** `signals` gains a `sharpe_tr` factor (`direction='high'`, inputs
   `["equity:fact_asset_metrics:sharpe_tr", "universe:universe_membership"]`, `method` documenting
   1Y/rf=0/gated-false) with a `_raw_sharpe_tr(eq_conn, members, as_of_date)` dispatch that reads
   `equity.fact_asset_metrics` (`window_id=11`, `gated=false`, `sharpe_tr IS NOT NULL`) — absent rows
   are omitted, never imputed. `raw_factor("sharpe_tr", …)` returns `{figi: sharpe}`; `_store` scores
   it (higher = rank 1). `required_modules("sharpe_tr")` is empty.
2. **Long/short selection.** A long/short selection (extending `_select_top` or a new
   `_select_long_short`) returns `(longs, shorts)` = top by `sharpe_tr` / bottom by `sharpe_tr`, sized
   by `long_pct`|`long_n` and `short_pct`|`short_n`. Long-only (no short params) keeps the existing
   behavior byte-identical (regression).
3. **Signed, dollar-neutral, low-vol weighting.** Longs get positive weights summing to +0.5, shorts
   negative summing to −0.5 (net 0, gross 1). `weighting='inverse_vol'` sets per-name weight ∝
   `1/vol_tr` (1Y `fact_asset_metrics`, `gated=false`) within each side; `weighting='equal'` splits
   each side evenly. A name missing a positive `vol_tr` is dropped from that side (counted, never
   zero-weighted). `_daily_weighted`/`score_weights` compute the book P&L as `Σ wᵢ·prᵢ` rescaled by
   gross-present (the net-zero trap fix) — and the long-only path stays byte-identical.
4. **Stable turnover (sticky selection).** A currently-held long is retained while it remains within
   the `keep` band (default top `1.5×` the entry cutoff), and only replaced when it exits; symmetric
   for shorts. A test shows sticky selection yields lower mean per-rebalance turnover than the
   hard-cutoff selection on the same path. Turnover is recorded per rebalance (already computed).
5. **Reproducible spec + API.** `StrategySpec`/`BacktestRunRequest` gain `long_pct`/`long_n`/
   `short_pct`/`short_n`/`weighting='inverse_vol'`/`sticky_keep_mult`; the run's `spec` JSONB persists
   them; the router validates the combos (`long_pct` XOR `long_n`; shorts optional; `weighting ∈
   {equal, cap, inverse_vol}`). `backtest.run`/`point` schema unchanged.
6. **Book diagnostics.** The run summary reports `net_exposure` (~0), `gross_exposure` (~1),
   `n_long`, `n_short`, and annualized book `vol` + `sharpe` (from `_stats`), so "low vol" is
   measurable. A live smoke over sp500 shows a dollar-neutral book whose annualized vol is materially
   below the long-only top-Sharpe book's vol (market-neutrality working).
7. **Tests + gates.** Unit tests: the Sharpe factor read (gated/absent), long/short selection sizing +
   long-only regression, signed inverse-vol weights (net≈0, gross≈1, dropped-no-vol), the **net-zero
   `_daily_weighted` fix** (dollar-neutral book → non-empty daily series; long-only unchanged), sticky
   selection turnover reduction. signals + backtest suites green; ruff clean; `sym validate` unchanged.

## Design decisions & guardrails (do NOT deviate without noting why)

- **Sign is decided by the SELECTION (Sharpe rank), not the weighting.** Longs are pre-signed +,
  shorts −. This keeps weighting convex/trivial here AND is the same property that makes the follow-on
  optimiser solve convex (two capped-simplex projections per side — see Follow-on).
- **Dollar-neutral, gross=1** (net 0, `Σ|w|=1`) is the default book. Do not renormalize by net Σw.
- **Read `fact_asset_metrics` at `window_id=11` (1Y), `gated=false`** for both the Sharpe rank and the
  inverse-vol weight. Reuse the loader's contract; do not recompute vol/Sharpe in the backtest.
- **Keep the long-only path byte-identical** (regression): all new behavior is gated behind the
  presence of short params / `weighting='inverse_vol'`.
- **No optimiser, no borrow-cost, no min-variance in this story** — all three are the follow-on.

## Tasks / Subtasks

- [x] **Sharpe factor** (AC: 1) — `signals/compute.py`: added the `sharpe_tr` `FACTORS` entry +
  `_raw_sharpe_tr` (reads `equity.fact_asset_metrics`, window 11, gated=false, non-NULL) + the
  `raw_factor` dispatch branch + scored it in `_compute_universe`. `required_modules` now also treats
  `equity` as a core (always-open) module so the `equity:` input label keeps it empty. Unit-tested
  the read (gated/absent/rank-by-high, required_modules empty). No signals schema change.
- [x] **Long/short selection** (AC: 2, 4) — `backtest/engine.py`: `_select_long_short(raw, direction,
  long_pct, long_n, short_pct, short_n, held_long, held_short, keep_mult)` → `(longs, shorts)` with
  the sticky-keep band and disjoint legs; `_select_top` (long-only path) untouched/byte-identical.
- [x] **Signed inverse-vol weighting** (AC: 3) — `_neutral_weights(eq_conn, longs, shorts, d,
  weighting, long_mass, short_mass)` producing `{long:+, short:−}` (net 0, gross 1 for L/S) via
  `1/vol_tr` (or equal); drops no-positive-vol names and counts them (`dropped_no_vol`).
- [x] **Net-zero P&L fix** (AC: 3) — `_daily_weighted` now divides by **gross present** (`Σ|w|`)
  instead of net `Σw`, with an `if gross > 0` gate. This is byte-identical for a long-only book
  (`Σ|w|=Σw`) AND fixes the dollar-neutral empty-series bug — subsumes the "branch it" suggestion
  with a strictly-equivalent single path. `score_weights` inherits the fix. Tested explicitly.
- [x] **Rebalance-loop wiring** (AC: 2–4, 6) — threaded selection + weighting through `_run_backtest`;
  carried `held_long`/`held_short` across rebalances for stickiness; skip a rebalance that can't hold
  both legs; added `net_exposure`/`gross_exposure`/`n_long`/`n_short`/`dropped_no_vol` to the summary.
- [x] **Spec + router** (AC: 5) — extended `StrategySpec`/`BacktestRunRequest`/`Summary` + the POST
  validation (long/short XOR, cap-with-shorts reject, weighting enum) + the `spec` JSONB (L/S fields
  added only on L/S runs so long-only specs stay byte-identical); `WEIGHTINGS` gains `inverse_vol`.
- [x] **Tests + docs** (AC: 7) — unit tests above (signals 17, backtest 48) + live sp500 smoke
  (AC-6 vol comparison, see Completion Notes); strategy documented in `docs/data-conventions.md`.

### Review Findings

Code review 2026-07-02 (bmad-code-review, 3 adversarial layers: Blind Hunter / Edge Case Hunter /
Acceptance Auditor). 5 patch, 5 defer, 4 dismissed. Acceptance Auditor: 5/7 ACs MET, 2 PARTIAL
(both minor); the `_daily_weighted` single-gross-path is an accepted, documented deviation.
**All 5 patches APPLIED 2026-07-02** — backtest 49 + signals 17 green, ruff `src` clean, web
typecheck clean. Status -> done. (Fixes were applied to the working tree on main; commit pending.)

- [x] [Review][Patch] inverse-vol read has no min-obs floor — a thin name with a 2-obs `vol_tr` gets an exploding `1/vol_tr` weight and dominates its leg, defeating "low-vol by construction"; add `n_obs >= 60` to match `signals.vol_1y` [packages/backtest/src/backtest/engine.py:_neutral_weights]
- [x] [Review][Patch] L/S selectors silently ignored on misconfiguration — `long_*`/`top_*` without a short selector, or `top_*` with shorts, are dropped with no error (and a bogus non-null pollutes `backtest.run.top_pct`); reject as 422 in router + error in engine [packages/backtest/src/backtest/router.py, engine.py]
- [x] [Review][Patch] L/S strategy unreachable from the sweep/overfitting harness — `_RUN_KWARGS` omits the L/S params, so the flagship market-neutral book can't be Deflated-Sharpe/PBO tested; add the 5 L/S params [packages/backtest/src/backtest/sweep.py:28]
- [x] [Review][Patch] saved dollar-neutral portfolio's `returns()` attribution divides by NET weight (`covered_w`) — the same net-zero trap the engine just fixed, now reachable via `save_portfolio=True`; normalize by gross (`abs`) like the sibling `analytics` path (byte-identical for long-only) [packages/portfolio/src/portfolio/gateway.py:~434,456]
- [x] [Review][Patch] web run-detail renders "top 0%" for an L/S run and ignores the L/S spec fields; show a long/short label when `long_*`/`short_*` present [apps/web/app/backtest/page.tsx:~540]
- [x] [Review][Defer] Book diagnostics (net/gross/n_long/n_short) computed only at the first rebalance — one-day snapshot, documented, could misrepresent later drift [engine.py summary] — deferred, minor reporting
- [x] [Review][Defer] Small-universe leg under-fill: when `long_n + short_n > covered names` the short leg under-fills (lopsided legs) with masses still 0.5/0.5 and no diagnostic [engine.py:_select_long_short] — deferred, low-probability edge (coverage gate ≥20)
- [x] [Review][Defer] Partial-coverage day on a neutral book reports a single-leg (directional) return — same shape as the historical long-only renormalization; neutrality breaks on thin days [engine.py:_daily_weighted] — deferred, pre-existing semantics
- [x] [Review][Defer] `save_portfolio` files every backtest under a synthetic "(backtest)" client [gateway.py:run] — deferred, pre-existing (not introduced here)
- [x] [Review][Defer] AC-4 sticky test asserts name-set churn (a proxy) rather than the engine's reported `turnover_at` through a full run [tests/test_engine.py] — deferred, fair proxy, test-hardening only

Dismissed (4): (1) Blind "sticky over-crowding" — standard buffer/hysteresis, matches docstring,
bounded by `keep_cut`; the retain-held-over-fresh is the intended turnover/signal tradeoff, not a
defect. (2) Blind "overlapping-legs double-map in `_neutral_weights`" — unreachable, legs are
disjoint by construction. (3) Blind "`math` import unverifiable" — false positive, `import math`
is present. (4) Auditor "AC-7 gates unverified" — re-run green here (signals 17 + backtest 48, ruff
`src` clean).

## Dev Notes

- **Read before coding** (UPDATE files): `backtest/engine.py` (`_select_top` 83–93, `_run_backtest`
  212–308, `_cap_weights` 96–113, `_daily_weighted` 116–138 — the trap, `score_weights`/`_stats`
  141–186, turnover 319–347), `signals/compute.py` (`_raw_vol` 187–201 as the template, `raw_factor`
  106–145, `FACTORS` 31–81), `backtest/router.py` (59–70, 98–179).
- **The net-zero trap** (repeat, because it silently produces an empty backtest): `_daily_weighted`'s
  `÷Σw` + `if cw > 0` is only valid for a sum-to-1 long-only book. Branch it.
- **`score_weights` Sharpe is correct** — do NOT "fix" it (it's `(mu/sd)·√252`, annualized once).
- **Turnover formula already handles signed weights** (`0.5·Σ|Δw|`); leave it. Borrow cost = follow-on.
- **Coverage gate** (`< max(20, 0.5·|mem|)`) is on the full roster; keep it. A side that loses all
  names to the no-vol drop should skip the rebalance, not divide by zero.
- **Weight schema:** `backtest` stores curves, not per-name weights, so negative weights need no
  schema change here (unlike the optimiser follow-on).

### References

- [Source: `packages/signals/src/signals/compute.py` — FACTORS 31–81, raw_factor 106–145, _raw_vol
  187–201, _store 315–341, required_modules 84–96]
- [Source: `packages/backtest/src/backtest/engine.py` — _select_top 83–93, _cap_weights 96–113,
  _daily_weighted 116–138 (net-zero trap), score_weights/_stats 141–186, _run_backtest 212–308,
  turnover/cost 319–347, spec 384–394]
- [Source: `packages/backtest/src/backtest/router.py` — StrategySpec 59–70, BacktestRunRequest
  98–111, validation 163–179]
- [Source: `packages/equity/db/deploy/fact_asset_metrics.sql` — window_id=11 (1Y), sharpe_tr/vol_tr,
  gated] · [`docs/data-conventions.md` — the metrics conventions]

## Follow-on story (OUT OF SCOPE here)

**"Optimiser min-variance long/short solve" (`optimiser-longshort-minvariance`)** — replace the
inverse-vol heuristic with a true **min-variance** dollar-neutral book (exploits the covariance, not
just per-name vol → lower book vol, the literal "targeting 0"). The key de-risking insight from this
story's analysis: because the Sharpe selection **pre-signs** each name (long/short), the projection is
**convex** — it decomposes into TWO independent capped-simplex projections (`_project_simplex_mass`,
which already exists): the long side onto mass +0.5, the short-magnitudes onto mass 0.5 (then negate),
each capped. So NO non-convex/NP-hard projection is needed (contrary to a first read). Scope: a
`min_variance_long_short` method in `optimiser.solve` (new per-side projection wrapper + `_pgd` over
the product set), `net_target`/`gross_target`/`cap` in the spec, the `optimiser.weight` sign comment
(the column already allows negatives), and wiring it as a backtest `weighting='min_variance'` mode.
Also ledgered: short **borrow cost** (`borrow_bps`) in the backtest cost model.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Opus 4.8, 1M context) — bmad-dev-story.

### Debug Log References

- ruff/pytest via `uv run --project packages/<pkg> …` (python3 not on PATH). ruff gate = `src` only
  (pre-existing test-file lines already exceed 100; the gate never covered tests).
- Metrics coverage for the AC-6 smoke: `fact_asset_metrics` was populated for only ~302 figis (the
  prior story's smoke sample), so a broad sp500 read fell under the coverage gate. Backfilled sp500
  members over 2024-07-01…2026-07-02 via `load_returns(..., figis=sp500_members)` before the smoke.

### Completion Notes List

- **AC-1 Sharpe factor.** `signals.sharpe_tr` (direction `high`) reads `equity.fact_asset_metrics`
  window 11 (1Y), `gated=false`, non-NULL, exact `as_of_date` — absent rows omitted, never imputed.
  Added to the `raw_factor` dispatch and the `_compute_universe` scoring pass. Key call: extended the
  always-open module set in `required_modules` to include `equity` (it's passed as `eq_conn`
  everywhere), so the `equity:` input label keeps `required_modules("sharpe_tr")` empty and the
  router does NOT try to open a non-existent "equity" module connection.
- **AC-2/4 selection.** `_select_long_short` longs the favourable end / shorts the unfavourable end,
  each sized by `_pct` XOR `_n`, legs disjoint. Sticky hysteresis: a held name within the
  `keep_mult × entry-cut` band is retained (rank order) before fresh entrants fill the rest — damps
  turnover. `_select_top` (long-only) untouched.
- **AC-3 weighting + the net-zero fix.** `_neutral_weights` signs longs `+`, shorts `−`, scales each
  side to its mass (`0.5/0.5` for L/S → net 0, gross 1) by `1/vol_tr` (inverse_vol) or evenly
  (equal); drops+counts no-vol names. `_daily_weighted` now divides by **gross present** (`Σ|w|`),
  not net `Σw` — mathematically byte-identical for a long-only book (all `w≥0`), and the fix that
  keeps a dollar-neutral book from collapsing to an empty series. This subsumes the story's "branch
  the long/short path" note with a single strictly-equivalent path (documented deviation, safer).
- **AC-5 spec/API.** New `long_pct`/`long_n`/`short_pct`/`short_n`/`sticky_keep_mult` on
  `BacktestRunRequest`/`StrategySpec`; `Summary` gains the book diagnostics. Router validates
  long/short XOR, rejects `cap` with shorts, and pins the weighting enum. L/S spec fields are added to
  the persisted `spec` JSONB only on L/S runs, so an existing long-only spec is byte-identical (the
  pre-existing `test_run_persists_the_full_spec_to_sql` still asserts the exact old dict, unchanged).
- **AC-6 diagnostics + live smoke.** `net_exposure`/`gross_exposure`/`n_long`/`n_short` reported. Live
  smoke results recorded below.
- **AC-7 tests.** signals 17 green (3 new), backtest 48 green (9 new incl. the net-zero fix, sticky
  turnover, inverse-vol net-0/gross-1, and a dollar-neutral integration run); ruff `src` clean; no
  regressions; long-only path byte-identical.
- **Migrations:** none — no schema change in either package (reuses the merged `fact_asset_metrics`).

**AC-6 live smoke (sp500, monthly, 2024-07-01…2026-07-02, cost_bps=0, sharpe_tr).** Backfilled
`fact_asset_metrics` for 562 sp500 all-ever members first (7.85M rows). Two runs over the identical
window/roster:
- **Long/short dollar-neutral inverse-vol** (`long_pct=0.2, short_pct=0.2, weighting=inverse_vol`):
  run 34, 501 days / 25 rebalances, **net_exposure ≈ 0** (−2e-17), **gross ≈ 1.0**, n_long=98,
  n_short=98, **ann_vol = 8.67%**, sharpe 0.81.
- **Long-only top-Sharpe equal-weight** (`top_pct=0.2, weighting=equal`): run 35, same window,
  net=1, gross=1, n_long=98, **ann_vol = 17.53%**.
- **Verdict: PASS** — the market-neutral book's vol is **49% of** the long-only book's (materially
  below), and the net-zero `_daily_weighted` fix produced a non-empty 501-day series across 25
  rebalances (the old `÷Σw` gate would have yielded an empty backtest).

### File List

- `packages/signals/src/signals/compute.py` (M) — `sharpe_tr` factor + `_raw_sharpe_tr` + dispatch +
  `required_modules` equity-core + `_compute_universe` scoring.
- `packages/signals/tests/test_compute.py` (M) — 3 Sharpe-factor tests.
- `packages/backtest/src/backtest/engine.py` (M) — `_select_long_short`, `_neutral_weights`, the
  gross-denominator `_daily_weighted` fix, L/S loop wiring, book diagnostics, spec fields,
  `WEIGHTINGS += inverse_vol`.
- `packages/backtest/src/backtest/gateway.py` (M) — pass the L/S params through `run`.
- `packages/backtest/src/backtest/router.py` (M) — request/spec/summary fields + `/run` validation.
- `packages/backtest/tests/test_engine.py` (M) — 9 L/S tests (selection, sticky, weighting, net-zero,
  integration run, validation rejections).
- `docs/data-conventions.md` (M) — long/short backtest conventions section.

### Change Log

- 2026-07-02 — Implemented the low-vol long/short Sharpe-ranked backtest (bmad-dev-story): new
  `signals.sharpe_tr` factor; `backtest` long/short selection (sticky), signed dollar-neutral
  inverse-vol weighting, the net-zero `_daily_weighted` fix, book diagnostics, and spec/router L/S
  params. Long-only path byte-identical. signals 17 + backtest 48 green; ruff clean; docs updated.
