# Story 3.1: 18-window return-math specification

Status: review

## Story

As the returns engine,
I want a precise specification for all 18 windows in `windows.py`,
so that calendar anchoring, reinvestment timing, and annualization are unambiguous before any computation.

## Acceptance Criteria

1. **Given** the spec, **Then** each window is defined: calendar-anchored (1D, WTD, MTD, QTD, YTD) use the prior period-end base; rolling (1M, 3M, 6M, 9M, 1Y) use the same-calendar-date N periods prior, with weekend/holiday → last trading day on/before.
2. **Given** multi-year windows (2Y, 3Y, 5Y, 10Y, 20Y, 30Y), **Then** returns annualize as CAGR; IPO_ANN base = first available close.
3. **Given** total return, **Then** EXDATE_C reinvestment timing (dividend reinvested on ex-date, gross) is specified.
4. **Given** insufficient history for a window, **Then** the value is NULL (documented rule).

## Tasks / Subtasks

- [x] Task 1: window registry in `src/sym/returns/windows.py` (AC: #1, #2)
- [x] Task 2: base-date resolver (`base_date`) — calendar/rolling/multiyear/ipo; None on insufficient history (AC: #1, #2, #4)
- [x] Task 3: return formula (`canonical_return` cumulative/CAGR, `period_years`); EXDATE_C documented (AC: #2, #3, #4)
- [x] Task 4: tests in `tests/test_windows.py` (13 tests) — base dates per kind, NULL rule, month clamp, CAGR, the window set

## Dev Notes

- **Spec, not computation (OI-2):** this story makes `windows.py` an executable spec — the *time periods*, base-date rules, and return formulas — independent of price storage. The actual `fact_returns` materialization (querying `v_prices_adjusted`, writing rows) is Stories 3.2/3.4; the PR/TR *price series* difference is Story 3.5.
- **Calendar-anchored base = prior period-end** (FR-9): YTD base = last session of the prior year, MTD = last session of prior month, etc.; 1D = the prior session. **Rolling** = the same calendar date N periods prior, snapped to the last trading day **on or before** it (weekend/holiday). Base-date logic reads the snapshotted `trading_calendar` (Story 2.1) — passed in as `sessions`, so the spec stays pure/testable.
- **Annualization (FR-9):** multi-year (2Y–30Y) and IPO are CAGR over the *actual* elapsed years `(asof − base)/365.25`; 1Y and shorter are cumulative. `IPO_ANN` base = first available close.
- **NULL rule (AC #4):** if the base date can't be resolved (history doesn't reach the target), the window is NULL — `base_date` returns `None`.
- **EXDATE_C (AC #3):** total return reinvests each dividend on its ex-date, gross — documented here; applied when 3.5 builds the TR-adjusted series. PR uses the split-only-adjusted series; both use these same windows.
- **Window count (resolved):** FR-9 enumerated 17 but said "18". Resolved per user: added **1W** (rolling one-week, distinct from calendar WTD) as the 18th, slotted as the first rolling window; ids renumbered 1–18 (safe — `fact_returns` not yet built). Final set: 1D, WTD, MTD, QTD, YTD, **1W**, 1M, 3M, 6M, 9M, 1Y, 2Y–30Y_ANN, IPO_ANN.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.1: 18-window return-math specification]
- [Source: _bmad-output/planning-artifacts/epics.md#FR-9 — Price return matrix]
- [Source: _bmad-output/planning-artifacts/epics.md#OI-2 — 18-window return-math spec]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `windows.py` is a pure, executable spec (no DB): `WINDOWS` registry (17, stable ids 1–17), `base_date` resolver, `canonical_return` (cumulative / CAGR via Decimal ln/exp), `period_years`, and the EXDATE_C TR-reinvestment rule documented for Story 3.5.
- **Verified live** against the real XNAS calendar (asof 2027-12-31, 9,569 sessions): all 17 windows resolve sensibly — 1D→prior session, YTD→2026-12-31, 30Y_ANN→1997-12-31, IPO_ANN→1990-01-02. 129 tests pass, ruff clean.
- **Window count resolved:** added **1W** (rolling one-week) as the 18th per user; full set is 18, ids 1–18.
- No migration/CLI — this is the spec layer; `v_prices_adjusted` (3.2) and the `fact_returns` loader (3.4/3.5) consume it.

### File List

- `src/sym/returns/windows.py` (new) — window registry, base-date resolver, return formulas.
- `tests/test_windows.py` (new, 13 tests).
- `_bmad-output/implementation-artifacts/3-1-window-spec.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.1: `windows.py` — return-math spec: registry, base-date anchoring (calendar/rolling/multiyear/IPO), CAGR annualization, NULL rule, EXDATE_C documented. Verified live against the XNAS calendar. Status → review. |
| 2026-06-06 | Resolved the count: added `1W` (rolling one-week, distinct from WTD) as the 18th window; renumbered to ids 1–18. Now genuinely 18. 130 tests pass. |
