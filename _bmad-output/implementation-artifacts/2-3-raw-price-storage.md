# Story 2.3: Raw price and factor storage with atomic ingestion

Status: review

## Story

As the warehouse,
I want raw OHLCV and explicit corporate-action factors persisted per security with per-batch atomicity,
so that prices are reproducible and never silently filled.

## Acceptance Criteria

1. **Given** migrations, **Then** `prices_raw` (FK to securities and currency) and a factor store exist with audit timestamps; no vendor `adjusted_close` column is stored.
2. **Given** an ingestion batch, **When** it writes, **Then** all rows + cursor + status commit in one transaction per figi-batch; a failure leaves no partial writes (NFR-6).
3. **Given** a missing price on an open trading day, **Then** it is logged per security and never forward-filled (NFR-3).
4. **Given** stored raw + factors, **Then** a derived adjusted value is reproducible from them; a non-reproducible value (e.g. adjusted > unadjusted close) is flagged as a data error (NFR-2).

## Tasks / Subtasks

- [x] Task 1: `price_storage` migration (AC: #1, #2, #3)
  - [x] `prices_raw` (composite_figi + session_date PK, O/H/L/C `NUMERIC`, volume, currency FK, source, retrieved_at, audit ts); OHLC sanity CHECKs; **no adjusted-close column**
  - [x] `corporate_actions` factor store (composite_figi, ex_date, action_type split|dividend, value, currency for dividends, source); explicit factors only (AR-6)
  - [x] `pipeline_backfill_progress` per-figi cursor (cursor_date, status pending|ok|error) for atomic rows+cursor commit (NFR-6, AR-13)
  - [x] `price_gaps` (composite_figi + session_date) — open trading day with no vendor price (NFR-3); never forward-filled
  - [x] revert + verify scripts (verify asserts no adjusted-close column); `sqitch.plan` entry
- [x] Task 2: ingestion writer in `src/sym/ingest/prices.py` (AC: #1–#4)
  - [x] `validate_bar(bar)` — positive prices, high≥low, volume≥0; invalid bars flagged, not written (NFR-2 data error)
  - [x] `detect_gaps(expected_sessions, bar_dates)` — pure; open trading days with no price
  - [x] `expected_trading_days(conn, mic, start, end)` — reads current `trading_calendar`
  - [x] `ingest_result(conn, result, *, expected_sessions)` — one transaction per figi: immutable INSERTs (ON CONFLICT DO NOTHING for prices/actions/gaps), advance the cursor+status atomically; returns `IngestSummary`; `ingest_results` isolates per-figi failures
- [x] Task 3: tests in `tests/test_ingest.py` (AC: #1–#4)
  - [x] `validate_bar` (positive/ordering/volume); `detect_gaps` pure logic
  - [x] `ingest_result` against a fake conn: single transaction; prices + actions + cursor written; gaps recorded; invalid bar excluded + flagged; idempotent (ON CONFLICT DO NOTHING); no "adj" column in any SQL

## Dev Notes

- **Immutability (AR-10):** normal backfill/delta never overwrites — `prices_raw` / `corporate_actions` / `price_gaps` insert `ON CONFLICT DO NOTHING`, so a re-run is a true no-op (supports the 2.5 "second delta = zero net mutations" invariant). Source-side corrections are handled by the weekly sweep (Story 2.8), not in-place writes.
- **Atomicity (NFR-6):** `ingest_result` wraps a single `conn.transaction()` per figi — valid price rows + corporate actions + gaps + the cursor/status advance all commit together; any failure rolls the whole figi-batch back and the cursor never advances without rows (AR-13).
- **No vendor adjusted (FR-5/AR-7):** `prices_raw` stores raw OHLCV only (the yfinance adapter already un-split-adjusts to true raw in 2.2). The factor store holds explicit split/dividend records (AR-6) — adjusted prices are *derived* in Epic 3 (`v_prices_adjusted`), never stored.
- **No silent gap-fill (NFR-3):** missing prices on open trading days (from `trading_calendar`) are recorded in `price_gaps`; we never insert a synthetic/forward-filled bar.
- **NFR-2:** raw + explicit factors make adjusted reproducible by construction; basic bar validation flags corrupt vendor data here. The full "adjusted > unadjusted" reproducibility gate lives in Epic 3.
- **Pattern:** same boundary discipline — pure helpers (`validate_bar`, `detect_gaps`) unit-tested; the writer tested against a recording fake conn; live ingest is the verification. The figi→symbol resolution and orchestration (resumable backfill/delta) are Story 2.5; this story is the storage + atomic single-batch writer.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.3: Raw price and factor storage with atomic ingestion]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-7 — Three-layer returns engine] (raw + factors → derive adjusted)
- [Source: _bmad-output/planning-artifacts/epics.md#AR-13 — Operational model] (per-figi atomicity, cursor never advances without rows)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest` → 79 passed (9 new ingest tests); `uv run ruff check` clean.
- Live: deployed `price_storage`; ingested AAPL (yfinance) into `prices_raw` + `corporate_actions`.

### Completion Notes List

- Four tables in one cohesive `price_storage` migration: `prices_raw` (raw OHLCV, **no adjusted-close**, OHLC-sanity CHECKs), `corporate_actions` (explicit split/dividend factor store; dividends carry currency, splits don't), `pipeline_backfill_progress` (per-figi cursor), `price_gaps` (NFR-3).
- `ingest_result` wraps **one `conn.transaction()` per figi** (NFR-6): valid bars + actions + gaps + cursor/status commit together; failure rolls back the whole batch and the cursor never advances. History is immutable (AR-10): all inserts `ON CONFLICT DO NOTHING`, so re-runs are true no-ops.
- Invalid vendor bars are flagged (`rejected`) and excluded, never written; missing trading days are logged in `price_gaps`, never forward-filled.
- **Verified live (AAPL 2018–2024):** 1760 raw bars (2018-01-02 close $172.26 — true raw, OHLC ordering valid, USD), 1 split (4:1 2020-08-31) + 28 dividends in the factor store, cursor 2024-12-30/`ok`, 0 rejected, 1 gap. Immutable re-run → delta 0.
- **Note for Story 2.5:** the one logged gap (2024-12-31) is a real NYSE session that yfinance omitted because its `end` param is *exclusive*. Gap detection is correct; the orchestration must align the fetch window with `expected_sessions` (use an inclusive/+1-day end) so boundary days aren't mis-flagged.

### File List

- `migrations/deploy|revert|verify/price_storage.sql` (new) — prices_raw + corporate_actions + pipeline_backfill_progress + price_gaps.
- `migrations/sqitch.plan` (modified) — `price_storage` change.
- `src/sym/ingest/prices.py` (new) — `validate_bar`, `detect_gaps`, `expected_trading_days`, `ingest_result`/`ingest_results`, `IngestSummary`.
- `tests/test_ingest.py` (new) — 9 tests (DB-free).
- `_bmad-output/implementation-artifacts/2-3-raw-price-storage.md` (new) — this story spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.3: `price_storage` migration (raw OHLCV + factor store + cursor + gap log) and the atomic per-figi `ingest_result` writer (immutable ON CONFLICT DO NOTHING, NFR-2/3/6). 9 tests; verified live ingesting AAPL. Status → review. |
| 2026-06-06 | Dropped `prices_raw.retrieved_at` (redundant with created_at for live ingest; updated_at tracks re-fetch). `OhlcvResult` still carries retrieved_at in-memory. New migration `prices_raw_drop_retrieved_at`; deployed (339k rows intact). |
