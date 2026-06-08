# Story 3.5: Total-return matrix

Status: review

## Story

As a researcher,
I want TR (dividends reinvested on ex-date, gross) for the same 18 windows,
so that total return is available alongside price return.

## Acceptance Criteria

1. **Given** dividends, **When** TR computes, **Then** it follows EXDATE_C reinvestment for all 18 windows / the same (FIGI, date) pairs, with the same schema and NULL rules as PR.
2. **Given** a name with no dividends, **Then** TR = PR.
3. **Given** a multi-year dividend payer, **Then** TR > PR.

## Tasks / Subtasks

- [x] Task 1: `total_return_index(rows, dividends)` — EXDATE_C, `TRI = adj_close × cumulative dividend growth` (rounding-free price term)
- [x] Task 2: unified `compute_return_rows` (pr+tr per window) + `load_returns` (one-pass per figi, UPSERT pr+tr+input_hash); `sym recompute` writes both; `input_hash` covers TRI endpoints
- [x] Task 3: tests (no-div → TR==PR exact; in-window dividend → TR>PR; TRI math; input_hash signature)

## Dev Notes

- **No migration:** `fact_returns.tr` already exists (Story 3.4); this story only fills it.
- **EXDATE_C (AC #1):** the total-return index reinvests each dividend on its ex-date, gross. Daily TRI factor = `adj_close(d)/adj_close(d-1) × (1 + D/close_raw(d))` — the split-adjusted price ratio (continuous across splits) times one plus the ex-date dividend **yield**. The yield is scale-invariant (`D_raw/close_raw == D_adj/adj_close`), so no separate dividend split-adjustment is needed. `TR(window) = TRI(asof)/TRI(base) − 1` (or CAGR), with the same base-date and NULL rules as PR.
- **AC #2 (no dividends → TR = PR):** with zero dividends the TRI factor is exactly the adjusted price ratio, so TRI tracks `adj_close` and TR == PR by construction.
- **AC #3 (payer → TR > PR):** positive ex-date yields compound the TRI above the price series, so TR exceeds PR for a dividend payer.
- **One-pass loader:** PR and TR are computed together per figi (one read of `v_prices_adjusted` + dividends, one forward TRI pass) — keeps the 3.3-validated filtered-per-figi access pattern.
- **`input_hash`:** extended to cover the TRI endpoints (which encode raw + splits + dividends) + calendar_version — so a dividend change marks the row dirty for 3.6's incremental recompute.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.5: Total-return matrix]
- [Source: _bmad-output/planning-artifacts/epics.md#FR-10 — Total return matrix]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- The loader now computes PR + TR in one per-figi pass. TR uses a total-return index `TRI[d] = adj_close[d] × ∏(1 + D/close_raw(ex))` over ex-dates ≤ d (EXDATE_C, gross). `input_hash` extended to cover the TRI endpoints (dividends).
- **Live bug found + fixed by AC#2:** computing the TRI as a cumulative product of price *ratios* accumulated Decimal rounding, so TSLA (no dividends) showed TR ≈ PR but not equal. Reformulated as `adj_close × dividend-growth` (price term exact, growth ≡ 1 when no dividends) → TR == PR **exactly**.
- **Verified live** (`sym recompute`, 282,222 PR+TR rows): AC#2 TSLA (no dividends) — all windows TR==PR exactly; AC#3 AAPL 1Y — PR 53.19% / **TR 53.80%** (TR>PR, ~0.6pp dividend contribution, matching AAPL's yield); 265k tr values populated. 139 tests pass, ruff clean. No migration (the `tr` column existed from 3.4).

### File List

- `src/sym/returns/loader.py` (refactored) — `total_return_index`, unified `compute_return_rows` (pr+tr), `load_returns`, extended `input_hash`.
- `src/sym/cli.py` (modified) — `recompute` calls `load_returns` (PR+TR).
- `tests/test_loader.py` (updated, 9 tests) — TR/PR equality + payer cases, TRI math.
- `_bmad-output/implementation-artifacts/3-5-total-return.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.5: TR via EXDATE_C total-return index; unified PR+TR loader; `recompute` writes both. Live AC#2 caught a TRI rounding bug (ratio-product) — reformulated to `adj×dividend-growth` so TR==PR exact with no dividends. Verified live (TSLA TR==PR; AAPL TR>PR). Status → review. |
