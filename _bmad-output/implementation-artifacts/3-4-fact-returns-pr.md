# Story 3.4: fact_returns loader and price-return matrix

Status: review

## Story

As a researcher,
I want PR for all 18 windows materialized into `fact_returns`,
so that cross-sectional price-return queries are fast and reproducible.

## Acceptance Criteria

1. **Given** migrations, **Then** `fact_returns` exists as a loader-written table (NOT a materialized view) with PK `(security_id, window_id, asof)` and an `input_hash` column.
2. **Given** `v_prices_adjusted`, **When** the loader runs, **Then** PR is computed for all 18 windows per (FIGI, date) per the spec, stored as decimals, with insufficient history → NULL.
3. **Given** each written row, **Then** `input_hash = hash(raw_slice + factor_set + calendar_version)` is stamped.

## Tasks / Subtasks

- [x] Task 1: `fact_returns` migration — `return_window` (18 seeded) + `fact_returns` (PK composite_figi/window_id/asof, pr+tr, input_hash, FKs, cross-sectional index) (AC: #1)
- [x] Task 2: loader `src/sym/returns/loader.py` — `input_hash`, pure `compute_pr_rows`, `load_pr` (per-figi filtered reads → COPY→UPSERT, durable per figi) (AC: #2, #3)
- [x] Task 3: `sym recompute [--from --to]` CLI (AC: #2)
- [x] Task 4: tests `tests/test_loader.py` (8) — PR cumulative/CAGR/NULL, hash determinism+sensitivity, anti-drift seed==windows.py

## Dev Notes

- **Loader-written, not a materialized view (AR-7):** `fact_returns` is a plain table the loader fills, so refresh is incremental (dirty-set, Story 3.6) and rows carry provenance — the 3.3 spike proved a live full-view scan is ~9 min, so the matrix must be materialized.
- **3.3 directive applied:** the loader reads `v_prices_adjusted` **filtered per figi** (the cheap path, sub-second per security), pulls the security's adjusted series + the current calendar once, and computes all asofs × 18 windows in Python via the `windows.py` spec — never a full-view scan.
- **PR per window (AC #2):** `base_date(window, asof, calendar sessions)` → look up `adj_close` at asof and base → `canonical_return` (cumulative or CAGR). Base unresolved or no price at base → **NULL row** written (the cell exists, value NULL).
- **`input_hash` (AC #3):** `sha256(calendar_version | base | adj_base | asof | adj_asof)` — the adjusted endpoints already encode raw_slice + split factor_set, plus the calendar_version. Stable + reproducible (DR determinism). Story 3.5 extends it to cover dividends when TR lands; 3.6's dirty-set reads it.
- **pr + tr in one row:** PK `(composite_figi, window_id, asof)` per the epics; 3.4 fills `pr` (`tr` NULL), 3.5 fills `tr`.
- **`sym recompute`** is the deterministic rebuild command the DR runbook (2.9) depends on; this story makes it produce PR over a date range.
- **Scope:** full-history materialization across the universe is a long batch; the demo recomputes a bounded recent range. The incremental dirty-set + anomaly gate are Story 3.6.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.4: fact_returns loader and price-return matrix]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-7 — Three-layer returns engine]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `fact_returns` is a loader-written table (PK composite_figi/window_id/asof, `pr`+`tr`, NOT NULL `input_hash`), with `return_window` reference (18 seeded, anti-drift test vs `windows.py`) and an `(asof, window_id)` cross-sectional index.
- The loader reads `v_prices_adjusted` **filtered per figi** (the 3.3-validated cheap path), pulls the adjusted series + calendar once, computes 18 windows per asof via `windows.py`, and COPY→UPSERTs (durable per figi). Insufficient history → NULL row, still hashed.
- **Verified live:** `sym recompute --from 2025-01-01 --to 2026-06-05` → 44 securities, **282,222 PR rows**. AAPL as-of 2026-06-05: 1D −1.25%, YTD +13.05%, 1Y +53.19%, 10Y_ANN +28.78%, **IPO_ANN +20.62%** (matches AAPL's real long-run CAGR — annualization correct). Cross-sectional YTD query (all securities) in **1.2ms** (SM-4 <10s, easily). 138 tests pass, ruff clean.
- `input_hash` covers PR inputs (adj endpoints + calendar_version); Story 3.5 extends it for dividends/TR. `tr` left NULL until 3.5.

### File List

- `migrations/deploy|revert|verify/fact_returns.sql` (new) — `return_window` + `fact_returns`.
- `migrations/sqitch.plan` (modified) — `fact_returns` change.
- `src/sym/returns/loader.py` (new) — `input_hash`, `compute_pr_rows`, `load_pr`.
- `src/sym/cli.py` (modified) — `sym recompute`.
- `tests/test_loader.py` (new, 8 tests).
- `_bmad-output/implementation-artifacts/3-4-fact-returns-pr.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.4: `fact_returns` materialized PR matrix + `return_window` ref + `sym recompute`. Loader reads `v_prices_adjusted` per-figi (3.3 directive), 18 windows, input_hash, NULL rule. Verified live (282k PR rows; AAPL matrix sensible; cross-sectional 1.2ms). Status → review. |
