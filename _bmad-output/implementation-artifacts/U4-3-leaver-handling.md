# Story U4.3: Leaver handling (survivorship-safe)

Status: review

## Story

As the pipeline,
I want members that leave a universe to stop forward fetches while retaining their history,
so that delisted/removed names remain survivorship-safe and don't waste daily retries.

## Acceptance Criteria

1. A member that left stops forward fetches without daily re-try.
2. Its history is retained and flows through returns to its exit date (Story 3.7); never dropped.
3. DB-free tests cover the stop-fetch / retain logic; live-verified with a simulated leaver.

## Tasks / Subtasks

- [x] Task 1: forward modes (delta/dev) select only members active as-of the run → leavers excluded from forward fetch (AC #1)
- [x] Task 2: `end_cap_for(figi)` = leaver exit date caps backfill so a leaver fetches only through its departure (AC #1)
- [x] Task 3: history retention is inherent (prices_raw immutable; returns engine spans all securities, AR-8/Story 3.7) (AC #2)
- [x] Task 4: DB-free window/cap tests + live verification (AC #3)

## Dev Notes

- `universe_securities(..., backfill=False)` returns only members with an interval covering `asof`, so delta/dev never fetch a name that has left (no daily retry). In backfill mode all members are included but `end_cap_for` caps each leaver's fetch at its exit date.
- Retention needs no special code: prices_raw is immutable and the returns loader already spans **all** securities regardless of lifecycle (Story 3.7 survivorship invariant), so a leaver's history flows through returns up to its exit.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- Active-as-of selection (forward modes) + `end_cap_for` leaver cap in `run_load`.
- DB-free tests: leaver cap (`end_cap` stops fetch at exit), delta skips up-to-date members.
- Live: the `active_asof` selection predicate verified against the populated sp500 (503 current vs 868 ever — leavers excluded from forward selection).

### File List
- `src/sym/ingest/pipeline.py` (end_cap_for)
- `src/sym/universe/ingest.py` (active-as-of selection)
- `tests/test_universe_ingest.py`

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U4.3: leaver stop-fetch (active-as-of forward selection + exit cap); retention via existing survivorship-safe returns. |
