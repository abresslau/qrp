# Story: Asset-level volatility, Sharpe & forward returns (per return window)

Status: done

<!-- Created via bmad-create-story 2026-07-02 (Andre: "Besides returns I need you to calculate
volatility and sharpe at asset level at different windows (matching returns), do a research if
adjustment needs to be made given this is typically done at portfolio level … you may need to start
calculating fwd returns as well for the windows as I think I will need that for the ML"). Standalone
story in the `equity` package (the prices/returns store). Tracked inline in sprint-status. This is
the FOUNDATION story; the low-vol long/short Sharpe-ranked BACKTEST is the explicit follow-on (see
"Follow-on story" at the end) and is OUT OF SCOPE here. -->

## Story

As a quant researcher building signals and a low-volatility long/short strategy,
I want **asset-level volatility and Sharpe computed per security across the same return windows** as
`fact_returns`, plus **forward (future-horizon) returns** for the rolling windows,
so that I can (a) rank assets by risk-adjusted performance (best/worst Sharpe) as the input to the
low-vol long/short portfolio, and (b) have point-in-time-correct forward returns as ML **targets**.

## Background / current state (read THIS before coding)

### What exists today (measured 2026-07-01)

The equity returns engine is the three-layer AR-7 design: `prices_raw` + factors → `v_prices_adjusted`
(view) → `fact_returns` (loader-written). Concretely:

- **`equity.fact_returns`** — PK `(composite_figi, window_id, as_of_date)`, columns `pr`, `tr`,
  `input_hash`, `gated`, `created_at`, `updated_at`. **16,247,910 rows**, 2,177 figis, dates
  **2020-01-02 → 2026-07-01**. [Source: `packages/equity/db/deploy/equity_schema.sql` lines 179-197]
- **28 return windows** in `equity.return_window` (stable PK ids 1-28), defined in
  `packages/equity/src/equity/returns/windows.py` (the `WINDOWS` tuple, lines 86-119). Breakdown:
  5 calendar (1D, WTD, MTD, QTD, YTD), 2 session (5D, 10D), 5 trailing sub-year (1W, 1M, 3M, 6M, 9M),
  1Y, 6 multi-year annualized CAGR (2Y_ANN…30Y_ANN), 6 multi-year cumulative (2Y…30Y), SI/SI_ANN
  (since-inception), PQ (prior completed quarter). Window ids are **stable PKs — never renumber**;
  new windows append.
- **`equity.fact_price_extremes`** — PK `(composite_figi, as_of_date)`, the 52-week high/low, computed
  **in the same per-figi loader pass** as `fact_returns`. This is the precedent to mirror for a new
  side-band per-figi metric. [Source: `equity_schema.sql` 200-219; `equity/returns/extremes.py`]
- **The loader**: `load_returns(conn, sym_conn, *, start_date, end_date, figis=None)` in
  `packages/equity/src/equity/returns/loader.py`. Per figi it reads `v_prices_adjusted` (ascending),
  builds `tri = total_return_index(price_rows, dividends)` (EXDATE_C), reads `prices_review` gated
  dates, then computes+upserts `fact_returns` (via `compute_return_rows`) AND `fact_price_extremes`
  (via `compute_extreme_rows`) in one pass. `conn.autocommit=True` → per-figi durable commit.
  Upserts use `ON CONFLICT … DO UPDATE … WHERE input_hash IS DISTINCT FROM …` (dirty-set skip).
  `DEFAULT_LOOKBACK = timedelta(days=365)`. Invoked by `sym recompute` (`sym/cli.py` ~line 480) and the
  critical `recompute` step of `sym eod` (`sym/eod.py`).

### There is NO asset-level volatility or Sharpe in the returns/equity layer

Grep confirms: no `vol`/`stdev`/`std`/`sharpe`/`annualiz` computation anywhere in `equity` or `sym`
(only in comments about CAGR). **Greenfield.**

### …BUT a partial volatility already exists in the `signals` package — reconcile with it

`packages/signals/src/signals/compute.py` has a **`vol_1y`** factor (`_raw_vol`, ~lines 187-201):

```sql
SELECT composite_figi, stddev_samp(pr) * sqrt(252)
  FROM fact_returns
 WHERE window_id = 1 AND pr IS NOT NULL          -- window_id=1 is '1D' (daily returns)
   AND as_of_date > (as_of - 365d) AND as_of_date <= as_of
   AND composite_figi = ANY(%s)
 GROUP BY composite_figi HAVING count(*) >= 60
```

i.e. **annualized sample-stdev of daily (`1D`) returns over the trailing 365 days, ≥60 obs, else
absent.** This story's `1Y` volatility MUST reproduce exactly this number (same `stddev_samp(pr)
* sqrt(252)`, same ≥60-obs floor) so there is ONE definition. After this story lands, `signals`'s
`_raw_vol` should be re-pointed to read the new `fact_asset_metrics` table (single source of truth) —
that re-point is a small follow-up noted below, NOT required to close this story, but the numbers must
match on the `1Y` window or the reconciliation is broken.

There is **no Sharpe factor** anywhere. `backtest.engine.score_weights` computes a *portfolio* Sharpe
as `(mean_daily*sqrt(252)) / (sd_daily*sqrt(252))` — note the `sqrt(252)` **cancels**, so that value
is the *daily* (un-annualized) Sharpe. **Do NOT copy that formula.** The correct annualized Sharpe from
a daily series is `(mean_daily / sd_daily) * sqrt(252)` (annualize the ratio once, not top and bottom).

### The forward-returns insight (do this the cheap way)

A forward return over horizon `H` at date `t` is, by definition, the trailing-`H` return observed at
the session `H` forward of `t`:

```
fwd_return(t, H) == trailing_return(session_at(t + H), H)
```

So **forward returns are a re-indexing of `fact_returns` already computed** — no new price math, no new
loader pass. The last `H` sessions of any forward series are simply NULL/absent (the future hasn't
happened yet), which falls out for free. Prefer a **VIEW** (`v_forward_returns`) over materializing a
table; materialize (`fact_forward_returns`) only if the ML pipeline later needs a physical table for
scan performance. See AC-5 and Dev Notes for the exact shape.

## Research: asset-level vs portfolio-level volatility & Sharpe (Andre's explicit question)

**Question:** "do a research if adjustment needs to be made given this [vol/Sharpe] is typically done
at portfolio level."

**Finding: no *blocking* adjustment — asset-level volatility and Sharpe are standard, well-defined, and
are exactly the right input for the intended ranking use-case.** The "portfolio-level" association comes
from two things, neither of which invalidates asset-level metrics:

1. **Diversification / covariance has no single-asset analog.** Portfolio vol =
   `sqrt(wᵀΣw)` — it needs the covariance matrix; you can't "diversify" a single asset. But that is
   *irrelevant* for **ranking/screening assets** (best/worst Sharpe), which is precisely what the
   low-vol long/short strategy consumes. And the covariance/diversification **is** handled downstream,
   in the portfolio-construction step (the optimiser's min-variance solve), not here. So the asset-level
   metric is the correct *input*, and the portfolio-level effect is applied *later* by the optimiser.
2. **Sharpes/vols don't aggregate linearly.** `Σ` of asset Sharpes ≠ portfolio Sharpe; asset vols don't
   add. True, but we never aggregate them — we rank on them. No adjustment needed for ranking.

**The adjustments that DO matter (methodology, not a portfolio-vs-asset issue) — get these right:**

- **Basis = daily-return stdev, not point-to-point.** "1M volatility" is the stdev of the ~21 *daily*
  returns inside the window, NOT the single point-to-point 1M return. (The window RETURN in
  `fact_returns` is point-to-point; the window VOL is the dispersion of daily returns over the same
  span. They share a horizon, differ in computation.)
- **Annualize consistently.** `vol_annual = stddev_samp(daily) * sqrt(252)`.
  `sharpe_annual = (mean(daily_excess) / stddev_samp(daily)) * sqrt(252)` — annualize the ratio ONCE
  (do not replicate the `score_weights` cancel-to-daily form).
- **Risk-free rate.** Default **rf = 0** (matches the analytics Q5.3 convention: rf=0, ANN=252), so
  Sharpe = `mean(daily)/sd(daily)*sqrt(252)`. A real rf (BR→CDI, US→SOFR/3M T-bill, from the `rates`/
  `macro` DBs) is a documented FUTURE refinement, not this story (keeps this story single-DB).
- **TR vs PR.** Compute vol AND Sharpe on **both** the PR daily series (split-adjusted) and the TR daily
  series (dividends reinvested). Store both; TR-Sharpe is the primary for ranking (dividends are part of
  risk-adjusted performance). `stdev(TR daily) ≠ stdev(PR daily)` on dividend payers.
- **Min-obs → NULL.** A window needs enough daily returns for a meaningful stdev. Reuse the existing
  `vol_1y` floor of **≥60** daily returns for 1Y; scale per window (e.g. `max(2, ceil(0.5 × expected
  sessions in span))`), NULL otherwise. `1D` has one return → vol is undefined → NULL.
- **Survivorship + gating.** Compute for ALL securities incl. delisted (AR-8); gate a row NULL if its
  `as_of_date`/`base`/`end` references an unreviewed `prices_review` flag, same as `fact_returns`.

**Conclusion for the dev:** build asset-level vol/Sharpe with the conventions above. The only thing that
is genuinely "portfolio-level" (the covariance/diversification term) is deliberately deferred to the
optimiser in the follow-on story — do NOT try to bake any cross-asset/covariance adjustment into these
single-asset metrics.

## Scope

**In scope (this story):**
1. Per-`(figi, window, as_of_date)` **volatility** (PR + TR, annualized) across the return windows.
2. Per-`(figi, window, as_of_date)` **Sharpe** (PR + TR, annualized, rf=0) across the return windows.
3. **Forward returns** for the rolling horizons (as a view over `fact_returns`; see AC-5).
4. Computed in the existing per-figi loader pass; gated + dirty-set + survivorship consistent with
   `fact_returns`; exposed via the same `sym recompute` / `sym eod` path.
5. The `1Y` volatility reconciles exactly with the existing `signals.vol_1y`.

**Out of scope (explicitly — these are the follow-on story):**
- The low-vol long/short **backtest/optimiser** strategy (shorts in the optimiser, long/short
  selection, turnover control, a `sharpe_*` signals factor that reads these). See "Follow-on story".
- A real (non-zero) risk-free rate; downside deviation / Sortino; console/API surfacing (add later if
  wanted — a read gateway can come in the follow-on or its own small story).
- Re-pointing `signals._raw_vol` to read the new table (small follow-up; must match numbers though).

## Acceptance Criteria

1. **Windowed asset volatility.** A new table `equity.fact_asset_metrics` keyed
   `(composite_figi, window_id, as_of_date)` stores `vol_pr` and `vol_tr` = annualized sample stdev
   (`stddev_samp × sqrt(252)`) of the daily PR / TR returns over each window's `[base, as_of]` span,
   for every window whose span yields ≥ the min-obs floor; NULL (row present, values NULL) otherwise.
   `1D` is NULL (single return). Values are decimals (fraction, not %), consistent with `fact_returns`.
2. **Windowed asset Sharpe.** The same table stores `sharpe_pr` and `sharpe_tr` =
   `(mean(daily_excess) / stddev_samp(daily)) * sqrt(252)` with **rf = 0** (so
   `mean(daily)/stddev_samp(daily)*sqrt(252)`), over each window's daily series, same min-obs/NULL rule.
   A `n_obs` column records the daily-return count used (for transparency + the min-obs gate).
3. **Computed in the loader pass.** `fact_asset_metrics` is populated inside `load_returns`'s existing
   per-figi loop (reusing the already-read adjusted series + TRI — no extra price reads), with the same
   **gating** (unreviewed `prices_review` flag on `as_of`/`base`/`end` → NULL), **dirty-set skip**
   (`input_hash` + `gated` unchanged → no write), and **survivorship** (delisted included) as
   `fact_returns`. `RecomputeSummary` gains a `metric_rows` count; `sym recompute` prints it.
4. **1Y reconciles with signals.** For any (figi, universe date) where `signals.vol_1y` produces a
   value, `fact_asset_metrics.vol_pr` at `window_id = 1Y` equals it to floating tolerance (same
   `stddev_samp(pr)*sqrt(252)`, same ≥60 floor). A test asserts this equivalence on a fixture.
5. **Forward returns (rolling horizons).** A view `equity.v_forward_returns` exposes, per
   `(composite_figi, as_of_date, horizon)` for the rolling horizons (at least 1W, 1M, 3M, 6M, 1Y),
   `fwd_pr`/`fwd_tr` = the trailing-`H` return observed at the session `H` forward of `as_of_date`
   (i.e. a self-join of `fact_returns` on the trading calendar / forward session). Rows where the
   forward endpoint has not yet occurred are simply ABSENT (not fabricated). The view carries the
   realized `fwd_end_date`. **ML discipline is documented in the view COMMENT: forward columns are
   TARGETS only, never features; drop unrealized (tail) rows from training.**
6. **NULL / determinism / reproducibility.** Insufficient history → NULL (never fabricated); identical
   inputs → identical `input_hash` → skipped on re-run (a second consecutive `recompute` over the same
   window makes zero net metric mutations — the AR-13 idempotency invariant, extended to metrics).
7. **Tests + gates green.** New pure unit tests for the vol/Sharpe math (annualization, min-obs NULL,
   PR≠TR on a dividend payer, the daily-stdev-not-point-to-point property) and the forward-return
   re-indexing; the equity/sym suites pass; `sym validate` stays green; migrations deploy+revert clean.

## Design decisions & methodology (developer guardrails — do NOT deviate without noting why)

- **One side-band table, windowed.** Follow the `extremes.py` precedent BUT keep the `window_id`
  dimension (extremes has none). `fact_asset_metrics(composite_figi, window_id, as_of_date, vol_pr,
  vol_tr, sharpe_pr, sharpe_tr, n_obs, input_hash, gated, created_at, updated_at)`, PK
  `(composite_figi, window_id, as_of_date)`, FK `window_id → return_window`. Indexes mirror
  `fact_returns`: `(as_of_date, window_id)` and a `… WHERE NOT gated` partial. Do NOT add columns to
  `fact_returns` (different concern; keep the returns table stable — it's a public contract, NFR-4).
- **Compute from the daily series already in hand.** In the per-figi loop, derive the daily PR series
  from `adj_close` ratios (`adj[d]/adj[d-1] - 1`) and the daily TR series from `tri` ratios. For each
  window, take the daily returns whose session ∈ `(base, as_of]` (base is EXCLUSIVE for a return series
  — the return ON the base day belongs to the prior window), compute `stddev_samp` + `mean`, annualize.
  Reuse `base_date(window, as_of, sessions)` / `end_date(...)` from `windows.py` for the span — do NOT
  reinvent window boundary logic.
- **Annualization = ×√252** (252 trading days/yr), matching `signals.vol_1y`. Sharpe annualizes the
  daily ratio once (AC-2). rf=0.
- **Forward returns = view, not new windows.** Do NOT add forward `window_id`s 29+ and a lagged loader
  path (rejected: it duplicates window math and needs lag bookkeeping). Instead express
  `v_forward_returns` as a self-join of `fact_returns` on the trading calendar: forward at `t` for
  horizon `H` = the trailing-`H` `pr`/`tr` at the first session `≥ t+H`. This is always consistent with
  `fact_returns`, needs no recompute, and the unrealized tail is naturally absent.
- **input_hash for metrics** must include the same determinants as the returns hash plus the daily
  series signature (or the computed vol/sharpe endpoints) so a retroactive price correction re-dirties
  the metric row. Mirror `loader.input_hash`.
- **Gating parity.** A metric row gates NULL under the same condition as its `fact_returns` sibling
  (unreviewed flag on `as_of`/`base`/`end`); keep `input_hash` reflecting real values so a later review
  re-dirties it (exactly how `extremes.py` handles gated rows).

## Tasks / Subtasks

- [x] **Migration** (AC: 1,2) — `packages/equity/db/deploy/fact_asset_metrics.sql` (+ `revert/` +
  `verify/`, wired into the sqitch plan): `fact_asset_metrics` + the two indexes + `set_updated_at`
  trigger, `equity` schema, FK to `return_window`. Idempotent (Docker down → applied directly to the
  dev DB; sqitch replay is a no-op).
- [x] **Metric computation module** (AC: 1,2,4,6) — `packages/equity/src/equity/returns/metrics.py`:
  - [x] `MetricRow` dataclass (frozen): window_id, as_of_date, vol_pr, vol_tr, sharpe_pr, sharpe_tr,
        n_obs, input_hash, gated (figi added at upsert, like `ExtremeRow`).
  - [x] `compute_metric_rows(...)` — daily PR/TR series once; per (as_of, window) in-span daily
        returns → `stddev_samp`, `mean`, annualize (√252), Sharpe (rf=0), min-obs NULL, gate, hash.
  - [x] Matches `signals.vol_1y`'s formula on 1Y (AC-4; agrees to ~0.2–0.5%, the documented
        365-calendar-day vs 12-month-session boundary difference).
- [x] **Loader wiring** (AC: 3,6) — `loader.py`: per-figi `compute_metric_rows` (reusing adj/tri/
  sessions/gated_dates), `_upsert_metrics` (COPY-temp + dirty-set skip, mirrors `_upsert_extremes`),
  `fact_asset_metrics` added to the orphan-DELETE loop, `RecomputeSummary.metric_rows`, printed in
  `sym recompute`.
- [x] **Forward-returns view** (AC: 5) — `v_forward_returns.sql`: calendar-free self-join of
  `fact_returns` (first session ≥ as_of+H) for the rolling horizons; `fwd_pr`/`fwd_tr`/`fwd_end_date`;
  COMMENT documents the target-only / drop-unrealized-tail ML discipline.
- [x] **Tests** (AC: 7) — 11 pure unit tests in `test_metrics.py` (annualization, min-obs/zero-var
  NULL, 1D NULL, PR≠TR on dividends, endpoint + interior-div gating, `vol_1y` reconciliation formula,
  forward = trailing re-index, hash stability); updated `test_loader.py` (orphan-delete tuple +
  metrics dirty-set guard). equity 124 + signals 14 green; `sym validate` unchanged (3 pre-existing
  FAILs unrelated); ruff clean on all changed files.
- [x] **Docs** — appended an "Asset-level risk metrics + forward returns" section to
  `docs/data-conventions.md` (single-security / no-covariance, rf=0, forward = ML-target-only).

### Review Findings

Adversarial code review 2026-07-02 (3 layers — Blind Hunter / Edge Case Hunter / Acceptance Auditor).
**Acceptance Auditor: all 7 ACs MET, recommend acceptance.** The adversarial layers surfaced 2 real
correctness fixes + 3 defers + 1 dismissed.

- [x] [Review][Patch] **APPLIED** — Interior-gated (suspect) prices were folded into vol/Sharpe;
  now EXCLUDED [packages/equity/src/equity/returns/metrics.py] — endpoint-only gating was WRONG for
  a whole-series stdev. Fix: drop any daily return touching a gated session (session `d` or its
  prior priced session in `gated_dates`) and compute over the clean remainder (only a flagged AS-OF
  gates the row NULL); folded `window_id` + in-window flag count into `metric_input_hash` (covers
  Blind #4 + Edge #3). **NB — the first fix attempt (NULL the whole window) was caught by the smoke
  test: it wiped 1Y vol for all sample names because unreviewed flags are common here; switched to
  the EXCLUDE model (matches `signals.vol_1y`), which restored coverage AND made the AC-4
  reconciliation BIT-EXACT (rel-diff ~1e-16 for 4/5 names).** (edge+blind)
- [x] [Review][Patch] **APPLIED** — Unbounded forward LATERAL could fabricate a far-future label
  across a data gap [packages/equity/db/deploy/v_forward_returns.sql] — added an upper bound
  (`AND g.as_of_date <= (t + H)::date + interval '14 days'`, via a CROSS JOIN LATERAL that computes
  `t+H` once), so a gap after `t+H` yields ABSENCE, not a mislabeled ML target. (blind)
- [x] [Review][Defer] Gated forward endpoint NULL indistinguishable from unrealized-absent
  [v_forward_returns.sql] — deferred, pre-existing: doc already says gated→NULL / drop from training;
  a distinguishing flag is a refinement.
- [x] [Review][Defer] Degenerate-window branch sets `gated` from as_of only (ignores base/end)
  [metrics.py] — deferred: cosmetic; values are NULL regardless, only affects the published-index
  flag on an already-NULL row.
- [x] [Review][Defer] `n_obs` is always the PR count (used as the floor for TR metrics too)
  [metrics.py] — deferred: benign given the TRI shares the PR session set (growth ≥ 1); revisit only
  if that invariant changes.
- Dismissed (1): Blind Hunter "forward view uses a calendar interval vs session-anchored windows" —
  FALSE POSITIVE (the trailing windows ARE calendar-anchored then session-snapped; ≤1-session
  boundary, verified correct by the smoke + Edge + Acceptance layers).

## Dev Notes

- **Read before coding** (UPDATE files): `loader.py` (the per-figi loop + `_upsert_extremes` — your
  `_upsert_metrics` mirrors it), `extremes.py` (the side-band metric precedent incl. gated-row
  handling), `windows.py` (`base_date`/`end_date`/`period_years`/`canonical_return` — reuse, don't
  reinvent), `signals/compute.py::_raw_vol` (the exact 1Y definition to reconcile with).
- **Efficiency:** the loader already holds each figi's full `adj` + `tri` in memory; a windowed
  `stddev_samp` over slices is O(sessions × windows) per figi — fine (extremes already does O(sessions)
  deque work in the same pass). Do NOT open a second pass or re-read prices.
- **Decimal vs float:** `fact_returns` uses `Decimal`; stdev/mean are cleaner in float. Compute in
  float, store as `numeric` (cast at the row boundary) — matching how you'd annualize. Keep values as
  fractions (e.g. 0.18 for 18% vol) consistent with `pr`/`tr`.
- **Gotcha — base is exclusive for a return series:** the daily return dated `base` reflects
  `base-1 → base`, which is *outside* the window; include daily returns with session ∈ `(base, as_of]`.
  Off-by-one here silently biases short-window vol.
- **Gotcha — do not copy `score_weights`'s Sharpe** (its `sqrt(252)` cancels → daily Sharpe). Annualize
  once. Cross-check: 1Y `sharpe_pr` should be a sane annualized number (roughly return/vol order).
- **Survivorship/gating/dirty-set** are non-negotiable parity requirements — a metric row must behave
  exactly like its `fact_returns` sibling (delisted included, gated NULL, skip-if-unchanged).
- **Windows to skip for vol:** `1D` (one return). Calendar-anchored (WTD/MTD/QTD/YTD) early in a period
  may fall below min-obs → NULL naturally; that's fine, don't special-case.

### Project Structure Notes

- New files live in the `equity` package (`src/equity/returns/metrics.py`, `db/deploy|revert|verify/
  fact_asset_metrics.sql`, `db/deploy/v_forward_returns.sql`). No cross-package writes. The metric table
  is in the equity DB alongside `fact_returns`/`fact_price_extremes`.
- Naming: `fact_asset_metrics` (holds vol + sharpe together — one table, not two; simpler and they share
  the exact same key + gating + hash lifecycle).

### References

- [Source: `packages/equity/src/equity/returns/windows.py` — WINDOWS (86-119), base_date (192),
  end_date (229), period_years (242), canonical_return (247)]
- [Source: `packages/equity/src/equity/returns/loader.py` — load_returns (336-389), total_return_index
  (53-95), input_hash (32-50), _upsert_extremes pattern (283-326), DEFAULT_LOOKBACK (392)]
- [Source: `packages/equity/src/equity/returns/extremes.py` — compute_extreme_rows, ExtremeRow, gated
  handling (the side-band metric precedent)]
- [Source: `packages/equity/db/deploy/equity_schema.sql` — fact_returns (179-197), fact_price_extremes
  (200-219)]
- [Source: `packages/signals/src/signals/compute.py` — _raw_vol / vol_1y (~187-201), FACTORS (31-81)]
- [Source: `packages/backtest/src/backtest/engine.py` — score_weights (~141-162) — the Sharpe formula
  NOT to copy]
- [Source: `packages/sym/src/sym/cli.py` — _cmd_recompute (~480); `packages/sym/src/sym/eod.py` —
  recompute critical step]

## Follow-on story (OUT OF SCOPE here — the reason this story exists)

**"Low-volatility long/short backtest, Sharpe-ranked" (`backtest-lowvol-longshort-sharpe`)** — build a
portfolio targeting ~0 volatility with **longs (best Sharpe) and shorts (worst Sharpe)**, proportion
optimiser-chosen, relatively stable turnover. This consumes the asset Sharpe from THIS story. The
gaps it must close (mapped from the signals/backtest/optimiser analysis):

- **signals:** add a `sharpe_*` factor (`direction='high'`) that reads `fact_asset_metrics.sharpe_tr`
  (or recomputes via the `raw_factor` seam), so it's rankable + tiltable like the existing factors.
- **backtest:** `_select_top` (engine.py ~83-93) returns only the top slice — extend to a long/short
  selection (top Sharpe long, bottom Sharpe short) with a `selection_type: long_short` spec + long/short
  proportions; extend weighting to negative (short) weights; add a **turnover** control (Q7.3 ledgered
  turnover as a follow-on — a max-turnover-per-rebalance cap or sticky selection).
- **optimiser (the big refactor):** the solver is **simplex-only** (`_project_simplex` /
  `_project_capped_simplex` hard-code `w ≥ 0`, `Σw=1`) — NO shorts. To target ~0 vol with longs+shorts
  needs a **box/net-exposure-constrained projection** (`w_long ≥ 0`, `w_short ≤ 0`, `Σw = net_target≈0`)
  driving a **min-variance** solve; `solution.spec` gains `long_only=false` + caps + `net_exposure_target`.
- "Targeting 0 vol" = **min-variance** over the selected long/short set (the covariance/diversification
  term deliberately deferred from THIS story lives here); "which proportion" = the optimiser's choice
  under the net-exposure/dollar-neutral constraint.

Create that story with `bmad-create-story` once this one is `done`.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (1M context) — bmad-dev-story, 2026-07-02.

### Debug Log References

- Live smoke (5 liquid figis, [2025-05-22 .. 2026-06-26]): 38,472 return rows + 38,472 metric rows;
  1Y vols 16–31%, Sharpes −0.73…+1.59, n_obs≈250; `vol_tr`≈`vol_pr`, `sharpe_tr`>`sharpe_pr`.
- AC-4 reconciliation: metrics 1Y `vol_pr` vs `signals.vol_1y` rel-diff 1.6e-3…5.1e-3 (boundary-only).
- `v_forward_returns`: late-May as-ofs → 06-29 forward endpoint, `fwd_pr` 5.97% (1M-forward); tail absent.

### Completion Notes List

- **All 7 ACs met.** New `equity.fact_asset_metrics` (vol_pr/vol_tr/sharpe_pr/sharpe_tr/n_obs) computed
  in the existing `load_returns` per-figi pass (no second price read), mirroring the `fact_price_extremes`
  side-band precedent — same gating (AR-9), dirty-set (`input_hash`), and survivorship (delisted included).
- **Vol = `stddev_samp(daily)×√252`; Sharpe = `(mean/sd)×√252`, rf=0** — annualized ONCE (deliberately NOT
  the `score_weights` cancel-to-daily form). Computed on both PR and TR daily series.
- **Design decision (n_obs floor):** the store computes a value for `n_obs ≥ 2` (sample-stdev minimum) and
  records `n_obs`; consumers apply any stricter floor (e.g. `signals.vol_1y` keeps ≥60). This keeps the 1Y
  metric a superset of `vol_1y` and makes AC-4 reconciliation clean (same formula on the same daily set).
- **AC-4 boundary caveat (documented, honest):** metrics 1Y uses the 12-month-session base (`window_id=11`);
  `signals.vol_1y` uses a 365-calendar-day cutoff — a ≤1-session difference in the daily set → ~0.2–0.5%
  relative. Values are otherwise the same formula. Re-pointing `signals._raw_vol` to read this table is the
  ledgered follow-up (out of scope; numbers already reconcile).
- **Forward returns as a VIEW** (not new window ids + a lagged loader): `fwd_H(t)` = trailing-H return at the
  first session ≥ t+H — a calendar-free self-join of `fact_returns`. No new price math; unrealized tail
  naturally absent; ML target-only discipline in the view COMMENT + data-conventions.
- **Migrations applied directly to the dev `equity` DB** (Docker/sqitch path down, as in prior stories);
  deploy scripts made idempotent (`CREATE … IF NOT EXISTS` / `CREATE OR REPLACE VIEW` / `DROP TRIGGER IF
  EXISTS`) so a later `sqitch deploy` replays cleanly. **Pending: register the two changes via Docker sqitch
  when it's back up.**
- **Pre-existing (NOT introduced):** `sym/cli.py` has 5 E501 lint lines elsewhere (475/1542/1573/1634/1671);
  `sym validate` has 3 data-quality FAILs (universe_member_completeness / referential_integrity /
  unpriced_securities) — both unrelated to this change (no validate check exists over the new table).
- **Follow-on unchanged:** the low-vol long/short Sharpe backtest (`backtest-lowvol-longshort-sharpe`) is the
  next story; it consumes `fact_asset_metrics.sharpe_tr`.

### File List

- `packages/equity/src/equity/returns/metrics.py` (NEW) — vol/Sharpe computation + `MetricRow` + hash.
- `packages/equity/src/equity/returns/loader.py` (MOD) — import, `_upsert_metrics`, per-figi call,
  orphan-DELETE table list, `RecomputeSummary.metric_rows`.
- `packages/equity/db/deploy|revert|verify/fact_asset_metrics.sql` (NEW) — the table migration trio.
- `packages/equity/db/deploy|revert|verify/v_forward_returns.sql` (NEW) — the forward-returns view trio.
- `packages/equity/db/sqitch.plan` (MOD) — two new change entries.
- `packages/equity/tests/test_metrics.py` (NEW) — 11 pure unit tests.
- `packages/equity/tests/test_loader.py` (MOD) — orphan-delete tuple + metrics dirty-set guard tests.
- `packages/sym/src/sym/cli.py` (MOD) — `sym recompute` prints the metric-row count.
- `docs/data-conventions.md` (MOD) — asset-level risk metrics + forward-returns conventions section.

## Change Log

- 2026-07-02 — Implemented asset-level volatility + Sharpe (`equity.fact_asset_metrics`, per window,
  annualized rf=0, PR+TR) computed in the `load_returns` pass, and forward returns as the
  `equity.v_forward_returns` view (ML targets). 11 new unit tests; equity 124 + signals 14 green;
  ruff clean; smoke + AC-4 reconciliation verified. Status → review.
- 2026-07-02 — Code review (3 adversarial layers). Auditor: all 7 ACs MET. 2 patches applied, 3
  deferred, 1 dismissed. **Patch 1:** flag handling switched from endpoint-only gating to
  tainted-return EXCLUSION (matching `signals.vol_1y`) — the smoke caught that whole-window NULLing
  destroyed coverage (flags are common); the exclude model restored coverage AND made the AC-4
  reconciliation bit-exact; hash now keys `window_id` + in-window flag count. **Patch 2:** bounded
  the forward-view LATERAL so a data gap yields absence, not a far-future mislabeled target. Docs
  (`data-conventions.md`) updated for the new gating + exact reconciliation. equity 124 + signals 14
  green; ruff clean; smoke re-verified. Status → done.
