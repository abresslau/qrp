# Story 3.7: Survivorship invariant

Status: review

## Story

As a researcher,
I want delisted securities to flow through the returns engine,
so that backtests built on sym are survivorship-bias-free.

## Acceptance Criteria

1. **Given** a delisted security with history, **Then** it appears in `v_prices_adjusted` and `fact_returns` for its active dates.
2. **Given** the engine, **Then** no code path silently filters `status = 'delisted'` out of returns.
3. **Given** a known delisted name, **Then** a test asserts it has computed returns through its delisting date.

## Tasks / Subtasks

- [x] Task 1: remove the `status = 'active'` filter from the returns loader — `_active_securities` → `_securities_for_returns` (spans active + delisted + suspended)
- [x] Task 2: guard test — scan `src/sym/returns/*.py` for any `status = '…'` predicate; assert none (AC #2)
- [x] Task 3: guard test — `v_prices_adjusted` reads `prices_raw` with no `status` reference (AC #1 view half)
- [x] Task 4: live behavioral verification — delist a name with history, recompute, assert it flows through `v_prices_adjusted` + `fact_returns` through its delist date, then restore (AC #1/#3)

## Dev Notes

- **The only culprit was the loader.** `v_prices_adjusted` already reads `prices_raw` directly (no `securities` join, no status gate), so delisted prices flowed through the view unchanged. The returns loader, however, selected `WHERE status = 'active'` — silently dropping every delisted name out of `fact_returns`. That single predicate *was* the survivorship bias. Removed: the loader now spans all securities regardless of lifecycle status.
- **Status filtering belongs to ingestion, not returns.** `pipeline.py` (what to fetch next) and `gics.py` (what to classify) correctly scope to active — a delisted name has no new prices to fetch. AR-8 governs the *returns engine* specifically: history already captured must always be computable. The active/delisted split is a **query-time** choice for the researcher (`lifecycle._active_filter` / `iter_securities(include_delisted=…)`), never a silent compute-time filter.
- **No migration.** Code-only change (one SQL predicate dropped in the loader) plus two DB-free guard tests. The guard tests are the regression gate: they fail if anyone reintroduces a lifecycle-status filter into the returns engine or the adjusted-price view.
- **Delisted names naturally terminate.** A delisted security has no prices after its delist date, so its asofs (and thus its `fact_returns` rows) stop there automatically — no special-casing needed; just don't exclude it.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.7: Survivorship invariant]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-8 — survivorship invariant]
- [Source: src/sym/identity/lifecycle.py — soft-delete + explicit (never silent) active filter (Story 1.7)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- Returns loader no longer filters on lifecycle status: `_securities_for_returns` selects every security; delisted names flow through `fact_returns` for their active dates (AR-8).
- Two DB-free guard tests lock the invariant: no `status = '…'` predicate anywhere in `src/sym/returns/`, and no `status` reference in `v_prices_adjusted.sql`.
- **Verified live:** delisted subject `BBG000D0D358` (status→delisted, delist_date 2026-06-05) — `v_prices_adjusted` kept all 9,333 rows; `load_returns` processed it (`securities=1`, would be `0` under the old active-only loader); `fact_returns` materialized 29,286 rows with `max(asof)` = the delist date and all **18 windows on the delisting date**. State restored (subject reactivated, delist_date cleared).
- 144 tests pass (+2 guards), ruff clean. No migration.

### File List

- `src/sym/returns/loader.py` (modified) — `_active_securities` → `_securities_for_returns` (no status filter); `load_returns` docstring updated.
- `tests/test_loader.py` (modified, +2 tests) — survivorship guards.
- `_bmad-output/implementation-artifacts/3-7-survivorship-invariant.md` (new).

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 3.7: removed the `status='active'` filter from the returns loader so delisted securities flow through `fact_returns` (AR-8 survivorship invariant). Added two guard tests; verified live (delisted subject materialized 18 windows through its delist date). Status → review. |
