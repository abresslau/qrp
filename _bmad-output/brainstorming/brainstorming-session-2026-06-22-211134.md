---
stepsCompleted: [1, 2, 3, 4]
session_active: false
workflow_completed: true
inputDocuments: []
session_topic: 'Storing multi-country fixed-income curves from reliable sources to enable FI trading on QRP'
session_goals: 'Diverge widely: which curves/instruments, country coverage, reliable PIT sources, the curve data model (tenors, conventions, as_of/PIT, restatement), ingestion/refresh/validation, derived analytics (bootstrapping, yield↔price, spreads, roll-down/carry), and the FI-trading workflow on top.'
selected_approach: 'ai-recommended'
techniques_used: ['First Principles Thinking', 'Morphological Analysis', 'Role Playing', 'Reverse Brainstorming']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Andre
**Date:** 2026-06-22

## Session Overview

**Topic:** Storing multi-country fixed-income curves from reliable sources, to enable Fixed Income trading on QRP.

**Goals:** Diverge widely before converging — curves/instruments, country coverage, reliable point-in-time sources, the curve data model (tenors, day-count/compounding conventions, as_of/valid_from-to, restatement boundary), ingestion + refresh + validation, derived analytics (bootstrapping, yield↔price, spreads, roll-down/carry), and the trading workflow that sits on top.

### Session Setup

_Fresh session (the six prior sessions are from the 2026-06-08 initial build, unrelated topics). QRP context carried in: sym is a peer warehouse package; canonical `as_of_date` everywhere; PIT/restatement discipline; FX already has a 2-source + divergence pattern (`sym fx`); reliable-source + probe-before-build conventions; index-maintenance-plan discipline. FI is a new asset class for the platform (today: equities + FX + macro)._

## Phase 1 — First Principles Thinking

**Anchoring decision (Andre): store RAW instrument quotes; derive the zero/discount curve on read.** One source of truth, QRP's house bootstrap, full PIT audit — consistent with the FX "store observations, derive crosses" model.

**[Foundations #1] — Curve = O/N → 30y+ continuum, not a few bond points.** The tenor axis runs ~1 day to decades; stored atoms must populate the whole span. "Store the 2/5/10/30 benchmarks" is insufficient by construction (Andre: "if you construct curves they start from day all the way to years").

**[Foundations #2] — Instruments (and conventions) are segment-specific.** Short end: policy/O/N → cash deposits → T-bills → MM futures/FRAs (ACT/360, simple). Belly/long: coupon bonds and/or par swaps (ACT/ACT, semi-annual). So convention lives on the **instrument**, not the curve; the bootstrap stitches heterogeneous segments. Atom = `(instrument, as_of_date, value, day_count, compounding)`.

**[Foundations #3] — The short-end anchor IS the central-bank policy rate → QRP macro already has it.** FI curves extend the macro module rather than starting from zero; the front point and the macro policy-rate series are the same truth.

**[Foundations #4] — "Tradeable" test:** from stored atoms + conventions, can we compute a dirty price + DV01 for an arbitrary cashflow? If not, it's a display curve, not a trading curve.

## Phase 2 — Morphological Analysis

**v1 REFERENCE DECISION (Andre): UK, sourced from the Bank of England published yield-curve dataset.** The BoE Monetary & Financial Conditions Division estimates UK curves daily, in two sets:
- **Gilt-based (government):** nominal, real, and the **implied inflation** term structure (breakeven = nominal − real).
- **Sterling money-market:** **SONIA** overnight + related **OIS** rates.

**[Design #1] — The atom for this source is the BoE's *published fitted curve*, not raw gilt quotes.** Key refinement to Phase 1: the BoE already bootstraps/fits (spline/VRP) and publishes **spot, instantaneous-forward, and par** rates on a tenor grid. So "store raw" here = store the BoE-published curve grid verbatim and treat it as the observation; we DON'T re-bootstrap from individual gilt prices. Derive prices/DV01/spreads on read. (Raw per-ISIN gilt quotes would be a separate, much larger source — out of v1.)
*Atom:* `(curve_set ∈ {gilt, commercial/OIS}, basis ∈ {nominal, real, inflation}, rate_type ∈ {spot, forward, par}, tenor, as_of_date, value)`.

**[Design #2] — Rate-representation choice:** store all three published forms (spot / forward / par) verbatim for audit + convenience, OR canonicalize on **spot** and derive forward/par on read. (BoE publishes all three; spot is the canonical generator.)

**[Design #3] — Restatement is real here:** the BoE *revises historical curves* when it refits → needs `as_of_date` + `valid_from/to` + a restatement boundary (first-published vs latest-estimate), mirroring the FX restatement work.

**[Design #4] — Identity = synthetic curve-point key** (no ISIN at this layer): e.g. `GB.GLC.NOMINAL.SPOT.10Y`, `GB.OIS.SONIA.SPOT.1Y`.

**[Design #5] — Maintenance plan required** (per QRP's index-maintenance discipline): source URL, file format (BoE ships Excel/zip — latest + historical archives), daily cadence, history depth, monitor/gating, PIT boundary — all to be **probed in-env before building** (env-source discipline).

**Phase 2 decisions confirmed (Andre — all three):**
1. **Store all three rate reps** (spot / forward / par) verbatim — and use BoE's published par/forward as a **free validation check** on QRP's derive-on-read math.
2. **Restatement: keep both vintages** (first-published + latest), default to latest (FX `valid_from/to` pattern).
3. **Store the implied-inflation curve as published** (don't recompute nominal − real) — matches source, no drift.

## Phase 3 — Role Playing (pressure-test the UK/BoE design through four seats)

**FI PM / trader seat:**
- **[PM #1] The trade vocabulary is SPREADS between stored points:** 2s10s steepener/flattener, 2s5s10s fly, **breakeven** (nominal − real = the inflation trade), **asset swap** (gilt vs SONIA/OIS). The curve store must make these first-class derived reads, with **history + z-score/percentile** context (QRP already does this for equities/indices).
- **[PM #2] Carry & roll-down is THE gilt signal** → needs the **forward** curve (BoE provides it) + the holding-period roll. Storing forwards isn't optional for a PM.
- **[PM #3] BoE is EOD-only → no live mark.** v1 is EOD (consistent with QRP). A live overlay is a later story (mirrors the WEI/FX/portfolio live work). Flag, don't solve now.

**Quant seat:**
- **[Q #1] Convention exactness or every derived price is wrong:** must pin BoE's compounding/day-count for spot/forward/par EXACTLY (probe their methodology doc) so derive-on-read reconciles to their published par. This is the make-or-break.
- **[Q #2] The "inflation" curve is RPI-based with the indexation lag** (UK linkers are RPI, lagged) — must be labelled RPI breakeven, never mislabelled CPI.
- **[Q #3] Pricing a SPECIFIC gilt ≠ the fitted curve:** to price a real position you need the **instrument's cashflow schedule** (coupon, maturity, day-count) — which the BoE curve does NOT contain. → a **bond reference-data gap** (separate dataset; out of v1, but it's the bridge from "curve" to "position").

**Data-engineer seat:**
- **[DE #1] Ingest = parse BoE Excel/zip** (latest + historical archives), daily, scheduled at London EOD **with explicit timezone** (per the schedule-timezone discipline).
- **[DE #2] Validation checks** (QRP validate layer): no missing tenors; spot within a plausible band; **forward/par reconcile to spot** (the free check); inflation = nominal − real reconciles; stale-curve gating (missed publish / bank holiday → reads stale, never silently carried).
- **[DE #3] Topology decision:** FI is a new asset class — does the curve store live in `sym`, or a new `rates`/`fi` package (per the Postgres-per-package direction)? A genuine architecture choice to make before building.

**Risk / compliance seat:**
- **[R #1] Provenance + vintage on every value:** source = BoE + the file/vintage it came from; restatement keeps first-published so a backtest can ask "what did we know on date D" (AR-9-style PIT honesty).
- **[R #2] Licensing green-light:** BoE yield-curve data is freely usable (Open Government Licence, with attribution) — a compliance *advantage* over a vendor feed (no redistribution restriction). Confirm OGL terms.
- **[R #3] Staleness honesty:** a non-updated curve must surface as stale (freshness-per-market discipline), never imply currency it doesn't have.

## Phase 4 — Reverse-Brainstorm Pre-mortem (failure mode → guardrail)

1. **Silent convention mismatch** (curve looks right, every derived price subtly wrong) → reconcile derive-on-read par/forward vs BoE's *published* par/forward on every load; fail loud beyond tolerance. *(THE highest-value guardrail — it's also the free check from Design #1.)*
2. **Restatement rewrites history** (yesterday's backtest silently changes) → first-published vintage is **immutable**; `valid_from/to`; restatement audit + divergence flag when latest ≠ first beyond a band.
3. **Backtest look-ahead via latest default** → backtests MUST pin to first-published vintage; as-of-vintage is an explicit, loud parameter.
4. **Stale curve served as current** (missed publish / outage) → per-curve freshness vs the expected UK publish calendar; stale reads stale, never carried (use the bank-holiday calendar to tell an expected gap from a real miss).
5. **Excel layout drift** (BoE moves a column/sheet; parser silently mis-maps) → schema-assert the parsed layout (sheets/columns/tenor headers); fail on change; snapshot the raw file for re-parse.
6. **Interpolation hides gaps** → store only published nodes; mark interpolated reads as interpolated; never persist interpolated points as observations.
7. **Partial load desync** (nominal updates, real doesn't) → atomic per-day load across all four bases; reconcile inflation = nominal − real on load; gate the day if incomplete (the partial-EOD-repair lesson).
8. **Unit/scale error** (% vs decimal vs bp → 100× wrong) → canonicalize units at ingest + plausible-band assert per tenor (e.g. UK 10y spot ∈ [−2%, 20%]).
9. **as_of mislabel** (stamped ingest date, not the curve's date; London T+1 lag) → `as_of_date` = the curve's *stated* date from the file, never the ingest date (canonical-as_of_date discipline).
10. **RPI-as-CPI semantic trap** → type/label the basis (RPI, lagged) so it can't be silently consumed as CPI expectations.
11. **Single-source blind spot** → the internal forward/par-vs-spot reconciliation catches internal inconsistency now; a future 2nd UK source (vendor / DMO) enables an FX-style `divergence` cross-check later.
12. **Tenor-grid drift** (BoE adds a tenor; fixed schema drops it) → store tenor as data, not columns; accept new tenors; monitor tenor-set changes.

## Idea Organization and Prioritization

**Thematic Organization** — the ~30 ideas cluster into six themes:

- **A · Data model & atom.** Store-raw-derive-on-read; the atom is BoE's *published fitted curve grid* `(curve_set, basis, rate_type, tenor, as_of_date, value)`, NOT raw gilt quotes; store all 3 rate reps (spot/forward/par) verbatim; store inflation curve as published; synthetic curve-point key (`GB.GLC.NOMINAL.SPOT.10Y`); tenor stored as data, not columns.
- **B · Source & ingestion.** BoE Monetary & Financial Conditions Division daily dataset (gilt nominal/real/inflation + SONIA/OIS); parse Excel/zip (latest + historical archives); daily schedule at London EOD with **explicit timezone**; OGL licensing (free, attribution) — a compliance advantage; **probe the source + methodology doc in-env before building**.
- **C · PIT & restatement integrity.** Two vintages (first-published immutable + latest), default latest; `valid_from/to`; provenance + vintage on every value; `as_of_date` = the curve's stated date, never ingest date; backtests pin to first-published.
- **D · Validation & data-quality guardrails.** The free check (derive-on-read forward/par must reconcile to BoE's *published* forward/par); plausible-band + unit canonicalization; parse-layout schema-assert; atomic per-day load across all four bases; stale-curve gating vs the UK publish calendar; RPI (not CPI) labelling.
- **E · Derived analytics / trading layer.** Spreads as first-class reads (2s10s, flies, breakeven, asset-swap) with history + z-score; carry & roll-down off the forward curve; DV01/dirty-price engine. **Gap:** pricing a *specific* gilt needs bond reference-data (cashflows) — the bridge from curve → position.
- **F · Architecture/topology.** Does the curve store live in `sym` or a new `rates`/`fi` package (per the Postgres-per-package direction)? A real decision to make before building.

**Prioritization Results:**

- **Top-priority (v1 critical path):** [B] probe BoE + pin conventions → [A] curve-grid schema (all 3 reps) → [C] vintage/PIT → [D] the free reconciliation check + stale gating. These four ARE the trustworthy store.
- **Quick win / high value once stored:** [E] spreads + carry/roll as derived reads — large analyst value, no new data, reuses QRP's history+z-score pattern.
- **Breakthrough reframe:** storing the BoE curve gives a *complete rates trading layer* immediately (curve/breakeven/asset-swap/carry) — a real shippable v1, not a half-feature.
- **Explicitly deferred:** bond reference-data / specific-gilt pricing; live intraday mark; a 2nd UK source + divergence check; multi-country expansion (US/DE/etc.).

**Action Planning — recommended v1 ("UK rates curve store"):**

1. **Probe-before-build (do first).** In-env: fetch the BoE yield-curve files, confirm format/sheets/tenor grid + history depth, and read the methodology doc to pin exact compounding/day-count for spot/forward/par. Output: a maintenance-plan note (source URL, format, cadence, history, gating, PIT boundary) per the index-maintenance discipline.
2. **Topology decision.** Choose `sym` vs a new `rates` package before schema — record the rationale (revises nothing already built).
3. **Schema + ingest.** Curve-point table keyed by the synthetic id, all 3 reps, two vintages (`valid_from/to`), `as_of_date` = stated curve date; daily London-EOD scheduled load with explicit timezone; raw-file snapshot for re-parse.
4. **Validate layer.** Forward/par-reconcile-to-spot (the free check), plausible-band + unit asserts, parse-layout assert, atomic 4-basis load, stale-gating vs the UK calendar.
5. **Derived reads (fast-follow story).** Spreads (2s10s/flies/breakeven/asset-swap) + carry/roll with history + z-score; DV01/dirty-price.

**Next action:** `/bmad-create-story` for **v1 = "UK rates curve store"** (steps 1–4), with the derived-analytics layer (step 5) and bond reference-data as explicit follow-on stories.

## Session Summary and Insights

**Key Achievements:**

- Settled the foundational data decision: **store BoE's published fitted curve verbatim, derive on read** — and recognised the atom is the *curve grid*, not raw gilts (a key Phase-1→2 refinement).
- Locked three design decisions (3 rate reps + free validation; two vintages default-latest; inflation stored as published).
- Pressure-tested through four seats and ran a 12-point pre-mortem → a concrete guardrail set, most of which map onto disciplines QRP already runs (freshness, restatement, partial-EOD repair, canonical `as_of_date`, validate layer, divergence).

**Session Reflections:**

- The biggest reframe: **"storing the curve ≠ trading a position."** The BoE curve fully enables a *rates* trading layer (curve/breakeven/asset-swap/carry — all spreads + forwards), but pricing a specific gilt needs a separate bond reference-data set. Naming that boundary kept v1 honest and shippable.
- The single highest-leverage guardrail is the **free reconciliation check** (derive-on-read forward/par vs BoE-published) — it catches the silent convention-mismatch failure that would otherwise corrupt every derived price invisibly.
