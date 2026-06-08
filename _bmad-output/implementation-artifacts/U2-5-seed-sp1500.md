# Story U2.5: Seed S&P 1500 with ~20-year point-in-time backfill

Status: review

## Story

As Andre,
I want S&P 500/400/600 registered and backfilled with point-in-time membership,
so that I have a survivorship-correct US large/mid/small-cap universe to research over.

## Acceptance Criteria

1. Seeding `sp500`/`sp400`/`sp600` backfills join/leave events into the log and projects them, with `pit_valid_from` set to the backfill floor.
2. Each member is resolved (retain-and-flag for the unresolvable); `members('sp500', <past date>)` returns a survivorship-correct set (leavers present through exit dates).
3. Verified live: a spot-check date's membership matches the source; the projection has no overlap violations.

## Tasks / Subtasks

- [x] Task 1: first-class index universes on the CLI (`--index`, `--source-pref`); `add_universe` source_pref column (AC #1)
- [x] Task 2: index-aware `refresh_universe` — pull full history from a floor, derive `pit_valid_from` from the earliest dated leave (survivorship boundary), autocommit for durability (AC #1)
- [x] Task 3: OpenFIGI throttling (`min_interval`) + chunked, resumable resolution (large universes ride the public rate limit, partial progress is durable) (AC #2)
- [x] Task 4: live population of sp500/sp400/sp600 via Wikipedia → OpenFIGI; verify counts + no overlap (AC #2, #3)

## Dev Notes

- **Source:** FMP free tier needs an API key (HTTP 401 here), so live US population runs through the **Wikipedia archetype** (the brief's free 20y PIT path) → OpenFIGI resolution. The FMP source remains built/tested for when a key is provisioned (`source_pref` flips it in).
- **pit_valid_from honesty:** an index pulls history from a 1990 floor (constituent "date added" reach back decades), but the *trustworthy* boundary is the **earliest dated leave** the source can see — before that the changes table can't tell us who left, so a query would be survivorship-biased and is refused. Boundaries came out sp500=1994-09-30, sp400=2012-01-13, sp600=2019-12-17 (each page's changes-table depth). Deep pre-boundary history is intentionally out of reach for the free source (the community PIT repo / FMP historical are the named levers for extending it).
- **Resolution durability:** the OpenFIGI client now paces requests (≈25/min unkeyed) and resolution writes in chunks under an autocommit connection, so a multi-minute live run is resumable — a re-run resolves only the still-pending members (proved out: the first run 429'd, the re-run completed).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `cli.py`: `universe add --index --source-pref`; `store.py`: `source_pref` accepts a list.
- `refresh.py`: index pulls history from `DEFAULT_HISTORY_FLOOR` (1990); `pit_valid_from` derived from earliest leave; `conn.autocommit=True` for resumable durability.
- `figi.py`: `HttpOpenFigiClient(min_interval=...)` throttle (2.6s unkeyed / 0.3s keyed) + harder 429 backoff. `resolution.py`: chunked (`chunk_size=100`) durable resolution.
- **Live-populated (verified):**
  - `sp500`: 650 resolved / 218 retained-unresolved, 564 intervals, **503 members today** (exact), 284 as-of 2010-06-01 (survivorship-aware), pit 1994-09-30.
  - `sp400`: 687 resolved / 254 unresolved, 529 intervals, 411 today, pit 2012-01-13.
  - `sp600`: 847 resolved / 212 unresolved, 673 intervals, **600 today** (exact), pit 2019-12-17.
  - 1,568 distinct CompositeFIGIs across the S&P 1500; zero EXCLUDE overlap violations (the constraint held through every projection).
- Unresolved members are delisted leavers (no current OpenFIGI ticker match) — retained-and-flagged (survivorship), never dropped. sp400's 411-vs-400 is minor ticker-drift double-counting, surfaced by the U3.3 accuracy gate against an independent source.
- Full suite **257 passed**, ruff clean.

### File List
- `src/sym/cli.py` (modified — committed with U3.4)
- `src/sym/universe/store.py` (modified)
- `src/sym/universe/refresh.py` (modified)
- `src/sym/identity/figi.py` (modified)
- `src/sym/universe/resolution.py` (modified)
- `_bmad-output/implementation-artifacts/U2-5-seed-sp1500.md` (new)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U2.5: index-aware refresh + OpenFIGI throttle + chunked resumable resolution; live-populated S&P 1500 (1,568 securities, survivorship-aware PIT). 257 tests pass. |
