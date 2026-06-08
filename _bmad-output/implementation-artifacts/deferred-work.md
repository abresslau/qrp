
## Deferred from: code review of 3.1-ext-return-window-expansion (2026-06-07)

- `base_date` assumes `asof` is a member of the calendar `sessions` list. Off-calendar price dates (known pre-1990 / vendor-phantom bars, already WARN-classified and inert to returns) make the SESSION-count and snap logic count from the insertion point — slightly off but harmless. Optional hardening: snap `asof` via `_last_on_or_before` before counting. Pre-existing (all base-date snapping shares this assumption).
- No test asserts the migration-seeded `return_window.kind` matches the `windows.py` spec. Low impact: `kind` is non-functional metadata (the engine computes from `windows.py` constants, never the DB column), so drift would be cosmetic. Could add a live consistency check.
- Migration revert scripts hardcode code-lists (`trailing_kind_prior_quarter`) and use `BETWEEN 21 AND 27` range deletes (`cumulative_multiyear_windows`) instead of structural inverses. Correct for the current window set; fragile if new windows are inserted in those id ranges later.
- Equity loader has no test for the since-inception day-one semantics (`SI`=0, `SI_ANN`=None on a single-session history); only the index side (`test_benchmark_returns`) covers it.
- No PQ (`period` kind) test against a sparse or real exchange calendar — current tests use dense weekday fixtures only.
