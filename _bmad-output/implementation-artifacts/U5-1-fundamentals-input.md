# Story U5.1: Minimal fundamentals input (market cap / shares outstanding)

Status: review

## Story

As the universe layer,
I want a minimal fundamentals input populating market cap and shares outstanding,
so that rules-based screens have the reference data sym does not yet store.

## Acceptance Criteria

1. A small fundamentals source (FMP/yfinance, US-first, throttled) populates a fundamentals table with market cap + shares outstanding (ADV derivable from stored EOD volume×price), provenance-tagged.
2. A name with missing fundamentals is flagged, never faked.
3. DB-free tests cover parsing/normalization with a fake client; free-tier coverage limits (US-first) documented.

## Tasks / Subtasks

- [x] Task 1: `fundamentals` migration (effective-dated snapshot; deployed + verified) (AC #1)
- [x] Task 2: `FundamentalsSource` Protocol + `YFinanceFundamentalsSource` (throttled, US-first) (AC #1)
- [x] Task 3: `load_fundamentals` — upsert; missing values NULL + flagged in detail (never faked) (AC #2)
- [x] Task 4: CLI `fundamentals --universe`; DB-free tests + live verification (AC #3)

## Dev Notes

- `fundamentals` is an effective-dated snapshot `(composite_figi, as_of)` of market cap + shares outstanding; ADV is intentionally not stored (derivable from `prices_raw` volume×price).
- The source is behind a fakeable Protocol; the yfinance implementation throttles and treats vendor flakiness/missing fields as a flagged gap (NULL + `detail`), never a fabricated value (AC #2). Free-tier reality: yfinance fundamentals are strongest for US names; non-US coverage is partial — the gap is visible via the flagged rows.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `fundamentals` migration deployed (Docker sqitch) + verified.
- `fundamentals.py`: `Fundamental`, `FundamentalsSource` Protocol, `YFinanceFundamentalsSource` (throttled), `load_fundamentals` (gaps flagged not faked), `resolved_member_figis`.
- CLI `sym fundamentals --universe <id> [--asof --limit]`.
- **Live-verified:** `sym fundamentals --universe sp500 --limit 3` → 3 loaded, 0 gaps; real market caps from yfinance (e.g. $4.5T mega-cap with 14.7B shares). Missing-symbol path returns a flagged gap, not a fake.
- 3 DB-free tests; full suite 275 pass; ruff clean.

### File List
- `migrations/deploy|revert|verify/fundamentals.sql` (new); `migrations/sqitch.plan`
- `src/sym/universe/fundamentals.py` (new)
- `src/sym/cli.py` (fundamentals command)
- `tests/test_universe_fundamentals.py` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U5.1: fundamentals table + throttled yfinance source + loader (gaps flagged, not faked). Live-verified. |
| 2026-06-07 | Refinement (per review): renamed `as_of` → `effective_date` (consistent with the SCD/membership convention; avoids the bare-`date` reserved-word footgun) and redesigned to a **historical series** — shares outstanding over time via yfinance `get_shares_full`, market cap = close × shares-as-of at each change-point, populated for all universe members; gaps flagged. Criteria screen (U5.2) recomputes point-in-time market cap (`close(≤date) × shares(≤date)`) so it is never stale. |
| 2026-06-07 | Per operator preference: renamed `effective_date` → `date`. (`date` is a non-reserved keyword in PostgreSQL — a legal, unambiguous column identifier; quoted as `"date"` in SQL for explicitness.) Column is now `fundamentals.date`. |
