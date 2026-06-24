# Next-Level Simulations — backtest & optimiser credibility roadmap

**Status:** research complete; **Tier-1 (3 items) IMPLEMENTED & tested overnight**; Tier-2/3 ready-for-prioritisation.
**Author:** overnight session 2026-06-23 (Andre asleep; directive: "deep research on backtesting, optimisation — start doing simulations soon").
**Inputs:** deep-research workflow `wbg8u51ui` (107 agents, 25 sources, 24/25 claims survived adversarial verification) + current-state code read of `backtest/engine.py`, `optimiser/engine.py`, `signals/compute.py`.

---

## ✅ Shipped tonight (Tier 1 — all tests green, lint clean, no UI breakage)

| # | Upgrade | Where | Tests |
|---|---|---|---|
| 1A | **Transaction costs + turnover + gross/net** | `backtest/engine.py` (`cost_bps` param; one-way turnover ½Σ\|Δw\| per rebalance; net curve+stats; `turnover_ann`/`cost_drag_total`/`strategy_gross` on summary) → gateway → router (`cost_bps` request field, surfaced in `Summary`) | +3 (`test_engine.py`) |
| 1B | **Spread t-stat vs Harvey-Liu-Zhu t>3.0 hurdle** | `backtest/engine.py` (`spread_tstat`/`spread_tstat_hurdle=3.0`/`spread_significant` on summary) → router `Summary` | covered by 1A run tests |
| 1C | **Ledoit-Wolf const-correlation covariance shrinkage** | `optimiser/engine.py` (`_const_corr_shrinkage`; `cov_method="shrinkage"` **new default**, `"sample"` available; `shrink_delta` on summary, `cov_method` on spec) → gateway → router (`cov_method` request field) | +5 (`test_optimiser_engine.py`) |

**Defaults (confirmed by Andre 2026-06-24):**
- **`cost_bps` defaults to 10** (liquid large-cap one-way) → backtests are **NET by default**; `strategy_gross` is reported alongside. Pass `cost_bps=0` for a gross run, or a higher value for a less-liquid book.
- **`cov_method` defaults to `"shrinkage"`** (sample covariance is wrong for MVO). ⚠️ optimiser solutions differ from the pre-1C sample-covariance runs (this is the upgrade). Pass `cov_method="sample"` to reproduce old behaviour.

**Numerical-correctness note (1C):** the optimal-intensity estimators (π, ρ, γ) were derived from first principles for the constant-correlation target (ρ via the ϑ-covariance expansion, holding r̄ fixed — the standard Ledoit-Wolf approximation), not transcribed. Even if δ were imperfect, Σ̂=δF+(1−δ)S is still a valid PD matrix between sample and target — robust by construction. Tests pin the load-bearing invariants: δ∈[0,1], diagonal=sample variance, **PD even when n>t (sample is singular)**, and δ grows as t shrinks. A cross-check against scikit-learn `LedoitWolf` / PyPortfolioOpt on real data is a good daytime confidence step before relying on the exact δ.

> **Remaining Tier-1 (not yet built):** Deflated Sharpe, PBO via CSCV, MinBTL guardrail + the `backtest.sweep` infra they need (1B-steps-2..4). These need a design decision on how to count effective trials N — see open questions.

---

## Thesis

QRP's simulation v1 is architecturally sound — PIT-correct membership (survivorship-safe), no look-ahead (factor recomputed at each rebalance via the signals seam), full reproducible specs persisted, an out-of-sample holdout already wired between optimiser→backtester. What it lacks is the layer that separates **a toy backtest from a result you'd trust**. The research converged unanimously on three credibility levers, in priority order:

1. **Statistical defence against overfitting & multiple testing** — the single highest-leverage upgrade. Right now nothing stops a factor/parameter sweep from surfacing a spurious winner.
2. **Transaction costs + turnover** — every QRP result today is gross/overstated; costs are *strategy-defining*, not a footnote (high-turnover momentum can cost 200–270 bps/yr at scale vs ~2 bps for low-turnover value).
3. **Ledoit-Wolf covariance shrinkage** — the optimiser's plain sample covariance "error-maximises"; this is the highest-ROI optimiser fix and is parameter-free.

Everything else (richer metrics, long-short, multi-factor, HRP/risk-parity/BL/CVaR, resampled frontier) is real value but second-order to these three.

> **Evidence grading.** Tier 1 items below rest on primary peer-reviewed sources with unanimous (3-0) adversarial verification. Tier 2/3 items (metrics, long-short, advanced optimisers, libraries) are **domain-standard but were NOT adversarially verified in this research pass** (the workflow flagged Q3/4/6/7/8/9 as producing no surviving verified claims — a focused second research pass is the right move before building those). Core math is given regardless; treat Tier-2/3 formulas as well-established-but-unverified-here.

---

## TIER 1 — do these first (the credibility floor)

### 1A. Transaction-cost & turnover model in the backtest  ✅ verified
**Why.** Costs are the difference between a paper Sharpe and a real one. Li-Chow-Pickard-Garg (FAJ 2019): at $10B AUM standard momentum ≈ 270 bps/yr, Sharpe-momentum ≈ 200 bps/yr, vs fundamental value ≈ 2 bps; capacity (AUM where cost hits 50 bps/yr) spans **two orders of magnitude** ($1.8B momentum vs $291B value). Crucially, cost is driven by **construction/turnover**, not the raw factor — so turnover accounting + a configurable cost model is the lever, **not** a fixed per-strategy number.

**Where.** `backtest/engine.py` — the holding is already daily-rebalanced-to-target, so turnover is computable at each rebalance from the change in weight vectors `weights_at[d]`.

**What to build.**
- At each rebalance compute one-way turnover `τ = ½ Σ|w_new,i − w_drifted,i|` (compare new target to the pre-rebalance drifted weights, not the prior target).
- Subtract cost from that day's return: `cost = c · τ` where `c` is a configurable round-trip cost in bps. **Default `c = 10 bps` one-way** for liquid large-cap (matches Frazzini-Israel-Moskowitz live-execution evidence of ~10 bps implementation shortfall intra-day; the research surfaced this as a sane modern default). Expose `cost_bps` on the spec.
- Persist annualised turnover and total cost drag on `backtest.run.summary`; report **gross vs net** curves and stats.
- ⚠️ **Do NOT** implement the "30 bps per 10% of ADV" linear-impact rule — that specific heuristic was **refuted 0-3** in verification. Start with a flat per-turnover bps; a turnover×ADV-scaled impact term is a later refinement with a non-linear (≈0.6 power-law, Almgren) functional form, not linear.

**Schema.** add `cost_bps` to spec; `turnover_ann`, `cost_drag`, net stats to `summary` (jsonb — no migration needed).

**Effort:** S–M. Highest credibility-per-line in the whole roadmap.

---

### 1B. Statistical-significance & overfitting guardrails  ✅ verified
**Why.** QRP will sweep factors × quantile cutoffs × rebalance cadences. Bailey-López de Prado: the best-observed Sharpe across N trials rises like √(2 ln N) **under the null of zero skill** — so a sweep *manufactures* a high in-sample Sharpe that means nothing. Harvey-Liu-Zhu (316+ factors data-mined) put the corrected significance hurdle at **t > 3.0, not 2.0** ("the usual 2.0 is a serious mistake").

**Where.** New `backtest/stats.py` (pure-Python; all four are arithmetic over the daily/excess series already in hand). Surface on `run` summary + the `/backtest` page.

**What to build (4 metrics, cheapest→deepest):**

1. **Spread t-stat vs the HLZ hurdle.** For the strategy-minus-baseline daily excess series `e_t`: `t = mean(e)/stdev(e)·√n`. Flag PASS only if `t > 3.0` (display 2.0 as the naive line for contrast). Cheapest; do first.

2. **Deflated Sharpe Ratio (DSR).** `DSR = Φ( (SR − SR₀)·√(n−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²) )` where SR is the (non-annualised) per-period Sharpe, γ₃/γ₄ the skew/kurtosis of returns, and the benchmark
   `SR₀ = σ_SR · [ (1−γ)·Z⁻¹(1 − 1/N) + γ·Z⁻¹(1 − 1/(N·e)) ]`, γ = Euler-Mascheroni ≈ 0.5772, `σ_SR` = stdev of the candidate Sharpes across the N trials, N = number of trials. Report DSR as "prob the strategy's true Sharpe > the best-of-N-luck threshold." **Open input:** how to count effective N when cutoffs/cadences are correlated (see open questions) — start by counting distinct specs in the sweep and label it conservatively.

3. **Probability of Backtest Overfitting (PBO) via CSCV.** Once a sweep produces a T×N P&L matrix: partition rows into S=16 blocks, form all C(16,8)=12,780 train/test splits, take the in-sample-best strategy per split, compute its out-of-sample rank logit, `PBO = fraction landing below the OOS median`. **Reject if PBO > 0.05.** This needs the sweep to be a first-class object (see 1B-infra).

4. **Minimum Backtest Length guardrail.** `MinBTL_years ≈ 2·ln(N) / E[maxSR]²`. Surface as a warning: "you tried N configs over Y years; MinBTL is ~X years — Y<X means a Sharpe of 1 is expected from luck alone." (5yr of data ⇒ ≤~45 independent configs.)

**1B-infra.** DSR/PBO/MinBTL need the platform to *know it ran a sweep*. Add a lightweight `backtest.sweep` concept (a parent id grouping N runs) so N is captured honestly rather than guessed. This is the one schema addition Tier 1 needs.

**Effort:** t-stat + DSR = S. PBO + sweep infra = M.

---

### 1C. Ledoit-Wolf covariance shrinkage in the optimiser  ✅ verified
**Why.** Ledoit-Wolf (verbatim): "nobody should be using the sample covariance matrix for portfolio optimization… the optimizer will latch onto [error] and place its biggest bets on the most extremely unreliable coefficients." Worst exactly when N (names) is large vs T (obs) — QRP's `n=40, lookback=252` is already in the danger zone, and the sample matrix can be singular for larger n.

**Where.** `optimiser/engine.py` `_mean_cov` → add `_shrink_cov`. Drop-in: the projected-gradient solver consumes `cov` unchanged.

**What to build (parameter-free, pure-Python — fits the no-numpy house style).**
- Target F = **constant-correlation**: `f_ii = s_ii`, `f_ij = r̄·√(s_ii·s_jj)`, where `r̄` = mean of all pairwise sample correlations.
- Shrink: `Σ̂ = δ̂·F + (1−δ̂)·S`, `δ̂ = max{0, min{κ̂/T, 1}}`, `κ̂ = (π̂ − ρ̂)/γ̂`, `γ̂ = Σᵢⱼ(f_ij − s_ij)²` (Frobenius distance of target from sample). π̂ = sum of asymptotic variances of sample-cov entries; ρ̂ = sum of asy. covariances between target and sample (full estimators in Ledoit-Wolf "Honey, I Shrunk the Sample Covariance Matrix" Eq. 5 — I have the formulas to implement).
- **Always positive-definite** even when N>T (F is PD, S is PSD, convex combo is PD) → the optimiser always has a well-posed risk model. Persist `δ̂` on `solution.summary` for transparency.

**Bonus.** Shrink the **means** too (or stop optimising on raw means): estimated μ is the noisiest input to `max_sharpe`. Cheapest robust step = a James-Stein / grand-mean shrink of `mean[]`, or default `max_sharpe` to ignore μ beyond the tilt. Flag as a sub-decision.

**Effort:** M (the π̂/ρ̂ estimators are the only fiddly part; ~80 lines pure-Python).

---

## TIER 2 — makes results legible & broadens what you can simulate  ⚠️ domain-standard, not verified this pass

### 2A. Richer metrics + a real benchmark
Add to `_stats`: **Sortino** (downside-deviation denominator, MAR=0), **Calmar** (ann_return / |max_drawdown|), **Information Ratio** (mean excess-vs-benchmark / tracking error), and a **drawdown distribution** (top-5 drawdowns + durations, not just the max). Add a **cap-weight / index benchmark** option alongside the current EW-of-roster so IR is meaningful. All pure arithmetic over series already computed.

### 2B. Long-short / market-neutral construction
Today's engine is long-only top-slice. Add a **top-minus-bottom** mode: long favourable quantile, short unfavourable quantile, dollar-neutral (Σw=0, gross=1 or a `leverage` param). This is how factor premia are actually measured and what the HLZ t-hurdle is designed for. Needs short-side return handling + a borrow-cost knob in the cost model (ties to 1A).

### 2C. Multi-factor combination
`raw_factor` is single-factor. Add a **composite**: z-score each factor (the signals layer already does), combine by equal-weight or specified weights, optionally orthogonalise. Lets QRP test "value+momentum+low-vol" rather than one signal at a time — the realistic case.

---

## TIER 3 — advanced optimisers & robustness  ⚠️ domain-standard, not verified this pass; warrants a focused research pass first

- **Hierarchical Risk Parity (HRP, López de Prado 2016).** Tree-clustering + recursive bisection; no matrix inversion → robust to the ill-conditioning that breaks MVO, and a natural fit for QRP's no-numpy constraint. Strong candidate as a *second optimiser method* next to MVO.
- **Risk parity / equal-risk-contribution.** Allocate so each name contributes equal marginal risk; popular, intuitive, needs only the covariance.
- **Black-Litterman.** Blends a market-equilibrium prior with views — directly consumes QRP's signal tilts as "views" with confidences. The principled upgrade to the current additive tilt.
- **Mean-CVaR / downside optimisation (Rockafellar-Uryasev).** Minimise tail loss instead of variance; convex LP. Better when return distributions are skewed.
- **Resampled efficient frontier (Michaud) / block-bootstrap robustness.** Monte-Carlo resample returns, re-solve, average weights → stabilises allocations against estimation error. Block bootstrap preserves autocorrelation.
- **Turnover-constrained / transaction-cost-aware optimisation.** Add an L1 turnover penalty to the objective so the optimiser trades off expected return vs rebalancing cost.

### The library fork-in-the-road
QRP's optimiser is deliberately pure-Python/no-numpy. Tier-3 convex methods (CVaR LP, turnover-penalised QP, robust opt) are painful without a solver. Decision to make explicitly: **stay pure-Python** (HRP, risk parity, Ledoit-Wolf, resampling all fit) **or adopt `numpy` + `cvxpy`** (unlocks CVaR/robust/turnover-aware cleanly; `PyPortfolioOpt`/`riskfolio-lib` wrap these). Recommendation: do Tier 1 + HRP/risk-parity pure-Python (no new deps), and gate the cvxpy adoption on whether mean-CVaR / turnover-aware optimisation becomes a real need. Don't take the dependency speculatively.

---

## Recommended sequence ("start simulating soon")

1. **1A transaction costs + turnover** (S–M) — instantly makes every existing backtest honest.
2. **1B-step-1 spread t-stat vs t>3.0** (S) — one number that reframes every result.
3. **1C Ledoit-Wolf shrinkage** (M) — fixes the optimiser's core flaw, parameter-free, no new deps.
4. **1B-step-2 Deflated Sharpe + sweep infra + PBO** (M) — the real overfitting defence once sweeps are first-class.
5. **2A richer metrics + benchmark** (S) — legibility.
6. then 2B long-short, 2C multi-factor; **commission a focused research pass** to verify Tier-3 before building it.

## Open questions (carried from the research pass)
- **Effective N for DSR/MinBTL** when quantile/cadence/holding configs are *correlated*, not independent — how to count trials honestly.
- **Cost model functional form** for the impact term beyond flat bps (linear-per-ADV was refuted; Almgren ≈0.6 power-law is the lead) — and separate defaults for daily vs monthly rebalance.
- **Factor-model vs Ledoit-Wolf covariance** — at what N/T does a Barra-style factor covariance beat constant-correlation shrinkage for QRP's universe sizes.
- Tier-2/3 (metrics, long-short, HRP/RP/BL/CVaR, resampling, library landscape) had **no adversarially-verified claims** this pass — run a second deep-research scoped to Q3/4/6/7/8/9 before committing build effort there.

## Primary sources (verified)
- Bailey & López de Prado, *The Deflated Sharpe Ratio*, JPM 2014 — SSRN 2460551.
- Bailey, Borwein, López de Prado & Zhu, *The Probability of Backtest Overfitting* (CSCV) & *Pseudo-Mathematics and Financial Charlatanism* (MinBTL), AMS Notices 2014 — SSRN 2308659.
- Harvey, Liu & Zhu, *…and the Cross-Section of Expected Returns*, RFS 29(1) 2016 — NBER w20592 (t>3.0 hurdle).
- Ledoit & Wolf, *Honey, I Shrunk the Sample Covariance Matrix*, JPM 2004 — SSRN 433840 (shrinkage + constant-correlation target).
- Li, Chow, Pickard & Garg, *Transaction Costs of Factor-Investing Strategies*, FAJ 75(2) 2019 (cost/capacity).
