# Story Q5.2 + Q4.5: Time-weighted returns & PnL over effective-dated weight history

Status: done

## Story

As Andre (the operator),
I want portfolio analytics to honour the full effective-dated weight history (not the latest vector applied retroactively) and to report a true time-weighted Return + a defined PnL per window,
so that FR-14/FR-15 are actually complete and a multi-date portfolio's measured performance reflects what it actually held when.

## Background + scope decision

Two `[PARTIAL]` stories that the record says must land together:

- **Q4.5** (epics-qrp-roadmap.md): *"upload + view multiple `as_of_date` vectors per portfolio; the detail view can pick an as-of; analytics uses the appropriate vector per date."* Storage already supports multi-date (PK includes `as_of_date`; `get` returns `as_of_dates`) — the gaps are the detail as-of picker and analytics' weighting.
- **Q5.2** (FR-15): *"time-weighted Return per Return Window; PnL: either define it as cumulative return (weights-first) or add an optional notional to express absolute PnL — decide + document."*
- **A.1 part 3 (parked):** *"effective-dated weighting stays PARKED with FR-15 — replacing the weighting model without the time-weighted-returns model is churn; they land together."* This story is that landing.
- **Chunk-1 ledger:** *"FR-15: portfolio returns are a latest-weights × latest-returns dot product — not time-weighted, no PnL (money), weights history never consumed time-series-wise [portfolios/gateway.py; analytics/gateway.py applies latest weights retroactively]."* Folded here.

**Current state (read 2026-06-11):** `analytics._portfolio_daily` gets `read_latest_weights` and applies that one vector across ALL history — wrong the moment a portfolio has two vectors. `portfolios.returns` is a snapshot dot-product of latest weights × sym window returns (a valid "current holdings attribution" view, but not FR-15's time-weighted Return, and no PnL).

**Design decisions (made here, documented in code):**
1. **Step-function weighting:** for each trading date `d`, the effective vector is the latest one with `as_of_date <= d`. Dates before the first vector are EXCLUDED (no weights existed — never fabricate backwards). Weights are held constant between rebalance dates (weights-first platform: no drift modelling — documented).
2. **PnL definition:** PnL **is** the cumulative time-weighted return over the window (weights-first); an **optional `notional`** on the portfolio (new nullable column, in `base_currency`) expresses it in money: `pnl = notional × cumulative_return`. No notional → `pnl: null`, return-space only. Never a fabricated notional.
3. **Where it lives:** the daily-series math is analytics' competence — the analytics response gains a `returns` block (cumulative/TWR + PnL). `portfolios.returns` keeps its snapshot semantics with an HONEST docstring + response note pointing to analytics for TWR (no contract break). Weight reads stay behind the owning package's seam (A.1): a new `read_weight_history` joins `read_latest_weights` in `portfolios.gateway`.

**Explicitly OUT of scope:** intra-period weight drift modelling; FX adjustment (existing warning stands); cash flows/external flows (weights-first has none); deleting/editing historical vectors; benchmark-relative PnL.

## Acceptance Criteria

1. **`read_weight_history` seam** in `portfolios.gateway`: full effective-dated history `[(as_of_date, {figi: Decimal}), …]` ascending, ONE statement (no torn vectors), consumed by analytics — zero `portfolio_weight` SQL outside the portfolios package (grep-asserted, the A.1 rule).
2. **Effective-dated analytics series:** `_portfolio_daily` applies the step-function vector per date; dates before the first vector excluded; per-date coverage floor measured against the THEN-effective vector's total weight. A single-vector portfolio's series is numerically unchanged (regression guarantee).
3. **TWR + PnL:** analytics response gains `returns`: `{cumulative_return, n_days, notional, base_currency, pnl}` — cumulative = Π(1+rᵈ)−1 over the window's series days; `pnl = notional × cumulative_return` when notional is set, else null. Computed from the same window-filtered series as the metrics (one series, one truth).
4. **Optional notional:** sqitch change `portfolio_notional` (`portfolios.portfolio.notional NUMERIC NULL CHECK (notional > 0)` — in `base_currency`, COMMENT documents the PnL definition); settable on create + `PATCH /api/portfolios/{pid}`; surfaced in portfolio responses.
5. **Detail as-of picker (Q4.5):** `GET /api/portfolios/{pid}?as_of_date=` returns that vector (422 unknown date); console detail page gets a date picker over `as_of_dates`; analytics panel displays cumulative return + PnL.
6. **Honest snapshot view:** `portfolios.returns` docstring + a `semantics` response field state it's a current-holdings attribution snapshot, not TWR (pointer to analytics).
7. **Tests:** portfolios seam (history shape + SQL ownership); analytics step-weighting (two-vector portfolio: correct vector per date, pre-first-vector dates dropped, single-vector unchanged); TWR compounding; PnL with/without notional; as-of picker; fake conns, house style.
8. **Live verification:** migration deployed (Docker sqitch, portfolios DB); types regenerated against a restarted API; console renders; a real two-vector portfolio (use #3, the backtest-saved one with 12 rebalances if its history is multi-date) shows different metrics than the latest-weights model where they should differ; epic Q4.5/Q5.2 → `[BUILT 2026-06-11]` + FR map; ledger items folded.

## Tasks / Subtasks

- [x] Task 1: `portfolio_notional` migration + `read_weight_history` seam (AC: 1, 4) — deployed via Docker sqitch; pre-existing verify rot fixed en route (the original `portfolios` change's verify referenced the `client` column `client_entity` dropped — the Q8.3 altdata-verify precedent); seam = ONE statement, grouped ascending; `read_portfolio_terms` added for the PnL terms
- [x] Task 2: analytics step-function series + `returns` block (AC: 2, 3) — `bisect_right` over vector dates per return date; pre-first-vector dates excluded (SQL-filtered AND code-guarded); coverage floor against the THEN-effective vector's total; `returns` computed from the same window-filtered `common` series as the metrics, served even below the 20-obs statistics floor (a cumulative return doesn't need 20 obs — stated in comment)
- [x] Task 3: portfolios router/gateway — notional on create + `PATCH /{pid}` (gt=0, allow_inf_nan=False), `?as_of_date=` picker (422 for a date with no vector), `shown_as_of_date`, `semantics: "snapshot_attribution"` + honest docstring on `returns` (AC: 4, 5, 6)
- [x] Task 4: tests (AC: 7) — `services/api/tests/test_twr_weight_history.py`: 9 tests (seam contract one-statement+grouping; step-function A,A,B,B with leak-traps both directions + pre-first-vector exclusion; single-vector regression; coverage floor vs then-effective total; PnL with/without notional; returns below statistics floor; window filter; as-of picker incl. 422). api suite 39/39
- [x] Task 5: types regen (+78 lines, against a freshly restarted API) + console (Holdings table with as-of picker; TWR + PnL metrics in the analytics panel; snapshot box relabelled "Current-holdings snapshot return (attribution)" with pointer) + live verification (AC: 5, 8)
  - [x] Live: portfolio #3 (backtest-saved, 12 vectors 2025-07-01→2026-06-01): series now STARTS at the first vector (2025-07-01, 235 days) instead of covering all history with the latest vector; **TWR +41.8% / Sharpe 2.04 ≈ the backtest engine's own +44.7% / 2.18** (monthly-snapshot gap) — analytics independently reproduces the engine from stored weights, the strongest possible cross-check
  - [x] PATCH notional 1,000,000 → YTD `returns`: cumulative +26.3%, pnl +263,238 USD; as-of probe: unknown date 422, oldest vector served with 100 holdings
  - [x] Console: tsc clean; eslint = exact pre-existing baseline (3 errors, C.1-ledgered, line-shifted); page 200 after restarting the crashed Next dev worker pool (long-session crash, not this change — client-rendered content verified via the API, not SSR grep)
  - [x] Epic: Q4.5 + Q5.2 `[BUILT 2026-06-11]`, FR-14/FR-15 map ✅ complete, v2 closed, Q6.4 refinement retired; ledger: chunk-1 FR-15 item resolved, A.1 part-3 landed

### Review Findings (code review 2026-06-11 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] Rebalance-day look-ahead: `bisect_right` makes a vector effective ON its own `as_of_date`, crediting it with the d−1→d return its PREDECESSOR earned (incl. inception day). Convention fix: a vector dated d is in force at the CLOSE of d — it earns from d+1 (strict `<` selection; SQL `> first_as_of`) [analytics/gateway.py] (HIGH, blind+edge)
- [x] [Review][Patch] TWR/PnL is benchmark-intersected: compounding over `common` makes the portfolio's stated money PnL change with the benchmark picker (dropped days compound as 0%). AC3's "one series, one truth" wording AMENDED by review: the `returns` block compounds the portfolio's OWN window-filtered series (benchmark-independent); the metrics keep the intersection [analytics/gateway.py] (HIGH, blind+edge)
- [x] [Review][Patch] PATCH `{}` silently clears the notional — omitted ≠ explicit null; use `model_fields_set` (merge-patch semantics: omitted = unchanged) [portfolios/router.py] (MED, all three)
- [x] [Review][Patch] Renormalised partial-coverage days are monetised unreported — surface `days_below_full_coverage` + `min_coverage` in the returns block [analytics/gateway.py] (MED, blind)
- [x] [Review][Patch] A non-positive-total vector blacks out its era silently — surface a warning naming the unusable vector date(s) [analytics/gateway.py] (MED, blind+edge)
- [x] [Review][Patch] Coverage floor breaks for short weights (covered/total on signed sums) — measure coverage on ABSOLUTE weights; return normalisation stays signed [analytics/gateway.py] (MED, edge)
- [x] [Review][Patch] Partial re-upload to an existing date MERGES with stale rows (ghost holdings) — now load-bearing for TWR. Replace-vector semantics: transactional DELETE-then-INSERT per upload [portfolios/gateway.py upload_weights] (MED, edge)
- [x] [Review][Patch] Console: as-of fetch error blanks the whole page (`setP(null)`); header shows shown-vector holdings count against the LATEST date; upload snaps the picker back to latest — keep state on picker errors, label with `shown_as_of_date`, preserve the picked date across uploads [apps/web/app/portfolios/[id]/page.tsx] (MED, blind+edge)
- [x] [Review][Patch] `except ValueError` on the get route catches more than the bad-date case — scope it to requests that passed `as_of_date`; analytics `as_of_date` field semantics shifted (now "latest vector date") — document in the model [routers] (LOW, blind)
- [x] [Review][Patch] Float-smuggled vector index in the agg accumulator — separate `idx_by_date` dict [analytics/gateway.py] (LOW, blind)
- [x] [Review][Patch] Weak tests: coverage-floor test never exercises per-era totals; single-vector regression is one trivial day; window-filter test can't fail; no PATCH-omission or replace-upload tests — strengthen all + update step-function expectations to the closing convention [tests] (MED, blind+auditor)
- [x] [Review][Patch] Story File List empty; console "set a notional" hint names an action the UI can't perform — fill the record; honest hint text; ledger the missing console notional affordance [story, console] (LOW, auditor)

Dismissed as noise (1): "TWR benchmark-intersected is AC3-by-design" (auditor note F6) — superseded: the patch amends AC3 because review showed the design was wrong for an absolute money figure.

## Dev Notes

### Existing code map (READ before writing)

- `packages/portfolios/src/portfolios/gateway.py` — `read_latest_weights` (the seam pattern to mirror), `get` (as_of_dates already listed; latest-only weights), `upload_weights` (multi-date already works), `returns` (snapshot view to keep + document).
- `packages/analytics/src/analytics/gateway.py` — `_portfolio_daily` (the rewrite target; keep COVERAGE_FLOOR/ANN), `analytics()` (window filtering happens AFTER the series build — the `returns` block must use the post-filter `common` dates), `VALID_WINDOWS`.
- `packages/analytics/src/analytics/router.py` + `packages/portfolios/src/portfolios/router.py` — response models to extend (types regen MANDATORY).
- `packages/portfolios/db/` — sqitch (existing `client_entity [portfolios]` follow-up pattern).
- `apps/web/app/portfolios/[id]/page.tsx` + `apps/web/components/analytics-panel.tsx` — console surfaces.
- `services/api/tests/test_analytics_boundaries.py` — house API-test style + the A.1 grep assertion to extend.

### Constraints

1. AR-R2: weight×return stays assembled in-app; weights ONLY via the portfolios seam (A.1).
2. Decimals from the DB; floats at the math boundary (existing pattern).
3. Sqitch via Docker (`MSYS_NO_PATHCONV=1`, portfolios DB); types regen against a FRESHLY RESTARTED API (ports: API 8001, console 3001).
4. Never fabricate: no backfilled weights, no fake notional, coverage gaps reported.
5. `as_of_date` canonical naming everywhere.
6. Ruff 100; house fake-conn tests; suites must stay green (api 30, sym 590+1 ledgered, etc.).
7. Q8.3 review lesson: console fetches don't check `r.ok` (pre-existing pattern — do NOT fix globally here; new fetches may check it).

### Previous story intelligence

- Honest counters/labels (every review); typed signatures; docstrings state partial capabilities.
- A.1 near-miss: stale running API bakes old types — restart before `gen:types`.
- Q6.4 refinement note says analytics used "latest weight vector held constant" — this story retires that caveat; update the epic text.

### References

- [Source: epics-qrp-roadmap.md — Q4.5, Q5.2, build-status "remaining v2 polish"]
- [Source: deferred-work.md — chunk-1 FR-15 item; A-1 part-3 parked note]
- [Source: packages/{portfolios,analytics}/src; services/api/tests/test_analytics_boundaries.py]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- Pre-existing sqitch verify rot in portfolios (original change's verify referenced the dropped `client` column) — fixed per the Q8.3 altdata precedent; verify clean on all 3 changes.
- Next dev server's worker pool crashed mid-session (long-running process, "Jest worker… exceeding retry limit") — restart fixed; not a code issue.
- Console content is client-fetched ("use client") — SSR grep can't verify render copy; verified via the API endpoints + compile + 200 instead.

### Completion Notes List

- **All 8 ACs met (AC2/AC3 amended by review — see findings).** The deepest review catch: my step-function used `bisect_right` (vector effective ON its own date) — a one-day look-ahead crediting each new vector with the return its predecessor earned. The closing convention (`bisect_left`, vector earns from d+1) fixed it, and the live cross-check went from approximate to almost exact: **TWR +44.68% / Sharpe 2.17 vs the backtest engine's recorded +44.7% / 2.18** — the off-by-one WAS the gap. Analytics now independently reproduces the engine from stored weights.
- **AC3 amended:** the `returns` block compounds the portfolio's OWN window-filtered series, benchmark-independent — review showed the original "one series with the metrics" design made money PnL change with the benchmark picker.
- **PnL definition recorded:** pnl = optional notional × cumulative TWR; PATCH is merge-patch (`{}` no-op — verified live; explicit null clears).
- **Replace-vector uploads:** re-uploading a date replaces the whole vector transactionally (ghost holdings would corrupt TWR); a fully-unresolved upload leaves data untouched.
- **Coverage honesty:** floor measured on absolute weights per era; renormalised days surfaced (`days_below_full_coverage`, `min_coverage` — live: 2 days, min 0.99); dead-vector eras excluded WITH a warning naming the vector.
- Suites: api 45/45 (30 base + 15 this story); ruff + tsc clean; eslint = exact pre-existing baseline.

### File List

- packages/portfolios/db/deploy/portfolio_notional.sql (new)
- packages/portfolios/db/revert/portfolio_notional.sql (new)
- packages/portfolios/db/verify/portfolio_notional.sql (new)
- packages/portfolios/db/verify/portfolios.sql (modified — pre-existing verify rot: dropped `client` column reference)
- packages/portfolios/db/sqitch.plan (modified — `portfolio_notional [portfolios]`)
- packages/portfolios/src/portfolios/gateway.py (modified — `read_weight_history` + `read_portfolio_terms` seams; create/set_notional; get as-of picker + `shown_as_of_date`; replace-vector upload_weights; snapshot-honesty docstring + `semantics`)
- packages/portfolios/src/portfolios/router.py (modified — notional create/PATCH merge-patch, as-of query param with scoped 422, extended models)
- packages/analytics/src/analytics/gateway.py (modified — effective-dated step-function series under the closing convention; benchmark-independent `returns` block with coverage honesty; dead-vector warnings; abs-weight coverage floor)
- packages/analytics/src/analytics/router.py (modified — `Returns` model + `as_of_date` semantics comment)
- services/api/tests/test_twr_weight_history.py (new — 15 tests)
- apps/web/lib/api-types.ts (regenerated)
- apps/web/app/portfolios/[id]/page.tsx (modified — Holdings table + as-of picker, state preserved across errors/uploads, shown-date labels, snapshot relabel)
- apps/web/components/analytics-panel.tsx (modified — TWR + PnL metrics, effective-dated caption, honest no-notional hint)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — Q4.5/Q5.2 `[BUILT 2026-06-11]`, FR-14/FR-15 ✅, v2 closed, Q6.4 refinement retired)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — chunk-1 FR-15 resolved, A.1 part-3 landed, Q5.2 deferral section)

## Change Log

- 2026-06-11: Story created — the recorded "land together" pair (Q4.5 multi-date history + Q5.2 TWR/PnL + A.1 part 3), PnL defined as cumulative TWR × optional notional.
- 2026-06-11: Implemented + live-verified (12-vector backtest portfolio; TWR/PnL/picker all live). Status → review.
- 2026-06-11: Code review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) — 12 patches applied. Headlines: rebalance-day look-ahead fixed via the closing convention (live cross-check tightened to +44.68%/2.17 vs the engine's +44.7%/2.18 — the off-by-one was the gap); `returns` made benchmark-independent (AC3 amended); PATCH merge-patch semantics; replace-vector uploads; abs-weight coverage floor; dead-vector warnings; coverage-honesty fields; console state-preservation; tests 9 → 15 (strengthened per-era coverage, real window exclusion, benchmark-independence, PATCH/upload semantics). api 45/45. Status → done.
