# Story: Enrich the Brazil rates curves (Tesouro Direto — nominal long end + real + breakeven)

Status: done

<!-- Created via bmad-create-story 2026-06-30 (Andre: "my brazilian curves are very limited, you are
not pulling enough data, you need to explore better bcb or tesouro direto"). Standalone story in the
`rates` package (the per-country curve store). Tracked inline in sprint-status. -->

## Story

As a rates analyst looking at Brazil,
I want the BR curve store to carry a **full nominal curve (with a real long end), a real (IPCA) curve,
and breakeven inflation** — not just the handful of short outstanding LTN points,
so that BR has the same nominal / real / breakeven richness as the UK and US curves, out to the long
end (2050+), instead of 5 points capped at ~5.5 years.

## Background / current state (read THIS before coding)

### The symptom (measured 2026-06-30)

BR has exactly **one** curve in `rates.curve_point`: `curve_set='govt', basis='nominal',
rate_type='yield'`. History is deep (2004-12-31 → 2026-06-29, 5,363 dates), but the **latest curve has
only 5 points, tenors 0.51–5.51 years** — no long end, no real curve, no breakeven.

### Why — the source drops almost everything

`packages/rates/src/rates/sources/tesouro.py` streams the Tesouro Transparente "Preço e Taxa dos
Títulos do Tesouro Direto" CSV but keeps **only `Tipo Titulo == "Tesouro Prefixado"`** (the zero-coupon
nominal bullet, LTN) and explicitly drops IPCA+ (real), the coupon bonds, and Selic. Only a few LTN
issues are outstanding at any time → 5 short points. The CSV (probed 2026-06-30, all with 2026 rows)
actually carries:

| `Tipo Titulo` | instrument | curve contribution | today |
|---|---|---|---|
| `Tesouro Prefixado` | LTN (zero nominal) | nominal, short | ✅ used |
| `Tesouro Prefixado com Juros Semestrais` | NTN-F (coupon nominal) | **nominal, long (~10y)** | ❌ dropped |
| `Tesouro IPCA+` | NTN-B Principal (zero real) | **real, mid** | ❌ dropped |
| `Tesouro IPCA+ com Juros Semestrais` | NTN-B (coupon real) | **real, long (→2050+)** | ❌ dropped |
| `Tesouro Educa+` / `Renda+ …` | IPCA-linked, ultra-long | real, very long | ❌ dropped |
| `Tesouro Selic` | LFT (floater) | NOT a yield-curve point | ❌ skip (correct) |
| `Tesouro IGPM+ com Juros Semestrais` | NTN-C (IGP-M, legacy/illiquid) | different inflation index | ❌ skip (out of scope) |

So the entire long end (NTN-F/NTN-B to 2050+), the whole **real** curve, and **breakeven inflation** are
sitting in the **same CSV we already stream** — just filtered out.

### The infra already supports nominal / real / breakeven

`CurvePoint` is `(country, currency, curve_set, basis, rate_type, tenor, as_of_date, value)` — `basis`
is `nominal | real | inflation`, exactly what the Fed GSW (`fed_gsw.py`) and BoE (`boe.py`) sources
already emit. The registry supports multiple sources per country (`US: [UsTreasuryCurveSource(),
FedGswCurveSource()]`). The analytics/gateway already derive **breakeven = nominal − real** for the UK.
So enriching BR is: emit `basis='real'` points from the IPCA+ titles + extend `basis='nominal'` with
NTN-F, and the existing breakeven/real machinery lights up.

### Honesty caveat (must be documented, not hidden)

`Taxa Compra Manha` on a coupon bond (NTN-F/NTN-B) is its **yield-to-maturity**, not a bootstrapped
zero/spot rate; and nominal vs real bonds mature on **different dates** (non-standard per-issue tenors).
So: (a) these stay raw per-issue YTM points (consistent with how the existing prefixado points are
already stored — "kept raw"), labelled `rate_type='yield'`; (b) BR **breakeven is approximate** (nominal
and real points don't share tenors — it needs interpolation, unlike the UK's matched-grid exact check).
The authoritative fitted curves (standard tenors, true zero rates, exact breakeven) are **ANBIMA's ETTJ**
— a documented follow-on (see Open Q / out of scope), not this story.

## Acceptance Criteria

1. **Nominal long end.** The BR nominal curve includes `Tesouro Prefixado com Juros Semestrais` (NTN-F)
   alongside `Tesouro Prefixado` (LTN), so the latest nominal curve extends to ~10y (not ~5.5y).
2. **Real curve.** A new BR `basis='real'` curve is populated from `Tesouro IPCA+` (NTN-B Principal) and
   `Tesouro IPCA+ com Juros Semestrais` (NTN-B), reaching the long end (2045/2050+). Optionally include
   `Educa+`/`Renda+` for the ultra-long real end (flag in code which titles map to real).
3. **Breakeven.** With nominal + real present, the gateway/analytics expose BR breakeven inflation
   (nominal − real) via the SAME path the UK uses — labelled approximate (interpolated across
   non-matching tenors), RPI-vs-IPCA wording correct (BR breakeven is **IPCA**-implied).
4. **Title → basis mapping is explicit + fail-loud.** A small table maps each kept `Tipo Titulo` to its
   `basis` (nominal/real); unknown/new title types are ignored safely (logged), and `Selic`/`IGP-M` are
   deliberately excluded (documented). Layout-drift still raises `CurveLayoutError` (don't mis-map).
5. **Same source, streamed.** Still one streamed pass over the existing Tesouro CSV (10M+ rows) — no
   second network source added in this story; per-issue tenors kept raw (no fabricated standard grid).
6. **Backfill + idempotent.** A reload repopulates BR nominal (extended) + real across history
   (2004→now) via the existing `rates curve load-world --country BR --start_date --end_date`; idempotent
   (equal-value rows skip). The eod `rates` bucket already covers BR — no orchestration change.
7. **Validate.** `rates validate` stays green for BR: plausibility band fits BR real yields (can be
   negative-ish / high vs DM), and the nominal−real breakeven check is WARN-only for BR (approximate,
   non-matched tenors) — do NOT apply the UK's exact-match FAIL to BR.
8. **Honest labelling.** The store/console label these as raw per-issue Tesouro Direto YTMs (not fitted
   zero rates); breakeven labelled IPCA-implied + approximate. No silent "fitted curve" claim.
9. **No regression.** Other countries' sources untouched; `rates` + `rates/validate` tests + ruff green;
   the BR nominal curve's existing consumers (gateway/page/spreads) keep working (now with more points).

## Tasks / Subtasks

- [x] **Task 1 — Title→basis mapping in the Tesouro adapter (AC: #1, #2, #4).** Replaced the
  prefixado-only filter in `parse_rows` with an explicit `TITLE_BASIS` map: `Tesouro Prefixado` +
  `Tesouro Prefixado com Juros Semestrais` → `nominal`; `Tesouro IPCA+` + `Tesouro IPCA+ com Juros
  Semestrais` → `real`. Exact strings verified against a live CSV probe (8 title types). `Selic` +
  `IGP-M` → `EXCLUDED_TITLES` (documented). Emits `CurvePoint("BR","BRL","govt",<basis>,"yield",…)`
  per kept row; unknown title → skip + log-once; `CurveLayoutError` column guard kept. **Decision:**
  `Educa+`/`Renda+` moved to `DEFERRED_TITLES` (NOT loaded) — they're IPCA-linked but retail ANNUITY
  products whose `Data Vencimento` is a final-payment date (not a bullet maturity → not a clean curve
  node), and their implied tenor (~62y) exceeds the store's 60y bound. Documented follow-on.
- [x] **Task 2 — Confirm the real-yield band + validate (AC: #7).** Confirmed the `plausible_band`
  (-5..40) admits BR nominal (~14%) + real (~6-7%) yields — no loosening needed. The exact-match
  breakeven FAIL (`check_inflation_reconcile`) is hard-scoped to GB/glc, so BR is never subject to it
  (no WARN/FAIL). Added a guard test (`test_plausible_band_admits_br_nominal_and_real_yields`).
- [x] **Task 3 — Breakeven surfacing (AC: #3, #8).** The existing path (`_GB_SPREAD_SPECS` be10y +
  exact-tenor leg queries) assumes matched tenors, which BR's per-issue tenors never hit. Added a
  thin **interpolated** variant: `gateway._interp_breakeven_series` interpolates BOTH curves per day
  (`analytics.breakeven`/`interp`) at 10y → nominal−real, dropping dates where 10y isn't bracketed.
  `_spread_specs` adds a generic `be10y` spec ("10y breakeven (IPCA, approx)") for any country with a
  real level curve in the nominal primary's curve_set and no fitted `inflation` curve (US GSW already
  publishes inflation → suppressed). No fake grid. Web page is adaptive → no web change.
- [x] **Task 4 — Backfill + verify (AC: #6, #9).** `rates curve load-world --country BR` (full
  history, archive semantics): 5363 days, inserted=10534 + restated=44502 + skipped=61577, flagged=0.
  Latest BR curve: **nominal 0.51→10.52y** (was ~5.5y; NTN-F long end), **real 0.13→34.15y** (new),
  **be10y breakeven = 6.47%** (IPCA-implied). `rates validate` GREEN for BR (staleness ok,
  plausible_band 19 nodes 0 fail/0 warn). Live API (:8001, restarted) serves nominal+real series +
  breakeven; web proxy (:3000) delivers all three; web typecheck + rates-page vitest green. 75 rates
  tests + ruff green. **Perf fix:** the breakeven detection first used per-basis `max()` probes — an
  absent basis triggered a full backward scan of the as_of_date index (~3s; a latent regression for
  ALL countries lacking real/inflation). Replaced with one bounded latest-day query → `spreads(BR)`
  15s → 0.18s (live API 10s → 0.24s).

### Review Findings (bmad-code-review 2026-06-30 — Blind + Edge + Auditor) — ALL PATCHES APPLIED
- [x] [Review][Patch] **PK collision: same-maturity issues overwrite each other (HIGH)** [packages/rates/src/rates/sources/tesouro.py parse_rows + ingest upsert] — LTN & NTN-F share Jan-1 maturities (2027/2029/2031) and NTN-B Principal & coupon share May/Aug-15; both map to the same `basis` so they collide on the PK `(country,curve_set,basis,rate_type,tenor,as_of_date)`. The ingest `ON CONFLICT DO UPDATE` is last-writer-wins → silent node loss + non-deterministic values (probe: 9 colliding buckets on one day; real-24y 7.27 vs 7.06 = 21bp). Explains the high restated=44502. **FIXED:** `parse_rows` now de-dups per (as_of_date,basis,tenor) via `TITLE_PRIORITY`, keeping the ZERO-COUPON bullet (LTN/NTN-B Principal); coupon issues extend only beyond. BR reloaded. Tests: `test_same_tenor_collision_keeps_zero_coupon_bullet`, `test_coupon_extends_long_end_when_no_bullet_at_that_tenor`.
- [x] [Review][Patch] **Ragged/blank-date row aborts the whole 10M-row stream (MED)** [tesouro.py parse_rows] — `row["Data Base"]`/`row["Data Vencimento"]` direct subscript; a blank/None cell → ValueError/AttributeError killed the entire fetch. **FIXED:** date fields read via `.get().strip()` + `try/except ValueError` → skip the row. Test: `test_malformed_date_row_is_skipped_not_raised`.
- [x] [Review][Patch] **`_pick_real_series` could select a forward-only real curve → meaningless breakeven (LOW)** [gateway.py] — **FIXED:** `forward` real curves excluded from candidates (`rt != "forward"`).
- [x] [Review][Patch] **Stale docstrings claim Educa+/Renda+ loaded as real (LOW)** [tesouro.py TesouroCurveSource + tests/test_tesouro.py module docstrings] — **FIXED:** wording corrected to reflect DEFERRED.
- [x] [Review][Patch] **`analytics.breakeven` docstring was RPI-specific (LOW)** [packages/rates/src/rates/analytics.py] — **FIXED:** now documented index-agnostic (RPI for GB, IPCA + approximate for BR).
- [x] [Review][Defer] **`_full_curve_by_date` unbounded full-history pull (MED, latent)** [gateway.py] — deferred: BR-safe today (index-covered, ~0.15s; be10y only fires for BR). A future high-row-count country with a real curve would materialize entire nominal+real histories per request — add a date window/cap then.
- [x] [Review][Defer] **be10y latest-day inflation gate decoupled from full-history series (LOW)** [gateway.py] — deferred: harmless for BR (never has an inflation series); only matters if a country's inflation series starts/stops mid-history.

## Dev Notes

### Critical conventions (regressions if violated)
- **Same source, one stream.** Keep the single streamed pass over the Tesouro CSV (`_stream_rows`, 10M+
  rows — never load whole). Only the row filter/mapping changes. `parse_rows` stays pure (no network).
- **basis is the existing nominal/real/inflation enum** — emit `real` points (don't invent a new
  curve_set); breakeven is DERIVED (nominal − real), never stored, matching `fed_gsw`/`boe`.
- **Per-issue tenors kept RAW** (no fabricated standard grid) — consistent with today's adapter and the
  store-raw/derive-on-read principle ([[project_fi_curves_brainstorm]], [[project_rates_package_decision]]).
- **Honest labelling** — these are per-issue **YTMs**, not bootstrapped zeros; BR breakeven is
  **IPCA**-implied and **approximate** (non-matched tenors). Never imply a fitted ANBIMA-style curve.
- **`as_of_date` canonical** ([[feedback_as_of_date_canonical_name]]); decimal-comma/latin-1 parsing
  unchanged; `CurveLayoutError` on column drift (fail loud, never mis-map).
- **No orchestration change** — the eod `rates` bucket + `rates curve load-world` already load BR; this
  is a source-content change only.

### Files to touch
- `packages/rates/src/rates/sources/tesouro.py` — the title→basis map + emit nominal/real (the core).
- `packages/rates/src/rates/validate/checks.py` — BR real-yield band + WARN-only breakeven for BR.
- `packages/rates/src/rates/gateway.py` / `analytics.py` — confirm/adapt BR breakeven (interpolated).
- `packages/rates/tests/…` — parse_rows mapping tests (a Prefixado row → nominal; an IPCA+ row → real;
  a Selic/IGP-M row → skipped; a coupon NTN-F → nominal long); band/validate.

### References
- [Source: packages/rates/src/rates/sources/tesouro.py] — the BR adapter (prefixado-only today).
- [Source: packages/rates/src/rates/sources/fed_gsw.py] — the nominal/real/inflation (breakeven) emit
  pattern to mirror (US GSW). [Source: packages/rates/src/rates/sources/boe.py] — UK nominal/real/breakeven.
- [Source: packages/rates/src/rates/sources/registry.py] — BR → [TesouroCurveSource()]; multi-source
  precedent (US). [Source: packages/rates/src/rates/sources/base.py] — CurvePoint shape.
- Tesouro Transparente CKAN CSV (PACKAGE_ID/RESOURCE_ID in tesouro.py); probed 2026-06-30: 8 title types,
  all with 2026 rows (Prefixado/NTN-F nominal; IPCA+/NTN-B real; Selic floater; IGP-M legacy; Educa+/Renda+).
- Sibling stories: `fx-matrix-rates-curves` (the 16-country build), `rates-sources` (US GSW/ECB expansion),
  `rates-curve-analytics` (spreads/breakeven analytics).

## Open Questions (for Andre — defaults chosen, do NOT block)
1. **ANBIMA ETTJ as a 2nd, fitted source (follow-on, OUT of scope here).** The authoritative BR curves
   (fitted nominal/real/breakeven at STANDARD tenors, true zero rates, exact breakeven) are ANBIMA's
   Estrutura a Termo (ETTJ), published daily. Default: this story enriches the existing **Tesouro Direto**
   source (per-issue YTMs — the big, free, already-wired win); ANBIMA (reachability + licence to probe)
   is a separate follow-on for a fitted curve. Say if you want ANBIMA probed/added now.
2. **BCB SGS anchors.** BCB's SGS API (already used by `macro`) carries Selic target + CDI (the overnight
   anchor) but NOT a fitted term structure (that's ANBIMA). Default: leave the short-rate anchor to macro;
   keep rates focused on the Tesouro term structure. Flag if you want the Selic/CDI point on the BR curve.
3. **Educa+/Renda+ (ultra-long IPCA).** Default: include them on the **real** curve for the long end
   (they're IPCA-linked); flag if you'd rather restrict the real curve to NTN-B only.
4. **IGP-M (NTN-C).** Default: excluded (different inflation index, legacy/illiquid). Flag if you want a
   separate IGP-M real curve.

## Dev Agent Record
### Agent Model Used
claude-opus-4-8[1m] (bmad-dev-story)

### Completion Notes
- **Outcome:** BR went from one thin nominal curve (5 points, ≤5.5y) to a full nominal curve to
  ~10.5y (LTN + NTN-F), a real curve to ~34y (NTN-B), and a derived IPCA breakeven (6.47% @10y) —
  all from the SAME streamed Tesouro CSV, no new network source.
- **Honest labelling (AC#8) held:** per-issue YTMs stored raw (`rate_type='yield'`, not fitted
  zeros); breakeven labelled "IPCA, approx" (interpolated across non-matching tenors); ANBIMA ETTJ +
  BCB SGS remain documented follow-ons (Open Q #1/#2 — not done, by design).
- **Open Q #3 resolved (deviation from the create-story default):** Educa+/Renda+ are NOT loaded.
  Rationale surfaced during the backfill — a Renda+ row violated `curve_point_tenor_chk` (tenor
  61.9y > 60y bound). On inspection these are retail accumulation ANNUITIES whose Data Vencimento is
  a final-payment date, not a bullet maturity → not a clean yield-curve node. Held out as
  `DEFERRED_TITLES`; admitting them needs both a tenor-bound widening (60→100y migration — drafted
  then reverted when the shared-schema ALTER was correctly gate-blocked) and an annuity-aware tenor.
  The proper real curve (NTN-B) is fully loaded and reaches 2055/60, satisfying AC#2's core.
- **Perf (not an AC, but a real find):** the first breakeven implementation probed basis presence
  with per-basis `max(as_of_date)` queries; an ABSENT basis made Postgres backward-scan the entire
  as_of_date index (~3s) — a latent regression for every country with no real/inflation curve.
  Replaced with one bounded latest-day series query (`_latest_day_series`): `spreads(BR)` 15s→0.18s.
- **No schema/orchestration change** shipped. No web change (the /rates page is adaptive: basis
  options from `/curve/series`, spreads rendered generically). `validate/checks.py` + `analytics.py`
  unchanged (band already admits BR; breakeven math reused as-is).
- **Verification:** 75 rates pytest + ruff green; web typecheck + rates-page vitest green;
  `rates validate` BR green; live API (:8001) + web proxy (:3000) serve nominal+real+be10y for BR.
  NOT pixel-verified via CDP (zero web code changed; the data surface is the API, which is verified).
- **sqitch note:** no migration was added (the tenor-bound idea was reverted with the Educa+/Renda+
  deferral); the plan is unchanged. Consistent with the standing caveat that prior multi_country was
  applied via psycopg and a full sqitch deploy is pending (Docker down).

### File List
- `packages/rates/src/rates/sources/tesouro.py` — TITLE_BASIS/EXCLUDED_TITLES/DEFERRED_TITLES map;
  parse_rows emits nominal/real per title; log-once on unmapped; docstring rewrite.
- `packages/rates/src/rates/gateway.py` — `_latest_day_series` (bounded basis-presence probe) +
  `_pick_real_series` + interpolated `be10y` spec in `_spread_specs` + `_interp_breakeven_series` +
  `_full_curve_by_date`; `import analytics`.
- `packages/rates/tests/test_tesouro.py` — NEW: title→basis mapping, exclusions, deferrals, parsing,
  layout guard.
- `packages/rates/tests/test_compare.py` — basis-aware fake conn (`_latest_day_series`); interpolated
  breakeven + suppression + cross-curve-set + deferral tests.
- `packages/rates/tests/test_validate.py` — BR nominal+real band guard test.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status tracking.
- (DB: full-history BR backfill into `rates.curve_point` via `rates curve load-world --country BR`.)

## Change Log
| Date | Change |
|---|---|
| 2026-06-30 | Created (bmad-create-story, Andre: "brazilian curves very limited … explore better bcb or tesouro direto"). BR has only the Tesouro Prefixado nominal curve (5 short points latest). Story: enrich from the SAME Tesouro CSV — add NTN-F (nominal long end) + IPCA+/NTN-B (real curve) + derived breakeven, mapped via an explicit title→basis table; per-issue YTMs kept raw + honestly labelled; breakeven IPCA-implied/approximate. ANBIMA ETTJ (fitted) + BCB SGS anchors are documented follow-ons. Status → ready-for-dev. |
| 2026-06-30 | Dev complete (bmad-dev-story). Title→basis map (NTN-F nominal long + NTN-B real); Educa+/Renda+ DEFERRED (annuity products, >60y tenor bound). Interpolated be10y breakeven (6.47%) via a new gateway path; per-basis-max probe replaced with a bounded latest-day query (spreads(BR) 15s→0.18s). Full-history backfill: nominal→10.5y, real→34y, validate green; live API + web proxy + web typecheck/vitest green; 75 rates tests + ruff green. Status → review. |
| 2026-06-30 | Code-reviewed (bmad-code-review, 3 adversarial layers) → done. 5 patches applied, 2 deferred, ~12 dismissed; all 9 ACs MET (auditor). HIGH fix: same-maturity PK collision (LTN/NTN-F + NTN-B Principal/coupon overwriting each other, ~10-20bp errors) → `parse_rows` now de-dups per (as_of_date,basis,tenor) keeping the zero-coupon bullet (TITLE_PRIORITY); BR reloaded (restated=10356 corrupted nodes corrected). MED: ragged-date row no longer aborts the stream. LOW×3: forward-real breakeven guard + 3 docstrings. 78 rates tests + ruff green; BR validate green; be10y stable. Status → done. |
