# Story U3.7: Provenance-aware corrective events — tombstone pairing (ledger D3)

Status: done

## Story

As Andre (the operator),
I want a `correct` event to nullify exactly the wrong event it names (via `provenance.reverses`) instead of blindly toggling whatever state the projector happens to be in, and the monitor's open-set logic to agree with the projector about what a correction means,
so that `sym universe reverse` — now an operator-facing CLI — reliably undoes the change I point it at, and a reversal doesn't leave the log and the projection telling different stories.

## Background (why this story exists)

Ledger **D3** (chunk-3 review): the projector treats `correct` as a context-free toggle — `opening = CORRECT and open_from is None`, `closing = CORRECT and open_from is not None` (`projection.py::_intervals_for_figi`) — ignoring the `provenance.reverses` field that `gating.reverse_change` has written since U3.2. Three concrete defects:

1. **Intervening events invert intent.** A corrective sorts at `(its effective_date, event_id)`; any event between the wrong change and the corrective flips the state the toggle sees, so the "reversal" can apply the opposite of what the operator asked.
2. **Two state machines disagree.** Observed live in U3.5: after `reverse` of a leave, the projector toggles the member OPEN while `monitor._open_tokens` (latest-change-wins, `change == JOIN` only) reads it CLOSED — the leaver diff and the projection contradict each other from that moment on.
3. **The projector never reads provenance at all** — `_membership_events` doesn't even SELECT the column.

U3.5 round-2 mitigations already in place (do not redo): `reverse_change` refuses never-recorded targets and refuses `change='correct'` (reversing a corrective under toggle semantics would re-apply the wrong change).

## Design (recorded choice): tombstone pairing

A `correct` event whose `provenance.reverses` names a change kind is a **tombstone** for exactly one event: the row matching `(universe_id, raw_identifier, change == reverses, effective_date == the corrective's effective_date)` — the same triple+date `reverse_change` validates exists before appending. The projector removes BOTH events (target + tombstone) from the stream before running the state machine. Consequences:

- Intervening events can no longer invert intent — annihilation is by identity, not by state.
- Ordering position of the corrective becomes irrelevant.
- A corrective with NO match (legacy provenance-less rows, or hand-written provenance naming a non-existent target) falls back to today's toggle behavior and is COUNTED (`toggle_corrections` on the summary) — visibility, not silent reinterpretation of history.

The monitor's `_open_tokens` switches to the same pure pairing+state-machine logic at the raw-token level (resolution-independent), so the log-derived open set and the projection agree by construction.

**Known limitation (documented, not solved):** the dedupe key `(universe, raw, change, effective_date)` allows only ONE `correct` row per (raw, date) — a same-member join AND leave on the same date can't both be reversed, and a correction can't itself be un-corrected at the same date. Schema stays untouched (re-assert at the true date instead).

## Acceptance Criteria

1. **Pairing:** Given a wrong event and a corrective whose `provenance.reverses` matches it (same raw_identifier + change + effective_date), the projector excludes both from interval building; an event from another source landing between them does NOT change the outcome (the D3 inversion case, tested explicitly).
2. **Legacy fallback:** a `correct` with no `reverses` provenance or no matching target keeps the existing toggle behavior; `ProjectionSummary` gains `paired_corrections` and `toggle_corrections` counters; `test_correct_toggles_state` keeps passing unchanged.
3. **One state machine:** `monitor._open_tokens` derives the open set from the same pure pairing logic (token-level, resolution-independent) — after a reverse, `_open_tokens` and the projection agree. The snapshot-leaver diff therefore does NOT re-derive a leave for a member whose leave was just reversed (it is open again and present in the snapshot).
4. **Provenance plumbed:** `_membership_events` selects `provenance`; the pure projector consumes it via the event dataclass.
5. **Round-trip live verification (ibov, synthetic member):** join promoted → leave promoted → `sym universe reverse` the leave → member OPEN in both `universe_membership` and the open-token set → next monitor run derives nothing for it (snapshot contains it). Cleanup per the test-row rule.
6. **Docs + ledger:** `docs/data-conventions.md` correct-event semantics updated (tombstone pairing + legacy toggle fallback + the same-date dedupe limitation); D3 marked done.
7. **Tests:** pairing, inversion case, fallback, mixed (paired + toggle in one log), `invert(project)==log` property test untouched and green; full suite green.

## Tasks / Subtasks

- [x] Task 1: Pure projector pairing (AC: 1, 2, 4)
  - [x] `MembershipEvent` gains `provenance: dict | None = None`; `_membership_events` SELECTs it
  - [x] Pre-pass `pair_corrections(events) -> (survivors, paired, toggles)`: match each reverses-corrective to its target by (raw_identifier, change, effective_date); remove both; unmatched correctives stay as toggle events
  - [x] `ProjectionSummary.paired_corrections` / `.toggle_corrections`; counters threaded through `project_membership`
  - [x] DB-free tests incl. the intervening-event inversion case (8 tests, new file)
- [x] Task 2: Unify `_open_tokens` on the same logic (AC: 3)
  - [x] Token-level open-set replay (pair_corrections + join/leave/toggle machine) replaces the `DISTINCT ON` latest-change-wins SQL
  - [x] Routing test: a reversed leave reads OPEN; the provider re-stating the member produces zero discoveries (old logic staged a phantom rejoin)
- [x] Task 3: Live round-trip on ibov (AC: 5)
- [x] Task 4: Docs + ledger (AC: 6)
- [x] Task 5: Full suite + lint (AC: 7)

### Review Findings (code review 2026-06-10, commit e83e5f2 — ALL RESOLVED)

- [x] [Review][Decision→Patch] Dangling EXPLICIT corrective — RESOLVED (option a, deviating from the story's constraint 4 by recorded operator decision): a corrective naming a target that doesn't exist is DROPPED (inert) and counted as `dangling_corrections`; only provenance-less legacy rows keep toggle behavior [projection.py]
- [x] [Review][Patch] "Agree by construction" scoped to the PAIRED path in docs §5 (legacy toggles can diverge token-vs-FIGI; unresolved tokens monitor-only by design); live census: ZERO correctives exist in the log, so no legacy rows are affected; toggle/dangling counts surface at projection rebuild (documented) [docs]
- [x] [Review][Patch] AC5 redone with a RESOLVED member (ABEV3/BBG000DCR6J5): synthetic leave → projection AND log-replay read closed → `reverse` → BOTH read open, `paired_corrections=1` live → monitor derives NOTHING (member in B3 snapshot + open) → 2 synthetic events deleted, 78 members, monitor 0/0. AC5's literal observables produced this time [live verification]
- [x] [Review][Patch] Mixed paired+toggle test + monitor unmatched-toggle routing test added [tests]
- [x] [Review][Patch] Non-dict provenance guarded (isinstance); `raw_identifier=None` corrective → dangling, never None-matched [projection.py]
- [x] [Review][Patch] Preconditions documented on `pair_corrections` (single-universe stream, DB dedupe invariant) [projection.py]
- [x] [Review][Patch] Story record arithmetic corrected (see amended notes below) [story file]
- [x] [Review][Patch] Keyword-args event construction + redundant re-sort dropped (SQL ordering is the contract, stated) [monitor.py]
- [x] [Review][Patch] Docs §5: CLI blocks un-correction at any date; adjacent-date advice scoped by precision; `members_pinned` one-time shift recorded in §5 + snapshot.py docstring [docs]
- [x] [Review][Patch] Ledger entry added: exact-date re-assertion dead-end → dedupe-key nonce (schema follow-up) [deferred-work.md]

Record corrections (review round): Task 1 produced 7 pairing tests (not 8); the e83e5f2 commit added 8 tests total (7 pairing + 1 routing), not 9; the invert-roundtrip property is scoped to join/leave streams by design — pairing correctness has its own dedicated tests. Post-review the pairing file has 10 tests and the suite is 486.
- [x] [Review][Defer] Exact-date corrective re-assertion dead-end (schema nonce) — deferred to ledger, schema change out of scope
- Dismissed (3): property-test "hollowness" (the invert-roundtrip is and was scoped to join/leave streams; pairing has dedicated coverage); unresolved-token monitor/projection divergence (pre-existing by design, surfaced via `excluded_unresolved`); duplicate-target order dependence (impossible under the DB dedupe key; covered by the precondition docstring patch).

## Dev Notes

### Wiring map

| File | Current | Change |
|---|---|---|
| `universe/projection.py` | `_intervals_for_figi` toggle at lines ~60-70; `_membership_events` omits provenance; `ProjectionSummary` has figis/intervals/excluded/orphans | pairing pre-pass (pure), provenance on the event dataclass + SELECT, two new counters |
| `universe/monitor.py` | `_open_tokens`: SQL `DISTINCT ON (raw_identifier) ... change == 'join'` — latest-change-wins, correct-blind | fetch `(raw_identifier, change, effective_date, event_id, provenance)` rows; reuse the pure pairing/state machine per token |
| `universe/gating.py` | `reverse_change` writes `provenance={"reverses": change, "by": ..., "detail": ...}`, validates target exists + change ∈ {join, leave} | NO changes (provenance shape is already exactly what pairing needs) |
| `tests/test_universe_projection.py` | toggle test + invert-roundtrip property | keep green; add pairing tests (new file or extend) |
| `tests/test_universe_monitor_routing.py` | `_Conn` fake answers `DISTINCT ON` for `_open_tokens` | fake must serve full event rows for the new open-set query |

### Constraints

1. **Schema untouched** — dedupe key stays; the same-date double-correct limitation is documented, not solved.
2. **`rebuild_projection` stays a deterministic full rebuild**; pairing happens in the pure layer so the property tests keep exercising it.
3. **Pairing is per `raw_identifier`** (the corrective references the wrong EVENT row, pre-resolution), not per FIGI — two raw tokens resolving to one FIGI must not cross-annihilate.
4. **Multiple correctives, one target:** impossible at same date (dedupe); a second corrective at a DIFFERENT date has no matching target (dates differ) → falls back to toggle, counted. Acceptable; note in docs.
5. **`as_of_date` canonical naming**; `conn.autocommit=True` durability pattern in any live scripts.
6. **Monitor performance:** full-log fetch per monitor run is fine at current scale (≤ a few thousand events/universe); note it in the docstring rather than optimizing prematurely.

### Previous-story intelligence

- U3.5/U3.6 fakes: `_Conn` SQL-substring dispatch — the new `_open_tokens` query must keep a distinguishable substring (e.g. keep selecting `FROM membership_event` with an ORDER BY; update fakes in routing + accuracy-runner tests, which both answer `DISTINCT ON` today — the accuracy fake answers `membership_event e` generically and may need nothing).
- The U3.5 live test sequence (synthetic `ticker:ZZZTEST3@BVMF`, backdated persistence, explicit cleanup) is the template for AC 5.
- Suite baseline 474 tests / ~3s; repo lint baseline 18 pre-existing errors.

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md — D3]
- [Source: packages/sym/src/sym/universe/{projection,monitor,gating,events}.py]
- [Source: docs/data-conventions.md — correct-event section to update]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor per task.

### Debug Log References

- Task 1 RED: collection error (pair_corrections absent) → 1 test failure was a wrong ASSERTION, not wrong code: at the FIGI level a genuine same-date leave from the other token correctly closes the membership — the per-raw guarantee is that it SURVIVES annihilation; test rewritten to assert survivor identity + the closed interval.
- Task 2 RED: 7 routing failures once the fake stopped serving the old `DISTINCT ON` query — confirms every `_open_tokens` consumer migrated.

### Completion Notes List

- **Task 1:** `pair_corrections` (pure) tombstones each reverses-corrective with exactly the event matching `(raw_identifier, reverses, effective_date)` — the same key `reverse_change` validates before appending, so every CLI-created corrective pairs by construction. Unmatched/legacy correctives survive as toggles, counted (`toggle_corrections`); `test_correct_toggles_state` passes unchanged. Pairing is per raw token (constraint 3) — verified by the cross-annihilation test.
- **Task 2:** `_open_tokens` replays the full ordered log through the SAME pairing + state machine (token-level toggle for unmatched correctives). The two state machines now agree by construction; full-log fetch per run noted as fine at current scale.
- **Task 3 (live, ibov, synthetic `ticker:ZZZTEST3@BVMF`):** join@06-08 + leave@06-09 → open-set reads CLOSED → `sym universe reverse ibov <tok> leave 2026-06-09` → open-set reads OPEN → next monitor run derives a leave proposal for it (open + absent from B3's real snapshot — the live proof the diff now sees it open; staged, not applied). Cleanup: 3 events + 1 proposal + 1 resolution row deleted, projection rebuilt, monitor back to 0/0 baseline with 78 members. Caveat recorded: the projection-level `paired_corrections` counter read 0 live because the synthetic token is UNRESOLVED and `_membership_events` excludes unresolved members — the pure pairing is fully covered DB-free; resolved-member live pairing would need a real member reversal.
- **Task 4:** `docs/data-conventions.md` gained §5 (tombstone pairing, legacy fallback, the three dedupe-key limitations and the operator path around them); D3 marked done on the ledger.
- **Task 5:** suite 474 → 482 green (9 new tests, incl. the rewritten per-raw test); lint at the 18-error pre-existing baseline; new/touched files clean.

### File List

- packages/sym/src/sym/universe/projection.py (modified — provenance field, `pair_corrections`, counters, SELECT)
- packages/sym/src/sym/universe/monitor.py (modified — `_open_tokens` unified replay)
- packages/sym/tests/test_universe_correct_pairing.py (new — 8 tests)
- packages/sym/tests/test_universe_monitor_routing.py (modified — fake event rows + reverse-then-monitor test)
- docs/data-conventions.md (modified — §5 correction semantics)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D3 done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-5); suite 474 → 482 green; live ibov round-trip verified (closed → reversed → open in the log replay; monitor sees it). Status → review.
- 2026-06-10: Code review (3 adversarial layers) — 1 decision (dangling explicit correctives now DROPPED + counted, a recorded deviation from constraint 4) + 9 patches applied, 1 deferred (dedupe-key nonce → ledger), 3 dismissed. AC5 re-verified live with a resolved member (ABEV3): projection + log replay agree closed→open across the reverse, `paired_corrections=1` observed, monitor derives nothing. Auditor confirmed `members_pinned` reproducibility is not broken (one-time historical shift now documented). Suite 482 → 486 green. Status → done.
