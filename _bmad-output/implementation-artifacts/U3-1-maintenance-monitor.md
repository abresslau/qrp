# Story U3.1: Daily maintenance monitor (event discovery + liveness)

Status: review

## Story

As the pipeline,
I want a scheduled per-index monitor that discovers membership-change events and appends them to the log,
so that universes stay current automatically and a frozen universe is never mistaken for a stable one.

## Acceptance Criteria

1. A scheduled, idempotent, per-index monitor re-runs the preferred provider, discovers change-events, appends them; re-running the same day is a no-op.
2. Each run records `last_successful_monitor` per index + a monitor run-log row {index, joiners, leavers, action}.
3. An empty or failed parse is recorded as an **error, never "no change."**
4. A change effective on a non-trading day / TZ skew is aligned to the exchange calendar.
5. DB-free tests cover discovery + idempotency with fake providers; live-verified on at least one index.

## Tasks / Subtasks

- [x] Task 1: `universe_monitor_log` migration (run-log + liveness; deployed + verified) (AC #2)
- [x] Task 2: `run_monitor` — rerun provider, append-new (idempotent), re-resolve + rebuild on change, write run-log; empty/failed = error (AC #1, #2, #3)
- [x] Task 3: liveness — `last_successful_monitor` + `stale_monitors` (AC #2)
- [x] Task 4: calendar alignment — pure `snap_to_sessions` + DB-backed `align_changes` (AC #4)
- [x] Task 5: DB-free tests (snap logic) + live verification on sp500 (AC #5)

## Dev Notes

- The monitor reuses the U1/U2 spine: `get_provider` → `append_change` (idempotent dedupe → re-run is a no-op) → `resolve_universe_members` + `rebuild_projection` only when something changed. Appended discoveries count as `applied`; the gating layer (U3.2) will route surprising ones to `proposed` instead.
- **Empty/failed = error (NFR2):** any provider exception, or an empty change set, writes a `status='error'` row — never a silent "no change". `last_successful_monitor` only advances on success, so a stuck monitor goes stale and alarms.
- Calendar alignment is optional (config `calendar_mic`); the pure `snap_to_sessions(changes, session_for)` is unit-tested, the DB-backed wrapper queries the current trading calendar.
- The three Epic-U3 schema migrations (`universe_monitor_log`, `membership_proposal`, `universe_accuracy_check`) are deployed together here as the epic's schema foundation; U3.2/U3.3 add their code on top.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `monitor.py`: `run_monitor` (rerun → append-new → conditional re-resolve/rebuild → run-log), `last_successful_monitor`, `stale_monitors`, pure `snap_to_sessions` + `align_changes`, `MonitorSummary`.
- Migrations `universe_monitor_log` / `membership_proposal` / `universe_accuracy_check` deployed via Docker sqitch + verified.
- **Live-verified on sp500:** run1 success (0 new — seed already captured all), run2 idempotent (0), `last_successful_monitor` set, `stale_monitors` correctly drops sp500 and flags un-monitored sp400/sp600. Empty-provider path returns `error` (reproduced before the providers-import fix).
- 3 DB-free tests (snap logic); full suite **241 passed**, ruff clean.

### File List
- `migrations/deploy|revert|verify/universe_monitor_log.sql` (new)
- `migrations/deploy|revert|verify/membership_proposal.sql` (new — used by U3.2)
- `migrations/deploy|revert|verify/universe_accuracy_check.sql` (new — used by U3.3)
- `migrations/sqitch.plan` (modified — 3 Epic-U3 changes)
- `src/sym/universe/monitor.py` (new)
- `tests/test_universe_monitor.py` (new)
- `_bmad-output/implementation-artifacts/U3-1-maintenance-monitor.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U3.1: daily maintenance monitor + liveness + calendar alignment + Epic-U3 schema. Live-verified on sp500 (idempotent, staleness). 241 tests pass. |
