# Story U1.6: Reproducible universe snapshots

Status: review

## Story

As a researcher,
I want to pin a study to a `(universe, as_of, log-version)` snapshot,
so that reruns give identical membership even after later log corrections.

## Acceptance Criteria

1. Given a snapshot pin `(universe, as_of, log-version)` (a monotonic `event_id` watermark), when membership is queried via the pin, then it reflects the log state at that version, ignoring later-appended events.
2. Given later corrective events, when the same pin is re-queried, then it returns identical membership; an unpinned query reflects the latest log.
3. The log-version mechanism is documented. DB-free tests cover the pinned-vs-latest logic.

## Tasks / Subtasks

- [x] Task 1: `current_log_version(conn, universe_id)` — the `max(event_id)` watermark for the universe (AC #1)
- [x] Task 2: parameterize `projection._membership_events(conn, universe_id, through=None)` with an `event_id <= through` filter; reuse it for both the latest rebuild and pinned reads (AC #1)
- [x] Task 3: `snapshot.py` — pure `members_from_events(events, as_of)` + `members_pinned(conn, universe_id, as_of, log_version)` (pit guard + events-through-version → project → as-of) (AC #1, #2)
- [x] Task 4: DB-free tests (pinned subset ignores later leave/correction; as-of over projection) + live verification (pin a version, append a later leave, rebuild; pinned == original, latest reflects the leave) (AC #2, #3)

## Dev Notes

- **log-version = `max(event_id)` watermark.** `membership_event.event_id` is a monotonic `BIGINT GENERATED ALWAYS AS IDENTITY`, so the max id at snapshot time is a stable cut. A pinned query **re-projects from events `WHERE event_id <= log_version`** (it cannot read the materialized `universe_membership`, which reflects the latest rebuild). Determinism falls out: the projection is a pure function of the ordered event subset, and resolutions are frozen (U1.3), so the same pin always yields the same membership.
- **Reuse, don't duplicate:** add a `through: int | None` parameter to `projection._membership_events` (adds `AND e.event_id <= %s`); the latest rebuild passes `None`, a pinned read passes the watermark. `members_from_events` (pure) = `project_membership` + an as-of interval filter — shared by pinned reads and DB-free-testable.
- **pit guard still applies:** a pinned query before `pit_valid_from` is refused (reuse `query.assert_within_pit`).
- **Known nuance (documented):** the pin is over the *event* log; resolutions are frozen so they don't drift, but a resolution first written *after* the pin (for events already `<= watermark`) could appear in a later rerun — a corner case noted for a future resolution-watermark if it ever matters. Appended events (the dominant mutation) are fully handled.

### References

- [Source: _bmad-output/planning-artifacts/epics-universe-layer.md#Story U1.6]
- [Source: src/sym/universe/projection.py — project_membership + _membership_events]
- [Source: src/sym/universe/query.py — assert_within_pit]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Completion Notes List

- `snapshot.py`: `current_log_version` (`max(event_id)` watermark) + pure `members_from_events(events, as_of)` + `members_pinned(conn, universe_id, as_of, log_version)` (pit guard → events `<= watermark` → project → as-of). Re-projects from the event subset (not the materialized table), so a pin is reproducible by construction.
- `projection._membership_events` gained a `through: int | None` param (`event_id <= through`); the latest rebuild passes `None`, pinned reads pass the watermark — one query, no duplication.
- **Verified live:** pin `V1` → member present; appended a later `leave`; **re-querying `@V1` still returns the member** (identical, ignores the later event) while `@V2` (latest) returns empty (reflects the leave). Cleaned up.
- Documented nuance: the pin is over the *event* log; frozen resolutions don't drift, but a resolution first written after the pin is a noted corner case for a future resolution-watermark.
- 202 tests pass (+4 in `test_universe_snapshot.py`), ruff clean.

### File List

- `src/sym/universe/snapshot.py` (new) — `current_log_version`, `members_from_events`, `members_pinned`.
- `src/sym/universe/projection.py` (modified) — `_membership_events(..., through=None)` watermark filter.
- `tests/test_universe_snapshot.py` (new, 4 tests) — pinned-subset reproducibility.
- `_bmad-output/implementation-artifacts/U1-6-reproducible-snapshots.md` (new) — this story.

### Change Log

| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U1.6: reproducible snapshots via an event_id log-version watermark — `members_pinned` re-projects from events <= the pin, ignoring later-appended events. 202 tests pass, ruff clean; live: a pin stayed identical after a later leave was appended while latest reflected it. Status → review. |
