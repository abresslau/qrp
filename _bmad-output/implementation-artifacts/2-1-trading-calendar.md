# Story 2.1: Trading calendar reference table

Status: review

## Story

As the returns engine,
I want exchange_calendars snapshotted into a versioned `trading_calendar` table,
so that compute reads a stable, versioned calendar rather than a live library.

## Acceptance Criteria

1. **Given** exchange_calendars 4.13.2, **When** the snapshot loader runs for the seed exchanges, **Then** `trading_calendar` holds open trading days per exchange with a `calendar_version` stamp and audit timestamps.
2. **Given** compute, **Then** the DB table (not the library) is the read source, and the calendar version is exposed for inclusion in the returns `input_hash`.
3. **Given** a re-snapshot that differs, **When** it runs, **Then** a new `calendar_version` is written without mutating prior versions.

## Tasks / Subtasks

- [x] Task 1: `trading_calendar` migration (AC: #1, #2, #3)
  - [x] `trading_calendar_version` table (per-exchange version metadata: `calendar_version` surrogate, `library_version`, `content_hash`, `session_count`, range, `is_current`, audit ts)
  - [x] `trading_calendar` table (`calendar_version` FK, `mic` FK, `session_date`); PK + `(mic, session_date)` index
  - [x] `content_hash` UNIQUE per `(mic, content_hash)` + partial-unique one `is_current` per MIC; `set_updated_at` trigger
  - [x] revert + verify scripts; `sqitch.plan` entry (requires `exchange`)
- [x] Task 2: snapshot loader in `src/sym/calendar/snapshot.py` (AC: #1, #3)
  - [x] `CalendarSource` Protocol + `ExchangeCalendarsSource` (clamps to each calendar's available range; returns `None` for a MIC the library doesn't know)
  - [x] `content_hash(library_version, sessions)` — deterministic over the ordered session list
  - [x] `plan_snapshot(source, mics, start, end, current_hashes)` — pure; classifies each MIC as `new` / `unchanged` / `unknown_mic` / `empty`
  - [x] `apply_snapshot(conn, plans)` — for `new`: flip prior `is_current` off, insert a version, COPY sessions; one transaction per MIC, error-isolated
  - [x] `snapshot_calendars(conn, source, mics, start, end)` orchestrator + `SnapshotSummary`
  - [x] read helpers: `current_calendar_version(conn, mic)`, `is_trading_day(conn, mic, day)` (DB is the read source)
- [x] Task 3: tests in `tests/test_calendar.py` (AC: #1, #2, #3)
  - [x] `content_hash` determinism + sensitivity (a changed session set → different hash)
  - [x] `plan_snapshot`: identical content → `unchanged` (idempotent); differing → `new`; unknown MIC → `unknown_mic`; no sessions → `empty`
  - [x] `apply_snapshot` against a fake conn: a `new` plan flips the prior current version off, inserts a version, and COPYs the sessions
  - [x] real-library guards: `ExchangeCalendarsSource` honours the requested 1990 start and relaxes XBOM's hard end bound
- [x] Task 4: `sym snapshot-calendar` CLI command (AC: #1)

## Dev Notes

- **Patterns:** mirror `classification/gics.py` — a `Protocol`-isolated external dependency, a pure `plan_*` step, a transactional `apply_*` with one transaction per entity and `try/except psycopg.Error` isolation, and a summary object. Migration style follows `gics_scd.sql` (CHECK constraints, partial-unique index, `set_updated_at` trigger, table/column comments).
- **Versioning model (AC #3):** `content_hash = sha256(library_version + ordered session dates)` per MIC. A re-snapshot whose hash matches the current version is a no-op; a differing hash inserts a NEW `calendar_version` and flips the prior `is_current` off — prior versions and their session rows are never mutated (immutable history, so `fact_returns` stays reproducible against the calendar it was computed under). `calendar_version` is the stable surrogate that will feed `fact_returns.input_hash` (AR-7).
- **exchange_calendars (verified):** `xcals.get_calendar(mic)` is keyed by ISO MIC; `get_calendar_names()` enumerates known calendars. Of the 35 exchange-table MICs, the library does not know all (e.g. **XNSE**); the source returns `None` for those and the loader records `unknown_mic` rather than failing. Sessions are clamped to each calendar's `first_session`/`last_session`.
- **Read source (AC #2):** `current_calendar_version` / `is_trading_day` read the DB table, never the library — the returns engine will anchor windows off these.
- **Testing standard:** DB-free unit tests with a fake `CalendarSource` and a fake connection (incl. a minimal `cursor().copy()` for the COPY path); the real bulk load is exercised in live verification, matching the suite's DB-free convention.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.1: Trading calendar reference table]
- [Source: _bmad-output/planning-artifacts/architecture.md#D3 — Trading calendar: `exchange_calendars` 4.13.2 → versioned reference table]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-4 — Trading calendar] — DB table read at compute time; version participates in `input_hash`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest` → all tests green (9 calendar tests added); `uv run ruff check` clean.
- Live: deployed `trading_calendar` via sqitch (Docker); `sym snapshot-calendar` over 35 exchanges.

### Completion Notes List

- Mirrors the `gics.py` boundary pattern: `CalendarSource` protocol + `ExchangeCalendarsSource`, pure `plan_snapshot`, transactional error-isolated `apply_snapshot`, summary object. Sessions bulk-loaded via `COPY`.
- **Versioning (AC #3):** per-MIC `content_hash = sha256(library_version + ordered sessions)`. Matching hash → no-op; differing hash → new `calendar_version` + prior `is_current` flipped off; prior version rows never mutated. Verified live: editing the snapshot window produced 31 new versions while 31 prior versions were retained as superseded (64 total).
- **Two bugs surfaced by the live run (both fixed):**
  - exchange_calendars defaults a calendar to only ~20 years (XNYS started 2006); long-window returns (10Y/20Y/30Y) need more. Fixed by passing the requested `start`/`end` to `get_calendar` — XNYS now spans 1990-01-02 → 2027-12-31.
  - XBOM has a *hard* end bound (holidays defined only to 2026); requesting 2027 raised and aborted the whole run. Fixed with `_calendar_within_bounds`, which relaxes the offending bound per-MIC instead of failing. Real-library regression tests added for both.
- **Unknown MICs** (XNSE, XSHE — not in exchange_calendars) are reported and skipped, never fatal.
- Read path (AC #2): `is_trading_day` / `current_calendar_version` read the DB table; verified `is_trading_day('XNYS', 1990-01-02)` is True and holidays are False.
- Final live state: 33 current calendar versions, 292,114 current session rows; second run idempotent (0 new, 33 unchanged).

### File List

- `src/sym/calendar/snapshot.py` (new) — snapshot source, content-hash versioning, planner, COPY writer, read helpers.
- `src/sym/cli.py` (modified) — added the `snapshot-calendar` subcommand.
- `migrations/deploy/trading_calendar.sql`, `migrations/revert/trading_calendar.sql`, `migrations/verify/trading_calendar.sql` (new) — versioned calendar schema.
- `migrations/sqitch.plan` (modified) — `trading_calendar` change (requires `exchange`).
- `tests/test_calendar.py` (new) — 9 tests (DB-free fakes + real-library bound guards).
- `_bmad-output/implementation-artifacts/2-1-trading-calendar.md` (new) — this story spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.1: versioned `trading_calendar` snapshot of exchange_calendars (content-hash versioning, immutable prior versions), `sym snapshot-calendar` CLI, 9 tests. Fixed two live-found bugs (20-year default window; XBOM hard end bound). Deployed + verified live (33 exchanges, 292k sessions). Status → review. |
| 2026-06-06 | Coverage fix (surfaced by Story 2.5): `_calendar_within_bounds` clamped to the library's 20-year default for out-of-bounds requests, so XTKS/XSHG/XBOM stopped at 2006. Now clamps to each calendar's true `bound_min`/`bound_max` → XTKS 1997, XSHG 1990-12, XBOM 1997. Re-snapshot wrote 3 new versions; cleaned up 1,744 stale `price_on_non_trading_day` flags (dates now valid sessions). Remaining ~890 flags are genuine exchange_calendars-vs-Yahoo holiday divergences. +1 regression test. |
