# Story 2.4: Anomaly annotation at ingestion (prices_review)

Status: review

## Story

As a data steward,
I want suspect prices annotated at ingestion without halting the pipeline,
so that legitimate large moves are preserved and suspect ones are queued for review.

## Acceptance Criteria

1. **Given** an ingested price, **When** a single-day move exceeds ±50%, **Then** a `prices_review` flag is written (idempotent UPSERT on (figi, date)) while the price still lands in `prices_raw` and ingestion continues (NFR-1 annotate half).
2. **Given** a data point that diverges from the trading calendar (a price on a non-trading day, or missing on a trading day), **Then** a `prices_review` flag records the divergence (AR-9).
3. **Given** a flagged price, **Then** it is recorded and annotated, never discarded; confirming a legitimate large move is a review action, not an ingestion-time drop.

## Tasks / Subtasks

- [x] Task 1: `prices_review` migration (AC: #1, #2, #3)
  - [x] table keyed (composite_figi, session_date) with `flag_type`, `detail`, `pct_move`, `source`, `reviewed`, `resolution`, `reviewed_at`, audit ts
  - [x] FK to `prices_raw` (a flag annotates a price that DID land) + securities; CHECKs (flag_type domain, reviewed⇔resolution); `set_updated_at` trigger
  - [x] revert + verify; `sqitch.plan` entry (requires `price_storage`)
- [x] Task 2: anomaly detection in `src/sym/ingest/anomaly.py` (AC: #1, #2)
  - [x] `detect_anomalies(bars, splits, expected_sessions)` — pure; **split-aware** ±50% single-day move on split-ADJUSTED prices (so a corporate-action drop is NOT a false flag), plus prices on non-trading days; one merged flag per date
  - [x] `PriceFlag`, constants (`PRICE_JUMP`, `PRICE_ON_NON_TRADING_DAY`, `JUMP_THRESHOLD = 0.50`)
- [x] Task 3: wire annotation into `ingest_result` + a review action (AC: #1, #3)
  - [x] within the existing per-figi transaction, UPSERT flags into `prices_review` (idempotent; never clobber a human-reviewed row); price still lands, ingestion never halts
  - [x] `resolve_review(conn, figi, date, *, resolution)` — confirming/rejecting is a review action, not an ingestion drop
- [x] Task 4: tests in `tests/test_anomaly.py` (AC: #1, #2, #3)
  - [x] split-adjusted jump caught; a pure split drop (e.g. 4:1) NOT flagged (no false positive); non-trading-day price flagged
  - [x] `ingest_result` UPSERTs the flag while the price row is still written; idempotent; reviewed row not clobbered

## Dev Notes

- **Two-stage anomaly (AR-9), annotate half only:** this story writes the flags; the *gate* (excluding unreviewed-flag rows from `fact_returns` recompute) is Epic 3 / Story 3.6. The flag carries `reviewed`/`resolution` so the gate can read it.
- **Split-aware jump detection (critical):** we store TRUE raw prices, so a 4:1 split is a real −75% raw move. Detecting on raw prices would false-flag every split. So the ±50% check runs on **split-adjusted** prices (`close / cumulative_split_factor`), using the explicit splits from the same `OhlcvResult` — a genuine bad tick is caught, a corporate action is not.
- **Annotate, never discard (NFR-1):** the suspect price still lands in `prices_raw` (Story 2.3); the flag is written in the **same per-figi transaction**, so price + annotation are atomic. Ingestion never halts on a flag.
- **Calendar divergence reconciliation (AR-9):** "price on a non-trading day" → a `prices_review` flag (a present-but-suspect price). The other direction — "missing on a trading day" — is already the `price_gaps` log from Story 2.3 (a flag would have no price row to reference and nothing for the gate to exclude). So `prices_review` covers present suspect prices; `price_gaps` covers absent ones — together they are the two-stage annotate surface.
- **Within-batch scope:** jump detection compares consecutive bars within the ingested batch (backfill ingests full history, so they're contiguous). Cross-batch detection on a `delta` (first new bar vs the last stored close) is a Story 2.5 orchestration concern.
- **Idempotent UPSERT:** flag write is `ON CONFLICT (composite_figi, session_date) DO UPDATE … WHERE NOT reviewed`, so re-runs are stable and a human review is never overwritten.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 2.4: Anomaly annotation at ingestion (prices_review)]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-9 — D2 two-stage anomaly]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-1 — Anomaly gating (two-stage)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest` → 87 passed (8 new anomaly tests); `uv run ruff check` clean.
- Live: deployed `prices_review`; ingested AAPL/NVDA/TSLA/AVGO (6 real splits) — 0 false flags.

### Completion Notes List

- `prices_review` keyed (composite_figi, session_date), FK to `prices_raw` (a flag annotates a price that landed), `reviewed`/`resolution` columns for the Epic 3 gate. Idempotent UPSERT `… WHERE NOT reviewed` so a human review is never overwritten.
- **Split-aware jump detection** is the crux: since sym stores TRUE raw prices, a 4:1 split is a real −75% raw move. `detect_anomalies` checks the ±50% threshold on **split-adjusted** prices (`close / cumulative_split_factor`), so corporate actions don't false-flag. Verified live: 4 names, 6 real splits (NVDA 2, TSLA 2, AAPL 1, AVGO 1), **0 false jump flags**.
- Annotate-not-discard (NFR-1): the suspect price still lands in `prices_raw`; the flag is written in the same per-figi transaction. `resolve_review` confirms/rejects (a review action, never an ingestion drop).
- Calendar-divergence reconciliation: "price on a non-trading day" → `prices_review`; "missing on a trading day" is the `price_gaps` log from Story 2.3 (no row to reference / gate).
- **Finding for Story 2.5 (recorded in memory):** per-figi *durable* commits require `conn.autocommit = True`, otherwise a prior SELECT opens a connection-level transaction and each `conn.transaction()` degrades to a savepoint — a later error then rolls back earlier figis. The backfill/delta orchestration must set autocommit. (Verified: a non-autocommit multi-name ingest with a trailing error lost all writes; autocommit persisted 9,305 rows.)

### File List

- `migrations/deploy|revert|verify/prices_review.sql` (new) — stage-1 anomaly flag table.
- `migrations/sqitch.plan` (modified) — `prices_review` change.
- `src/sym/ingest/anomaly.py` (new) — `detect_anomalies` (split-aware), `PriceFlag`, constants.
- `src/sym/ingest/prices.py` (modified) — annotation wired into `ingest_result` (same transaction); `resolve_review`; `IngestSummary.flags`.
- `tests/test_anomaly.py` (new) — 8 tests (DB-free).
- `_bmad-output/implementation-artifacts/2-4-anomaly-annotation.md` (new) — this story spec.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Implemented Story 2.4: `prices_review` stage-1 anomaly annotation (split-aware ±50% jumps + non-trading-day prices), wired into the atomic `ingest_result`; `resolve_review` action. 8 tests; verified live (6 splits, 0 false flags). Surfaced the autocommit/per-figi-durability finding for 2.5. Status → review. |
