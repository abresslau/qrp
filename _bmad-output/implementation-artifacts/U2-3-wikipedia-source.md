# Story U2.3: Wikipedia index provider + revision-diff engine

Status: review

## Story

As the universe layer,
I want a Wikipedia index source with a reusable revision-diff engine,
so that I have a fallback/corroboration source and the only free ~20-year point-in-time history for the S&P 500.

## Acceptance Criteria

1. An index's Wikipedia component table is parsed → current members emitted.
2. A revision-diff engine derives dated change-events from page revisions (poll_bounded).
3. Ticker-format drift (BRK.B vs BRK-B) is normalized before diffing (no fake leave+rejoin).
4. An empty/garbled parse triggers the sanity-gate (never wipes a universe); DB-free tests cover table parse + revision-diff.

## Tasks / Subtasks

- [x] Task 1: stdlib HTML `wikitable` parser (`parse_wikitables`) — strips refs, handles th/td (AC #1)
- [x] Task 2: current-constituents extraction with real "Date added" (exact) + poll_bounded fallback; "Selected changes" table → dated join/leave (AC #1)
- [x] Task 3: reusable pure `revision_diff(snapshots)` — seed + consecutive set-diff, poll_bounded, normalized tokens (AC #2, #3)
- [x] Task 4: empty/garbled parse → loud `IndexSourceError` (AC #4)
- [x] Task 5: DB-free tests on HTML fixtures + revision-diff; live S&P 500 parse verified (AC #4)

## Dev Notes

- Two mechanisms: the **constituents table** (current members, each with its real "Date added" → exact-dated join) and the **"Selected changes" table** (dated add/remove → leavers a snapshot can't give). The reusable `revision_diff` engine handles the general "sequence of dated snapshots → events" case.
- Identifiers normalized via `ticker_token`/`normalize_ticker` before diffing — separator drift can't fake a leave+rejoin (AC #3).
- US composite FIGIs are venue-independent, so a single default MIC (XNYS) resolves any US name; per-index spec is overridable via config.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `wikipedia.py`: stdlib `_TableParser`/`parse_wikitables` (no new deps), `_constituent_changes` (exact Date-added joins, poll_bounded fallback), `_changes_table_events` (positional add/remove → dated join/leave), pure `revision_diff`, `HttpWikipediaClient` (MediaWiki `action=parse`).
- **Live-verified against en.wikipedia.org:** S&P 500 fetch parsed **864 joins (all with exact Date-added) + 358 dated leaves** = ~20y survivorship-aware PIT membership.
- 8 DB-free tests on HTML fixtures + revision-diff; ruff clean.

### File List
- `src/sym/universe/providers/wikipedia.py` (new)
- `tests/test_universe_wikipedia.py` (new)
- `_bmad-output/implementation-artifacts/U2-3-wikipedia-source.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.3: Wikipedia source (constituents + changes table) + reusable revision-diff engine. Live-verified S&P 500 (864 joins/358 leaves). 8 DB-free tests, ruff clean. |
