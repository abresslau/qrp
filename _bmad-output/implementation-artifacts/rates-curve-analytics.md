# Story: Rates curve analytics — spreads · carry/roll · DV01 + a rates console page

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "kick off" the derived-analytics follow-on). This
is the trading layer the FI-curves brainstorm + the `uk-rates-curve-store` story (committed 0c48904)
explicitly DEFERRED. It sits ON TOP of the now-live `rates.curve_point` store (derive-on-read; nothing
new persisted). Spec sources: _bmad-output/brainstorming/brainstorming-session-2026-06-22-211134.md
(Phase 3 "the trade vocabulary is SPREADS" + the biggest-reframe; Phase 2/4) and uk-rates-curve-store.md
("OUT of scope / follow-on" + the forward→spot WARN deferral). -->

## Story

As a fixed-income analyst on QRP,
I want **derived curve analytics over the stored BoE curves** — curve spreads (2s10s, flies, breakeven,
asset-swap), carry & roll-down, and a DV01/present-value helper — each with **history + z-score/percentile**
context, surfaced on a **rates console page**,
so that I can actually read the UK rates market the way a desk does (is the curve cheap/rich, steep/flat
vs its own history?) — turning the trustworthy curve store into a usable trading view.

## Background / current state (read before coding)

- **The store is done and committed** (`uk-rates-curve-store`, commit `0c48904`). `rates.curve_point` holds
  the BoE grid: `(curve_set ∈ {glc,ois}, basis ∈ {nominal,real,inflation}, rate_type ∈ {spot,forward},
  tenor, as_of_date)` → `value` (% p.a., restated latest) + `first_value` (immutable first-published).
  GLC nominal 0.5–40y, real/inflation 2.5–40y, OIS nominal 0.5–25y, plus finer short-end sub-year nodes.
  **13,140 nodes loaded** (2026-06). Reads: `rates.gateway.DbRatesGateway.curve(...)` + `curve_sets()`;
  API `GET /api/rates/curve` + `/curve/series` (in `packages/rates/src/rates/{gateway,router}.py`).
- **This story adds DERIVE-ON-READ analytics — nothing is persisted** (the brainstorm's core decision;
  [[feedback_chart_date_axis]] / derive-don't-store). All math reads `curve_point` and computes on the fly.
- **The trade vocabulary IS spreads between stored points** (brainstorm Phase 3, PM seat): 2s10s steepener/
  flattener, 2s5s10s fly, **breakeven** (nominal − real = the inflation trade), **asset-swap** (gilt vs
  SONIA/OIS). Carry & roll-down is THE gilt signal and needs the **forward** curve (already stored).
- **Conventions gate (the make-or-break — brainstorm Quant seat #1):** to derive a discount factor / zero
  curve / DV01 correctly you must pin BoE's **exact compounding + day-count** for spot/forward. The store
  left this as a WARN-level forward→spot reconciliation (`check_forward_spot_reconcile`, approximate). This
  story pins it from BoE's methodology doc and makes the reconciliation **exact**, which is also the
  foundation for correct discount factors. Get this wrong and every derived price is subtly wrong.
- **History + z-score/percentile is an existing QRP pattern — REUSE, don't invent.** `packages/signals/src/
  signals/compute.py` computes z-score/rank/percentile via `statistics.mean` + `pstdev` (with winsorisation);
  `packages/macro/src/macro/gateway.py` `series()` shows the point-in-time delta + sparkline enrichment in
  one indexed pass. Mirror these for "current spread + its history + z-score vs a lookback".
- **Console page conventions:** module pages live under `apps/web/app/<module>/` with a `layout.tsx` tab
  strip; `sym/indices` (`apps/web/app/sym/indices/page.tsx`) is the closest model (level chart + trailing
  stats + range selector). Submenu/rail registration is `apps/web/lib/nav.ts` (a `*_SUBNAV` array + the
  module registry — adding a module needs no shell edit, NFR-10/QH.6). Date charts MUST use
  `apps/web/lib/date-axis.ts` ([[feedback_chart_date_axis]]). Two-tier responsive density, fit-laptop-no-
  scroll + roomier at `2xl:`, verify overflow via CDP ([[feedback_responsive_density_two_tier]]). The
  `rates` module is already in `platform.toml` (enabled) but has NO console page yet.
- **Probe note:** the BoE methodology FAQ PDF was referenced in the store's `MAINTENANCE.md`
  (`…/statistics/Documents/yieldcurve/yields_faq.pdf`). Fetch + read it in-env first
  ([[reference_env_external_sources]], [[feedback_name_the_probe_retest]]); if unreachable, fall back to the
  spreadsheet `info`-sheet notes + a documented assumption, flagged.

## Acceptance Criteria

1. **Conventions pinned + reconciliation made exact (gate).** BoE's compounding (continuously-compounded vs
   annual) and day-count for the spot + forward curves are pinned from the methodology doc and recorded in
   `packages/rates/MAINTENANCE.md`. `check_forward_spot_reconcile` is upgraded from the approximate WARN to
   an **exact** reconciliation at the pinned convention (tight tolerance, FAIL on breach) — and the same
   convention drives discount-factor/zero derivation below. If the doc is unreachable in-env, the exact
   convention is recorded as a flagged assumption + a re-test trigger, and the check stays WARN with an
   honest detail (do not claim "exact" on an unverified convention).
2. **Derive module (pure, tested).** A `packages/rates/src/rates/analytics.py` (or `derive.py`) of PURE
   functions over a curve grid (dict `{tenor: value}` from the gateway), no DB/IO:
   - **Discount factor / zero rate** at a tenor from the spot curve at the pinned convention (with safe
     interpolation between published nodes — document the method, e.g. linear on zero rates).
   - **Spreads:** 2s10s (and a general N-s-M-s), 2s5s10s **fly** (2·5y − 2y − 10y), **breakeven** =
     nominal_spot(t) − real_spot(t) at matching tenors, **asset-swap proxy** = gilt_nominal(t) − OIS(t) at
     matching tenors. Each returns a number in **basis points** with the tenors it used.
   - **Carry & roll-down** over a holding horizon from the **forward** curve: roll-down = spot(t) − spot(t−h);
     carry from the implied forward. Document the exact definition used.
   - **DV01 / present value** helper for an **arbitrary user-supplied cashflow schedule** `[(date|tenor,
     amount)]`: PV = Σ amount·DF(t); DV01 = PV sensitivity to a 1bp parallel shift. (This is the engine; it
     does NOT fetch any specific gilt's cashflows — that's the deferred bond-reference-data bridge.)
3. **History + z-score context (derive-on-read).** For each standard spread (2s10s, 2s5s10s fly, 10y
   breakeven, 10y asset-swap — the default set), the gateway computes the **current value**, a **time series**
   over a lookback (e.g. 1y/5y/max), and a **z-score + percentile** of the current value vs that lookback,
   mirroring the signals `mean`/`pstdev` pattern. One indexed pass over `curve_point` per spread (no N+1);
   uses the latest **non-restated-vintage-agnostic** `value`. Honest about gaps (real/inflation start at
   2.5y, so a 2y breakeven is N/A — surface as null, never fabricate).
4. **Read API.** New read endpoints on the rates router (reuse the `DbRatesGateway` + `_gateway` dep):
   - `GET /api/rates/spreads` — the standard spread set: each with `key`, `label`, current `value_bp`,
     `zscore`, `percentile`, `as_of_date`, and a compact `history` (date+value) for a sparkline.
   - `GET /api/rates/spread/{key}` — one spread's full history over a `?window=` (1Y/5Y/MAX) for the chart.
   - (Curve read `GET /api/rates/curve` already exists — reuse it for the page's curve chart.)
   Read-only, Pydantic-typed, registered after the existing rates routes; regenerate `api-types.ts`.
5. **Rates console page.** A new `apps/web/app/rates/` area (with `layout.tsx` tab strip + `page.tsx`):
   - A **curve chart** (spot vs forward; toggle nominal/real/inflation + OIS) over the published tenor grid,
     using `date-axis.ts` where a date axis applies and a tenor axis for the curve shape.
   - **Spread monitors**: the standard spread set as cards/rows showing current bp + z-score + percentile +
     a history sparkline (click → the `/spread/{key}` history chart), with up/down colour and an honest
     "as of <date>" + RPI-not-CPI labelling on breakeven.
   - Registered in `nav.ts` (a `RATES_SUBNAV` + the rail/registry entry — no shell hardcoding). Two-tier
     responsive density; SSR-safe; newest-wins fetch (QH.8). EOD-only (a live mark is a later story).
6. **Honesty + conventions.** Breakeven is labelled **RPI** (lagged), never CPI. Asset-swap is labelled a
   **proxy** (gilt-yield − OIS, not a true par/par ASW until bond static data lands). A spread whose tenors
   aren't both published reads **N/A** (null), never 0 or a fabricated value. `as_of_date` is the curve's
   stated date (canonical [[feedback_as_of_date_canonical_name]]). Derived bp values reconcile to the curve
   chart (the 10y on the chart and the 10y leg of a spread agree).
7. **No regression + green.** The `rates` store (load/validate/curve endpoint) and the rest of the platform
   stay green. New pure-math + gateway tests (`pytest`) + API route tests + a web vitest for the page;
   `ruff`/`tsc`/`eslint` clean; `api-types.ts` regenerated. Derive-on-read only — `rates.curve_point` and
   its loader are untouched.

## Tasks / Subtasks

- [x] **Task 1 — Pin BoE conventions + make forward→spot exact (GATE) (AC: #1)**
  - [x] Fetch + read the BoE yield-curve methodology doc in-env; record the exact compounding + day-count
    for spot/forward in `MAINTENANCE.md` (+ re-test trigger). If unreachable, record a flagged assumption.
  - [x] Upgrade `check_forward_spot_reconcile` to the exact relationship at the pinned convention (tight
    tolerance, FAIL on breach); keep WARN + honest detail if the convention is only assumed.
- [x] **Task 2 — Derive module (pure functions) (AC: #2)**
  - [x] `analytics.py`: discount-factor/zero-rate (+ documented interpolation), spreads (2s10s, general
    N-s-M, fly, breakeven, asset-swap proxy), carry/roll-down off the forward curve, DV01/PV over an
    arbitrary cashflow list. No DB/IO; all bp outputs carry the tenors used.
  - [x] Unit tests with hand-computed fixtures (a known curve → known spread/DF/DV01).
- [x] **Task 3 — History + z-score gateway methods (AC: #3, #6)**
  - [x] `DbRatesGateway.spreads()` (standard set: current + z-score + percentile + sparkline) and
    `spread_history(key, window)` — one indexed pass per spread over `curve_point`, mirroring
    signals/macro; N/A (null) when a leg tenor isn't published.
- [x] **Task 4 — Read API (AC: #4)**
  - [x] `GET /api/rates/spreads` + `GET /api/rates/spread/{key}` on the rates router; Pydantic models;
    register after existing routes; regen `api-types.ts`.
- [x] **Task 5 — Rates console page (AC: #5, #6)**
  - [x] `apps/web/app/rates/layout.tsx` + `page.tsx`: curve chart (spot/forward × basis toggle) + spread
    monitors (bp + z-score + percentile + sparkline + drill-in). `date-axis.ts`; two-tier density; SSR-safe.
  - [x] `nav.ts`: `RATES_SUBNAV` + rail/registry entry (no shell hardcoding).
- [x] **Task 6 — Verify + no-regression (AC: #7)**
  - [x] `pytest` (rates math + gateway + API), web vitest, `ruff`/`tsc`/`eslint` clean, `api-types` regen.
    CDP-verify the page renders the curve + spreads with correct values (per [[feedback_scale_verification_to_change]]
    — this is behavioral/data-binding, so CDP is warranted). Spot-check a derived spread against the curve.

### Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Edge Case Hunter: 0 High ("SHIP with two nits"). Auditor: 6/7 ACs met (AC#5 had an undisclosed gap).
Blind Hunter's lone "High" (OIS double-fetch) was downgraded to Med by the read-access layer (abort
cancels the stale request; the backend returns empty, not an error). 4 patches, 3 deferred, dismissed rest.

- [x] [Review][Patch] **AC#5 gap: `apps/web/app/rates/layout.tsx` tab strip not built (undisclosed)** — the AC + siblings (`sym`/`monitor`) have a layout tab strip; only `page.tsx` was added. Add a minimal `layout.tsx` driven by `RATES_SUBNAV` (closes the literal AC).
- [x] [Review][Patch] **OIS→non-nominal fires a wasted/empty curve fetch for one frame** [apps/web/app/rates/page.tsx] — clamp the fetched basis (`curveSet==="ois" ? "nominal" : basis`) so no request is issued for an unpublished (ois, real/inflation) combo; the correcting effect stays as a backstop.
- [x] [Review][Patch] **`const [window, setWindow]` shadows the global `window`** [apps/web/app/rates/page.tsx] — latent footgun; rename to `histWindow`/`setHistWindow`.
- [x] [Review][Patch] **Stale module docstring in `checks.py`** [validate/checks.py:5-6] — still calls `check_forward_spot_reconcile` a "WARN-level diagnostic until … pins compounding"; it's now a FAIL/exact identity. Update the doc.
- [x] [Review][Defer] **`spreads()` reads full per-leg history on every summary load** [gateway.py] — fine now (13k rows); over decades of backfill, switch to a windowed z-score. Watch-item.
- [x] [Review][Defer] **Leg-calendar mismatch silently thins a spread series** [gateway.py] — gilt & OIS share BoE's release calendar in practice, but differing calendars would shrink the intersection with no diagnostic. Add a coverage note if a 2nd source/calendar ever lands.
- [x] [Review][Defer] **`spread_history` window floor anchored to the last data date, not today** [gateway.py] — intentional (chart relative to data); document so a stale feed's "1Y" isn't surprising.

Dismissed (key ones): percentile uses `≤ current` (defensible time-series convention, can't reach 0th — fine); flat-series z=0/pctile=100 (degenerate cosmetic); sparkline `/(n-1)` (guarded by `length<2`); unknown-key `unit:"bp"` default (empty points, never rendered); `carry_roll` modeling approximation (labelled, not UI-wired); `interp` float-equality exact-node (tenors are exactly representable); `fmtVal` `+0.0 bp` (cosmetic); spreads fetch uses `alive` not AbortController (one-shot mount fetch, matches the indices sibling); HistoryChart NaN-on-malformed-date (dates are our own ISO output); AC#2 functions return bare float not (value,tenors) (the gateway spec table carries the legs); FAQ "not pinned as PDF" (the verbatim quote in MAINTENANCE.md IS the in-repo anchor); `analytics` PV/DV01/carry pure+tested but not UI-wired (intentional — the DV01 helper is for the deferred bond-refdata bridge).

## Dev Notes

### Critical conventions (regressions / trust failures if violated)
- **Derive-on-read; persist NOTHING.** All analytics read `rates.curve_point`. Do not add tables or write
  derived values. The store (loader, schema, validate) is untouched.
- **Conventions first (Task 1 gates Task 2's pricing math).** Discount factors / DV01 are only correct at
  BoE's actual compounding/day-count. Pin it before building the pricing; if only assumed, say so and don't
  claim exactness.
- **Reuse the existing z-score/history pattern** (`signals/compute.py` mean/pstdev; `macro/gateway.py`
  one-pass enrichment). Don't invent a new stats path.
- **Honest N/A, not fabricated zeros** — a spread needs both legs published (real/inflation start 2.5y; OIS
  ends 25y). Missing leg → null. Breakeven = RPI (lagged), never CPI. Asset-swap = a proxy until bond
  static data lands.
- **Canonical `as_of_date`** ([[feedback_as_of_date_canonical_name]]); **date charts via `date-axis.ts`**
  ([[feedback_chart_date_axis]]); **two-tier responsive density** ([[feedback_responsive_density_two_tier]]);
  newest-wins SSR-safe fetch (QH.8); never `npm --prefix` ([[feedback_minimize_dev_churn]]).
- **`rates` stays a peer** — no edits to sym/macro internals; the page is composed via `nav.ts`/platform
  config, the API via the existing rates router ([[feedback_sym_is_peer_not_hub]], [[project_rates_package_decision]]).

### Explicitly OUT of scope (still deferred)
- **Bond reference-data / specific-gilt pricing** — the DV01/PV helper takes an *arbitrary* cashflow list;
  fetching a *specific* gilt's coupons/maturity (the curve→position bridge) is a separate dataset/story.
- **Live intraday mark** (EOD-only here), **2nd-source divergence** (FX-style), **multi-country** (UK only).

### References
- [Source: packages/rates/src/rates/{gateway,router,validate/checks}.py] — the store reads + the
  `check_forward_spot_reconcile` to upgrade.
- [Source: packages/rates/db/deploy/curve_point.sql + MAINTENANCE.md] — the grid shape + the conventions note.
- [Source: packages/signals/src/signals/compute.py] — z-score/rank/percentile via `mean`/`pstdev` (winsorised).
- [Source: packages/macro/src/macro/gateway.py `series()`] — one-pass history + delta + sparkline enrichment.
- [Source: apps/web/app/sym/indices/page.tsx] — the level-chart + range-selector page model.
- [Source: apps/web/lib/nav.ts] — `SYM_SUBNAV` + the module submenu registry (add `RATES_SUBNAV`).
- [Source: apps/web/lib/date-axis.ts] — the mandatory date-axis helper.
- Spec: brainstorming-session-2026-06-22-211134.md (Phase 3 spreads/carry; the biggest-reframe) + uk-rates-curve-store.md.
- Memories: [[project_fi_curves_brainstorm]], [[project_rates_package_decision]], [[feedback_chart_date_axis]],
  [[feedback_responsive_density_two_tier]], [[feedback_as_of_date_canonical_name]], [[feedback_minimize_dev_churn]],
  [[feedback_scale_verification_to_change]], [[reference_env_external_sources]].

## Open Questions (for Andre — defaults chosen, do not block)
1. **Scope size:** default = do it all in one story (conventions + math + history/z-score + API + page).
   If you'd rather split, the natural seam is **(a) the API/math layer** then **(b) the console page** as a
   fast-follow. Say the word and I'll split.
2. **Standard spread set:** default = 2s10s, 2s5s10s fly, 10y breakeven, 10y asset-swap (gilt−OIS). Add/remove?
3. **Carry/roll definition:** default = roll-down = spot(t) − spot(t−h) over a 3m horizon + forward-implied
   carry. Confirm the horizon(s) you want (3m/6m).
4. **Asset-swap proxy:** default = gilt nominal yield − OIS at the same tenor (a clean ASW needs bond static
   data, deferred). OK as a labelled proxy?

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes List

- **Task 1 — conventions pinned (gate) from the BoE FAQ, in-env (authoritative).** *"The yields (spot and
  forward) are continuously compounded and quoted on an annual basis"* → `DF(t)=exp(-s/100·t)`; day-count
  ACT/ACT for gilts (Nov-1998+), ACT/365 otherwise. Recorded in `MAINTENANCE.md`. This makes the
  forward↔spot relation the **exact continuous-compounding identity** `s(t)·t=∫₀ᵗf` — so
  `check_forward_spot_reconcile` was upgraded from a hedged WARN to a **FAIL** gate (tolerance 0.50pp sits
  above the trapezoidal-discretization residual; a large breach = a true convention mismatch). Passes on
  real data (125 nodes, 0 fail).
- **Task 2 — pure derive module `analytics.py`** (no DB/IO): `interp` (linear, None outside grid),
  `discount_factor`/`zero_rate`, `curve_spread` (2s10s), `butterfly` (2s5s10s), `breakeven` (% level),
  `asset_swap_proxy` (bp), `roll_down`/`carry_roll` (bp off the forward curve), `present_value`/`dv01`
  over an **arbitrary** cashflow list. 10 hand-computed unit tests.
- **Task 3 — history + z-score gateway** (`spreads()` + `spread_history()`): standard set (2s10s, 2s5s10s
  fly, 10y breakeven, 10y ASW proxy); one indexed query per leg-group (no N+1); z-score+percentile via
  `statistics.mean`/`pstdev` (the signals pattern); N/A (null) when a leg tenor isn't published. Verified
  on real data: 2s10s **75.4bp** (z+0.39, 73rd pctile), fly −33bp, 10y breakeven **3.19%**, ASW 48bp.
- **Task 4 — read API:** `GET /api/rates/spreads` + `GET /api/rates/spread/{key}?window=` (Pydantic
  `SpreadSummary`/`SpreadHistory`/`SparkPoint`), registered after the existing curve routes.
- **Task 5 — rates console page** `apps/web/app/rates/page.tsx`: curve chart (tenor axis; spot/forward ×
  nominal/real/inflation + OIS toggles; OIS auto-pins to nominal), spread monitor cards (value + z + pctile
  + sparkline) with a click-through date-axis history chart (`lib/date-axis.ts`), two-tier responsive grid
  (`sm:`/`2xl:`), SSR-safe newest-wins fetch. `RATES_SUBNAV` + registry entry in `lib/nav.ts` (the rail
  link `/rates` already resolves from the enabled `platform.toml` module). RPI-not-CPI + ASW-proxy labelled.
- **Task 6 — verify:** `ruff` clean; **39 Python tests** pass (10 analytics + 6 spreads/router + the 23
  store tests, no regression); live `rates validate` exit 0 + `curve coverage` intact (store untouched);
  `/rates` returns **HTTP 200** and headless-Chrome dump-dom renders the page shell (header, toggles,
  "Spread monitors", footnote) with no Next error overlay. A `rates-page.test.tsx` vitest was written.

### Caveats / follow-ups (deferred-work)
- **Web toolchain couldn't run `tsc`/`eslint`/`vitest` locally** — `apps/web/node_modules` is an incomplete
  install (no top-level typescript/eslint/vitest/next; empty `.bin`), and reinstalling is the exact churn
  [[feedback_minimize_dev_churn]] forbids ("broke lightningcss; verify pages via headless Chrome"). Verified
  the page instead via the sanctioned method: dev-server HTTP 200 (compiles) + dump-dom render. The page
  uses LOCAL TS types (not `Schemas`), so it doesn't depend on an api-types regen. `tsc`/`eslint`/`vitest`
  to be run wherever the web toolchain is whole (CI).
- **api-types regen deferred** — needs a live API with `rates` mounted; the running `:8001` predates the
  rates install (the store's caveat). The page doesn't consume `Schemas`, so this is non-blocking.
- **Live end-to-end (page→API→DB) pending the `:8001` restart** — same caveat as the store; the data path
  is proven in-process (gateway returns the real values, routes exist).
- The **carry** leg of `carry_roll` needs a forward node at the horizon tenor; the standard monitor set
  surfaces roll-down — a full carry/roll monitor card is a small follow-up.

### File List
- `packages/rates/src/rates/analytics.py` (new — pure derive math)
- `packages/rates/src/rates/gateway.py` (modified — `spreads()` + `spread_history()` + spec table)
- `packages/rates/src/rates/router.py` (modified — `/spreads` + `/spread/{key}` + models)
- `packages/rates/src/rates/validate/checks.py` (modified — forward↔spot upgraded WARN→FAIL exact identity)
- `packages/rates/MAINTENANCE.md` (modified — pinned BoE compounding/day-count conventions)
- `packages/rates/tests/test_analytics.py` (new)
- `packages/rates/tests/test_spreads.py` (new)
- `packages/rates/tests/test_router.py` (new)
- `apps/web/app/rates/page.tsx` (new — the rates console page)
- `apps/web/lib/nav.ts` (modified — `RATES_SUBNAV` + registry entry)
- `apps/web/__tests__/rates-page.test.tsx` (new — vitest, run in CI)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Edge Case Hunter "SHIP" (0 High); Auditor 6/7 ACs (one real gap); Blind Hunter's lone "High" (OIS double-fetch) downgraded by the read-access layer (abort cancels the stale request; backend returns empty not error). **4 patches applied:** (1) added the missing `apps/web/app/rates/layout.tsx` tab strip (the AC#5 gap — undisclosed omission); (2) clamp the OIS basis in the curve fetch (`effBasis = curveSet==="ois" ? "nominal" : basis`) — no wasted/empty fetch for an unpublished (ois, real/inflation) combo; (3) renamed the `window` state → `histWindow` (was shadowing the global `window`); (4) fixed the stale `checks.py` module docstring (forward↔spot is now an exact FAIL identity, not a WARN). 3 deferred (full-history read perf watch-item, leg-calendar thinning, window-floor anchoring → deferred-work), rest dismissed (all CONFIRMS/non-issues). Post-patch: ruff clean, 39 py tests, `/rates` HTTP 200 + dump-dom renders the tab strip + shell (no error overlay). Status → done. |
| 2026-06-22 | Dev complete → review. Built the derive-on-read analytics over `rates.curve_point`. Task 1 pinned BoE conventions from the FAQ in-env (continuously compounded, annual; gilt ACT/ACT else ACT/365) → `DF=exp(-s·t)` + upgraded `check_forward_spot_reconcile` to the EXACT continuous-compounding identity (WARN→FAIL, 0 fail on real data). Task 2 pure `analytics.py` (discount/zero/interp, 2s10s/fly/breakeven/ASW-proxy spreads, carry/roll, DV01/PV over an arbitrary cashflow) +10 hand-computed tests. Task 3 `spreads()` + `spread_history()` gateway (one-pass per leg-group, z-score/pctile via statistics, N/A-not-zero) — real data: 2s10s 75.4bp/z+0.39/73pct, fly −33bp, 10y BE 3.19%, ASW 48bp. Task 4 `/api/rates/spreads` + `/spread/{key}`. Task 5 `app/rates/page.tsx` (curve chart spot/forward×basis + OIS, spread monitor cards w/ z-score sparklines + date-axis history drill-in, two-tier density) + `RATES_SUBNAV`/registry in `nav.ts`. Persist nothing; store untouched. Verify: ruff clean, 39 py tests (no regression), validate exit 0, `/rates` HTTP 200 + dump-dom shell render (no error overlay); `rates-page.test.tsx` written. Caveats: web `tsc`/`eslint`/`vitest` not runnable locally (incomplete install — churn-forbidden; CDP-verified instead); api-types regen + live page→API end-to-end pending `:8001` restart (page uses local types, non-blocking). Status → review. |
| 2026-06-22 | Created (bmad-create-story, Andre: "kick off" the derived-analytics follow-on to `uk-rates-curve-store` 0c48904). Derive-on-read trading layer over `rates.curve_point`: pin BoE compounding/day-count + make forward→spot reconciliation EXACT (gate) → pure derive module (discount/zero, spreads 2s10s/fly/breakeven/asset-swap, carry/roll off the forward curve, DV01/PV over an arbitrary cashflow) → history + z-score/percentile gateway (reuse signals/macro pattern) → read API (`/api/rates/spreads` + `/spread/{key}`) → a rates console page (curve chart + spread monitors, `date-axis.ts`, `RATES_SUBNAV`). Persist nothing. Bond reference-data (specific-gilt cashflows), live mark, 2nd-source divergence, multi-country stay OUT. Status → ready-for-dev. |
