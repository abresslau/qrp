# Story 3.2: Adjusted-price view (v_prices_adjusted)

Status: review

## Story

As the returns engine,
I want `v_prices_adjusted` to derive adjusted prices in-view from raw + factors,
so that adjustment is deterministic and reproducible with no stored adjusted column.

## Acceptance Criteria

1. **Given** raw prices + explicit factors, **When** the view is queried, **Then** it computes adjusted values deterministically; a NULL base yields NULL (no fabricated value).
2. **Given** identical inputs, **When** queried across runs, **Then** the view returns identical output (determinism, supports NFR-2).
3. **Given** factors derived only from explicit actions, **Then** the view never reverse-engineers factors from price ratios (AR-6 upheld downstream).

## Tasks / Subtasks

- [x] Task 1: exact-product aggregate — `CREATE AGGREGATE product(numeric)` (AC: #2)
- [x] Task 2: `v_prices_adjusted` view — `close_raw`, `split_factor` (from `corporate_actions` only), `adj_close = close_raw / split_factor`, LATERAL; revert + verify; sqitch.plan (AC: #1, #2, #3)
- [x] Task 3: verification — live (continuity, factor==Python, no fabrication, determinism) + sqitch verify (view + exact aggregate)

## Dev Notes

- **Three-layer engine (AR-7):** `prices_raw` + factor store → **`v_prices_adjusted`** (this view) → `fact_returns` (loader, 3.4). The view is a pure, deterministic function of raw + explicit factors — no stored adjusted column (FR-5/AR-7).
- **Split adjustment:** the back-adjusted close is `close_raw / cumulative_split_factor`, where the cumulative factor is the **product of split ratios with `ex_date > session_date`** (strictly greater — a price on/after the ex-date already reflects that split). This makes the series continuous across a split (AAPL pre-split $499 → adj ≈ $125, matching the post-split level).
- **Exactness (AC #2 determinism):** use a custom `product(numeric)` aggregate (exact NUMERIC multiplication) rather than `exp(sum(ln()))`, which is float and would make a 4:1 split factor `3.9999…`. Splits are few, so the LATERAL subquery into the small `corporate_actions` table is cheap (the 20M-row perf check is Story 3.3).
- **AR-6 upheld (AC #3):** `split_factor` is computed **only** from `corporate_actions` records — the view never reads a price ratio. Structural, not just convention.
- **PR vs TR:** this view yields the **split-adjusted** (price-return) series. The total-return series (EXDATE_C dividend reinvestment) is layered on in Story 3.5.
- **Testing:** a SQL view can't be exercised by the DB-free pytest suite; it's covered by the sqitch `verify` script (view queryable + the `product` aggregate proven exact on literals) plus live verification — the same way migrations are validated.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.2: Adjusted-price view (v_prices_adjusted)]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-7 — Three-layer returns engine]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-6 — HARD RULE (factor provenance)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `v_prices_adjusted` derives `adj_close = close_raw / product(split ratios with ex_date > session_date)` via a LATERAL into `corporate_actions`. The custom `product(numeric)` aggregate gives an **exact** factor (4:1 → exactly 4.0, not 3.9999…).
- **Verified live (AAPL):** continuity across the 2020-08-31 4:1 split — 2020-08-28 raw $499.23 → adj **$124.81**, 2020-08-31 raw $129.04 → adj **$129.04** (a normal ~3% move, not a −74% raw drop). 2024-12-30 factor 1, adj == raw. `split_factor` matches the Python `cumulative_split_factor` exactly. View rows == `prices_raw` rows (339,238 — no fabrication). Two queries → identical md5 (deterministic).
- **AR-6 structural:** the factor is computed only from `corporate_actions`; the view never reads a price ratio.
- No pytest (SQL view, DB-free suite); covered by sqitch `verify` (view + exact-product proof) and the live checks above. PR uses `adj_close`; TR series (dividend reinvestment) is Story 3.5.

### File List

- `migrations/deploy|revert|verify/v_prices_adjusted.sql` (new) — `product` aggregate + the view.
- `migrations/sqitch.plan` (modified) — `v_prices_adjusted` change.
- `_bmad-output/implementation-artifacts/3-2-adjusted-view.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.2: `v_prices_adjusted` deterministic split-adjusted view + exact `product(numeric)` aggregate (AR-7/AR-6). Verified live (continuity across AAPL's split, factor==Python spec, no fabrication, deterministic). Status → review. |
