# Story U2.1: Open-finance-API index provider (FMP)

Status: review

## Story

As the universe layer,
I want an open-finance-API index source that reads FMP's current and historical constituents,
so that US flagship indexes are sourced from a dated, structured feed rather than scraping.

## Acceptance Criteria

1. Fetching S&P 500 / Nasdaq-100 / Dow Jones emits current-membership join events and historical add/remove events (historical dated `exact`).
2. FMP's bare US tickers are normalized to ticker+MIC for resolution.
3. An orphan leave event (removal with no prior add in-window) is tolerated, never crashing projection.
4. The provider verifies returned counts (no silent partial fetch) and budgets calls.
5. DB-free tests use a fake FMP client; the live free-tier endpoint is verified before relying on it.

## Tasks / Subtasks

- [x] Task 1: archetype framework — `index_source.py` (`IndexSource` Protocol, `IndexSourceError`, archetype-keyed registry) shared by all U2 sources (AC #1)
- [x] Task 2: shared `membership_diff.py` — token builders (`ticker_token`/`isin_token` + `normalize_ticker`) and pure `diff_identifier_sets` (set-diff, never weights) (AC #2)
- [x] Task 3: `fmp.py` — `FmpClient` Protocol + `HttpFmpClient` (loud `IndexSourceError`), `FmpIndexSource` deriving current (poll_bounded) + historical (exact) join/leave; MIC normalization; empty-current = error (AC #1–#4)
- [x] Task 4: DB-free tests (`test_universe_fmp.py`, `test_membership_diff.py`) with a fake client (AC #5)

## Dev Notes

- **Archetype, not one-per-index (FR3):** all three U2 sources implement the `IndexSource` Protocol (`fetch(index_key, start, end) -> list[MembershipChange]`); a single `IndexProvider` (U2.4) selects between them per-index. The archetype registry mirrors the kind-keyed provider registry.
- **FMP free tier:** requires `FMP_API_KEY`; US-only; the historical-constituent endpoint may be gated — `fetch` tolerates a missing history (falls back to current-only) but treats an empty *current* snapshot as an `IndexSourceError` (never "the index is empty").
- **Orphan leave (AC #3):** a `leave` with no open interval is a no-op in the projection state machine (U1.4) — verified there; the source emits it regardless.
- **Live note:** FMP returned HTTP 401 for the demo key in this environment (no key available), so the live free-tier check is deferred to when a key is provisioned; Wikipedia is the live US source used for population (U2.5).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `index_source.py`: `IndexSource` Protocol + `IndexSourceError`/`UnknownArchetypeError` + archetype-keyed registry (`register_index_source`/`get_index_source`).
- `membership_diff.py`: `normalize_ticker` (unifies `-`/`.`/space → `.`), `ticker_token`/`isin_token`, and `diff_identifier_sets` (set-diff into join/leave, poll_bounded) — shared by ETF/Wikipedia snapshot sources and the U3 monitor.
- `fmp.py`: `FmpIndexSource` over a fakeable `FmpClient`; current → poll_bounded joins, historical → exact dated join/leave; MIC mapping; window filtering; empty-current loud error.
- 11 DB-free tests pass; ruff clean. FMP not runnable live here (no key) — Wikipedia drives live population.

### File List
- `src/sym/universe/providers/index_source.py` (new)
- `src/sym/universe/membership_diff.py` (new)
- `src/sym/universe/providers/fmp.py` (new)
- `tests/test_universe_fmp.py` (new)
- `tests/test_membership_diff.py` (new)
- `_bmad-output/implementation-artifacts/U2-1-fmp-index-source.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.1: FMP index source + archetype framework + shared membership-diff helpers. 11 DB-free tests, ruff clean. |
