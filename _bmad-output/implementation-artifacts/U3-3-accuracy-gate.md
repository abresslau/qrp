# Story U3.3: Membership accuracy gate

Status: review

## Story

As Andre,
I want a periodic cross-check of each universe against an independent second source,
so that I am alarmed when membership is wrong, not merely stale.

## Acceptance Criteria

1. Cross-check maintained membership vs an **independent** second source; alarm on divergence beyond a threshold.
2. A proxy reference (ETF that legitimately differs) gets a proxy-aware tolerance to avoid alert fatigue.
3. The gate catches a *wrong* universe (not just a stale one); DB-free tests cover the divergence comparison.

## Tasks / Subtasks

- [x] Task 1: pure `evaluate` — Jaccard-distance divergence, missing/extra sets, proxy-aware effective threshold, alarm (AC #1, #2)
- [x] Task 2: `run_accuracy_check` — compare maintained tokens vs reference, write `universe_accuracy_check` audit row (AC #1)
- [x] Task 3: `current_tokens_from_changes` (reference from a snapshot source) + `accuracy_alarms` (latest alarming check per universe, for the digest) (AC #1)
- [x] Task 4: DB-free tests (divergence math, proxy tolerance, edge cases) + live verification on sp500 (AC #3)

## Dev Notes

- Comparison is on normalised identifier **tokens** (both pipelines build them via `membership_diff`), so it doesn't depend on resolution succeeding, and the reference must be a genuinely *independent* source (the caller's responsibility — e.g. ETF holdings vs a Wikipedia-derived list, not two derivatives of one upstream).
- Divergence = Jaccard distance `|A △ B| / |A ∪ B|`. Proxy references widen the threshold by `proxy_tolerance`.
- A *wrong* universe (large symmetric difference) alarms even when the monitor is fresh — staleness (U3.1) and wrongness (U3.3) are distinct signals.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `accuracy.py`: pure `evaluate` (Jaccard distance + proxy tolerance + alarm), `current_tokens_from_changes`, `maintained_tokens`, `run_accuracy_check` (writes audit row), `accuracy_alarms`.
- **Live-verified on sp500** (503 maintained tokens): a near-identical reference (5 dropped/5 added) → divergence 0.0197, no alarm (within proxy tolerance); a deliberately-wrong reference (100 of 503) → divergence 0.80, alarm. Test rows cleaned up.
- 6 DB-free tests; ruff clean.

### File List
- `src/sym/universe/accuracy.py` (new)
- `tests/test_universe_accuracy.py` (new)
- `_bmad-output/implementation-artifacts/U3-3-accuracy-gate.md` (new)
- (`universe_accuracy_check` migration deployed in U3.1)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U3.3: membership accuracy gate (Jaccard divergence vs independent source, proxy-aware tolerance, audit rows). Live-verified on sp500. 6 DB-free tests. |
