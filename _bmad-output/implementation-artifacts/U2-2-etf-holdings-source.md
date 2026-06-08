# Story U2.2: ETF-holdings index provider

Status: review

## Story

As the universe layer,
I want an ETF-holdings index source that derives membership from issuer daily-holdings files,
so that European flagships and big/gated US indexes have a least-brittle, self-archivable source.

## Acceptance Criteria

1. Non-equity rows (cash, futures, FX hedges) are dropped; only equity constituents become members.
2. Two consecutive holdings files diff on the identifier **set only, not weights**.
3. Events are tagged proxy provenance with `poll_bounded` precision.
4. An empty/garbled parse is flagged (sanity-gate hook), never applied as "all members left".
5. DB-free tests cover row-filtering + set-diff.

## Tasks / Subtasks

- [x] Task 1: `parse_equity_tokens` — filter non-equity (asset-class/sector), ISIN-preferred token (AC #1)
- [x] Task 2: `parse_holdings_csv` — skip issuer preamble, alias headers (AC #1)
- [x] Task 3: `EtfHoldingsIndexSource` — current equity members → poll_bounded joins, `etf_holdings:<etf>` proxy source; empty-parse loud error (AC #3, #4)
- [x] Task 4: set-diff reuses shared `diff_identifier_sets` (set, not weights) — covered in `test_membership_diff` (AC #2)
- [x] Task 5: DB-free tests with a fake client + a real issuer-preamble CSV fixture string (AC #5)

## Dev Notes

- Membership = the equity identifier set of the holdings file; the U3 monitor diffs consecutive snapshots via `diff_identifier_sets` (a weight change is not a membership change).
- ISIN-preferred tokens (Europe's durable identifier); ticker+MIC fallback when no ISIN.
- Empty parse → `IndexSourceError` at the source boundary; the U3 sanity-gate adds the churn-threshold half.
- Live note: per-ETF holdings URLs are config (`holdings_urls`/`etf_for_index`); not fetched live overnight (issuer files require per-issuer URL curation) — wired for U2.6 European seeding.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `etf_holdings.py`: `parse_equity_tokens` (drop cash/futures/FX, ISIN-preferred), `parse_holdings_csv` (skip issuer preamble + header aliases), `EtfHoldingsIndexSource` (poll_bounded joins, proxy source, empty-parse loud error), `HttpEtfHoldingsClient`.
- 6 DB-free tests pass (incl. a realistic issuer-preamble CSV); ruff clean.

### File List
- `src/sym/universe/providers/etf_holdings.py` (new)
- `tests/test_universe_etf_holdings.py` (new)
- `_bmad-output/implementation-artifacts/U2-2-etf-holdings-source.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.2: ETF-holdings index source (equity filter, ISIN-preferred tokens, proxy/poll_bounded, empty-parse guard). 6 DB-free tests, ruff clean. |
