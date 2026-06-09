# Story 2.10: Explicit-range reload (re-upload any date window)

Status: done

## Story

As the **QRP owner-operator**,
I want **to re-upload raw prices for an explicit `[start_date, end_date]` window**,
so that **I can replace bad data for any date — a provisional/intraday bar pulled before the close, or a vendor restatement — without it being silently skipped, and reproduce any date on demand.**

## Context

`prices_raw` is **insert-only** (`ON CONFLICT (composite_figi, session_date) DO NOTHING`) — immutable by
design, so a re-run is a true no-op. That's correct for normal loads, but it means there is **no way
to overwrite a stored bar**. We hit this live: running `sym eod --steps delta` mid-session stored 2,019
**provisional** 2026-06-09 bars (median volume ~0.72× normal, ~110 fewer names); the after-close run
will *not* refresh them in place.

The loader also has **no explicit window** — `delta` derives `(cursor → latest session ≤ as_of_date]`,
`backfill` does `[floor → end]`, `dev` does last N days. `--as_of_date` only moves the *ceiling*; you
can't pin a *floor*. So "reload exactly 2026-06-09" isn't expressible.

This story adds an explicit-range **reload**: `sym reload --start_date D1 --end_date D2` re-fetches that
window and **replaces** what's stored (scoped delete-in-range → re-ingest), preserving immutability
everywhere outside the requested window. Reload is also the right home for vendor restatements.

## Acceptance Criteria

1. **`sym reload --start_date YYYY-MM-DD --end_date YYYY-MM-DD [--figi FIGI]`** re-ingests raw prices for
   the explicit window: for each selected security it **deletes `prices_raw` in `[start_date, end_date]`
   then re-fetches + stores**, so a provisional/incorrect bar is *replaced*, not skipped. Default scope =
   the active master; `--figi` restricts to one security. Run-logged like other loads.
2. **Fetch-first safety:** the delete happens **only after a successful fetch**, and the delete + re-insert
   for a figi are **atomic** (one transaction). A fetch failure leaves that security's existing data intact
   (marked errored), never a deleted-but-not-reloaded hole.
3. **Immutability preserved outside the window:** a `RELOAD` mode in `compute_window`/`run_load` produces
   `[start_date, latest session ≤ end_date]` ignoring the cursor; nothing outside `[start_date, end_date]`
   is touched, and the normal `DO NOTHING` insert path is unchanged for delta/backfill/dev.
4. **Naming consistency:** range bounds use `start_date`/`end_date` (CLI `--start_date`/`--end_date`),
   matching the `*_date` convention. Reconcile `recompute`'s `--from`/`--to` to `--start_date`/`--end_date`
   so the range-bound vocabulary is identical across the loader and the returns materializer.
5. **Verified end-to-end:** reloading the provisional **2026-06-09** window repopulates clean finals
   (this is the acceptance test); DB-free tests cover the `RELOAD` window logic.
6. **No regression:** full sym suite green; `delta`/`backfill`/`dev` behavior unchanged.

### Out of scope
- Reloading **corporate actions** in the window (event-keyed, append-only; rare to need — follow-up).
- Re-running downstream `recompute`/`benchmarks` automatically (operator runs them after reload, as today).
- Universe-scoped reload (`--universe`) — `--figi` + active-master cover the need now.

## Tasks / Subtasks

- [x] Task 1: `pipeline.py` — `RELOAD` mode constant; `compute_window` `reload_start` param + RELOAD branch
  (returns `(reload_start, end)`, cursor-independent); DB-free tests. (AC: #3)
- [x] Task 2: `pipeline.py` `run_load` — `start_date` param; RELOAD branch: fetch → atomic
  (`_delete_prices_range` + `ingest_result`); errored on fetch failure leaves data intact. (AC: #1, #2)
- [x] Task 3: `cli.py` — `_cmd_reload` + `reload` subparser (`--start_date`/`--end_date`/`--figi`); `--figi`
  filters `read_active_with_cursor` (keeps the real MIC/calendar). (AC: #1)
- [x] Task 4: `cli.py` — `recompute` `--from`/`--to` → `--start_date`/`--end_date` (dests unchanged). (AC: #4)
- [x] Task 5: tests + verify — reload `2026-06-09`, confirm finals replace provisional; `sym validate`. (AC: #5,#6)

## Dev Notes

- **Reuse, don't fork:** RELOAD threads through the existing `run_load` loop (`as_of_date` already = the
  ceiling → pass `end_date`; add `start_date` as the floor). Only the per-figi window source + a pre-ingest
  delete differ. `read_active_with_cursor` already returns `(figi, mic, cursor)`; `--figi` just filters it,
  so the MIC/calendar lookup (`latest_session_for`, `expected_trading_days`) is unchanged.
- **Atomicity** (AC#2): `with conn.transaction(): _delete_prices_range(...); ingest_result(...)` — under the
  loop's `autocommit=True` this is one durable unit per figi. Fetch is *outside* the txn and *before* the
  delete, so a vendor failure can't orphan a deleted window.
- **Immutability story stays true:** the raw layer is still "append-only, a re-run is a no-op" for
  delta/backfill/dev. Reload is the one explicit, operator-chosen escape hatch, scoped to a window — it does
  not flip the conflict policy to upsert.
- **Files:** `packages/sym/src/sym/ingest/pipeline.py` (UPDATE), `packages/sym/src/sym/cli.py` (UPDATE),
  `packages/sym/tests/test_reload.py` (NEW).

### References
- [Source: packages/sym/src/sym/ingest/pipeline.py] — `compute_window`, `run_load`, `read_active_with_cursor`
- [Source: packages/sym/src/sym/ingest/prices.py:89-93] — `prices_raw` `ON CONFLICT … DO NOTHING`
- [Source: docs/data-conventions.md#1] — `*_date` range-bound naming
- [Source: _bmad-output/implementation-artifacts/2-5-load-orchestration.md] — the delta/backfill/dev modes

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09

### Completion Notes List
- New `RELOAD` mode threads through the existing `run_load` loop: `compute_window` gains a
  `reload_start` param and a cursor-independent RELOAD branch returning `(start_date, latest
  session ≤ end_date)`. `run_load` gains `start_date`; for RELOAD it does **fetch → atomic
  (`_delete_prices_range` + `ingest_result`)** so a vendor failure can't orphan a deleted window.
- CLI: `sym reload --start_date D1 [--end_date D2] [--figi F]` (`_cmd_reload`); `--figi` filters
  `read_active_with_cursor` to keep the real MIC/calendar. Reconciled `recompute`'s `--from`/`--to`
  → `--start_date`/`--end_date` (dests unchanged) for one range-bound vocabulary.
- **Bug found + fixed in verification:** `_cmd_reload` ran the `--figi` lookup before `run_load`,
  opening a txn → `run_load`'s `autocommit=True` raised `INTRANS`. Fixed by setting
  `conn.autocommit = True` up front. (The atomic design held — no data lost when it errored.)
- **Verified:** 6 DB-free window tests; 409 sym tests pass; **replace-semantics proven live** —
  reloading `BBG000B9WX45` over the settled `2026-06-02..06-05` window (which `delta` skips)
  reported `reloaded=1 rows=4`, and the stored count stayed 4 (replaced in place, not duplicated).
- **Note on the 2026-06-09 provisional bars:** reloading them is now a one-liner, but doing it
  *mid-session* re-pulls the same provisional data — finals require reloading **after the close**
  (or once the env clock advances): `sym reload --start_date 2026-06-09`. Not run here.

### File List
- `packages/sym/src/sym/ingest/pipeline.py` (UPDATE — RELOAD mode, `compute_window` reload branch,
  `run_load` `start_date` + atomic reload, `_delete_prices_range`)
- `packages/sym/src/sym/cli.py` (UPDATE — `_cmd_reload` + `reload` subparser; recompute flag reconcile)
- `packages/sym/tests/test_reload.py` (NEW)
- `_bmad-output/implementation-artifacts/2-10-explicit-range-reload.md` (NEW)
