# Story 2.5: Three-phase load orchestration and idempotent CLI

Status: review

## Story

As an operator,
I want `uv run sym backfill|delta|recompute|sweep` driven by Windows Task Scheduler,
so that loads are resumable, gap-computed, and safely re-runnable.

## Acceptance Criteria

1. **Given** a mode flag, **Then** `dev` / `backfill` (resumable, per-security progress) / `delta` (dates since last success) select at runtime; up-to-date securities are skipped in delta; an interrupted backfill resumes from the last completed security.
2. **Given** `delta`, **Then** the gap is computed from DB state, not the clock (backfill = delta with an earlier floor).
3. **Given** a 429 response, **Then** backoff + jitter (capped) is applied, then the security is marked `error` and the run continues; the cursor never advances without rows.
4. **Given** two consecutive `delta` runs, **Then** the second produces zero net mutations (idempotency invariant).

## Tasks / Subtasks

- [x] Task 1: yfinance symbol resolution (prereq for fetching across exchanges)
  - [x] `YAHOO_SUFFIX` MIC→suffix map + `make_yahoo_symbol_resolver(conn)` (ticker via symbology, share-class `.`→`-`, exchange suffix); unknown exchange → None (figi errored, never halts)
  - [x] normalize the contract's `end` to **inclusive** in the yfinance adapter (yfinance `end` is exclusive — fixes the Story 2.3 boundary gap)
  - [x] normalize minor-unit quotes (Yahoo's pence `GBp` etc.) to the major ISO currency
- [x] Task 2: orchestration in `src/sym/ingest/pipeline.py` (AC: #1–#4)
  - [x] modes `DEV` / `BACKFILL` / `DELTA`; `compute_window(mode, cursor, floor, end)` — pure; backfill from floor, delta from cursor+1, dev recent window; **up-to-date (cursor ≥ end) → skip**
  - [x] `latest_session_for(conn, mic, asof)` (end from calendar, not clock); `read_active_with_cursor`; window/end computed from **DB state** (AC #2)
  - [x] `fetch_with_retry` — capped backoff+jitter, then re-raise (AR-13 429)
  - [x] `run_load(conn, source, mode, *, asof)` — **autocommit** (per-figi durable commits); per-figi error isolation around **fetch AND ingest** → mark `error`, continue; cursor never advances without rows; `LoadSummary`
- [x] Task 3: CLI `sym backfill` / `sym delta` / `sym dev` (AC: #1)
  - [x] build the source via `config.source_key()` + the yahoo resolver; run the mode; print a summary; exit non-zero if any figi errored
- [x] Task 4: tests in `tests/test_pipeline.py` (AC: #1–#4)
  - [x] `compute_window` (backfill/delta/dev/up-to-date-skip); `fetch_with_retry` (retry then succeed / exhaust then raise, injected sleep)
  - [x] `run_load` (monkeypatched DB helpers + fake source): skips up-to-date, loads windowed, isolates a failing figi, sets autocommit, delta window from cursor not clock

## Dev Notes

- **Per-figi durability (the Story 2.4 finding):** `run_load` sets `conn.autocommit = True` so each `ingest_result`'s `conn.transaction()` is a top-level durable commit — one bad figi never rolls back earlier ones. (Non-autocommit degrades it to a savepoint; see memory.)
- **Gap from DB, not clock (AC #2):** `delta`'s window start is `cursor_date + 1` read from `pipeline_backfill_progress`; the end is the latest calendar session ≤ asof (`latest_session_for`), so an incomplete current session isn't chased. `backfill` is the same loop with an early floor.
- **Idempotency (AC #4):** a security whose cursor ≥ its latest session is skipped entirely (no fetch, no write) — so a second `delta` mutates nothing. Combined with the immutable `ON CONFLICT DO NOTHING` writes (Story 2.3), re-runs are no-ops.
- **429/errors (AC #3):** `fetch_with_retry` applies capped exponential backoff (+jitter) then re-raises; `run_load` catches per figi, marks `pipeline_backfill_progress.status = 'error'` **without advancing the cursor**, and continues.
- **Symbol resolution is vendor-specific:** the yahoo resolver lives with the yfinance adapter; EODHD's resolver arrives in Story 2.7. `recompute` (Epic 3) and `sweep` (Story 2.8) are separate stories — this one ships `backfill`/`delta`/`dev`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.5: Three-phase load orchestration and idempotent CLI]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-13 — Operational model]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest` → 99 passed (11 new pipeline tests + 1 pence test); `uv run ruff check` clean.
- Live: `sym backfill` over the active universe, then `sym delta`.

### Completion Notes List

- Modes (`dev`/`backfill`/`delta`) share one loop; the window comes from **DB state** (`pipeline_backfill_progress.cursor_date`) and the calendar (`latest_session_for`), never the clock. Up-to-date securities (cursor ≥ latest session) are skipped — so resume and the "second delta = zero mutations" invariant both fall out.
- `run_load` sets `conn.autocommit = True` so each `ingest_result` is a durable top-level commit (the Story 2.4 finding); per-figi failures are isolated and marked `error` without advancing the cursor.
- **Two live-found bugs fixed:** (1) the per-figi error isolation only wrapped the *fetch* — a constraint failure in `ingest_result` crashed the whole run; now fetch+ingest are both inside the try. (2) Yahoo quotes UK stocks in **pence (`GBp`)** → currency FK violation; the adapter now normalizes minor units (GBp/GBX/ZAc/ILA) to the major ISO currency (÷100). Also normalized the adapter's `end` to inclusive (the Story 2.3 boundary-gap finding).
- **Verified live:** `sym backfill` → 44/45 active securities loaded, **339,238 raw bars**, 3,277 dividends + 174 splits, 0 errors. The 45th (XNSE/India) is skipped — its exchange has no trading calendar. `sym delta` → `loaded=0 skipped=45 rows=0` (idempotency, AC #4). The 11 `price_jump` flags are all real (AAPL −51.9% on 2000-09-29; a financial −60.8% on 2008-09-15) — split-aware detection working.
- **Follow-up (Story 2.1 calendar coverage):** 2,634 `price_on_non_trading_day` flags, 2,444 pre-2006 — dominated by XTKS/XSHG/XBOM whose exchange_calendars only cover ~2006+. The Story 2.1 `_calendar_within_bounds` fallback uses the library's 20-year default rather than each calendar's true earliest bound; it should fall back to `bound_min` (and/or those exchanges genuinely lack pre-2006 data, in which case the flags are correct "price without calendar" signals). Not a 2.5 defect — the anomaly system is correctly reporting calendar-vs-data divergence.

### File List

- `src/sym/ingest/pipeline.py` (new) — modes, `compute_window`, `fetch_with_retry`, `run_load`, `LoadSummary`, DB helpers.
- `src/sym/sources/yfinance_adapter.py` (modified) — `YAHOO_SUFFIX` + `make_yahoo_symbol_resolver`, inclusive-`end` fix, minor-unit (pence) normalization.
- `src/sym/cli.py` (modified) — `backfill` / `delta` / `dev` subcommands.
- `tests/test_pipeline.py` (new) — 11 tests; `tests/test_sources.py` (modified) — pence normalization test.
- `_bmad-output/implementation-artifacts/2-5-load-orchestration.md` (new) — this story spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.5: dev/backfill/delta orchestration (window from DB state, autocommit per-figi durability, error isolation), yfinance symbol resolution, `backfill`/`delta`/`dev` CLI. Live-fixed two bugs (ingest error-isolation gap; GBp pence FK). Verified live: 339k bars backfilled across 44 securities, idempotent delta. Surfaced a Story 2.1 calendar-coverage follow-up. Status → review. |
