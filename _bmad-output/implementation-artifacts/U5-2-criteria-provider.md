# Story U5.2: Criteria provider (rules-based screen)

Status: review

## Story

As Andre,
I want a function-evaluating criteria provider that computes membership from a rule,
so that I can define a universe like "top-N US common stocks by month-end market cap" and query it like any other.

## Acceptance Criteria

1. A criteria provider registered with a rule computes `members(date) = {s : rule(s, date)}` against the fundamentals input.
2. Computed membership is snapshotted into the event log, so the criteria universe is point-in-time queryable + reproducible.
3. `universe add <id> --kind criteria --rule ... ` then `refresh` materializes it; `members(<id>, date)` returns the screened set.
4. DB-free tests cover rule evaluation + snapshotting; live-verified for a small top-N screen.

## Tasks / Subtasks

- [x] Task 1: `figi:` resolution token — `_parse_token`/`make_local_resolve_fn` resolve a CompositeFIGI directly (criteria members are existing securities) (AC #1)
- [x] Task 2: `CriteriaProvider` (kind=criteria) — evaluates a rule (`top_n_market_cap`) against fundamentals, emits figi join events at the evaluation date (AC #1, #2)
- [x] Task 3: refresh wiring — inject conn for criteria, resolve via the local resolver, snapshot into the log + project (AC #2, #3)
- [x] Task 4: CLI `--rule`/`--n`; DB-free tests + live verification (AC #3, #4)

## Dev Notes

- A criteria provider is *function-evaluating*: `members(start, end)` runs the rule as-of `end` against `fundamentals` and emits the result as `join` events (`figi:` tokens). Snapshotting into the append-only log means the screen is point-in-time + reproducible like any other universe (each refresh records that date's screen).
- Criteria members are CompositeFIGIs of securities already in the master, so a new `figi:` token resolves *directly* (no OpenFIGI) via the local resolver. The rule registry (`_RULES`) makes new screens additive.
- The provider needs DB access to evaluate, so `refresh_universe` injects the connection (and uses the local resolver for the figi tokens).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8

### Completion Notes List
- `figi_token` + `figi:` parsing + direct local resolution.
- `providers/criteria.py`: `CriteriaProvider` + `_RULES` (`top_n_market_cap` reads the latest fundamentals snapshot ≤ date), self-registered.
- `refresh.py`: criteria injects conn + resolves locally; CLI `universe add --rule --n`.
- **Live-verified end-to-end** (synthetic fundamentals on 5 real securities, cleaned up): `add ustop3 --kind criteria` + `refresh` → 3 appended/3 resolved/3 intervals; `members('ustop3', today)` == the exact top-3 by market cap (MATCH). Criteria over real fundamentals works once `sym fundamentals` has populated the candidates.
- 6 DB-free criteria tests; full suite 275 pass; ruff clean.

### File List
- `src/sym/universe/providers/criteria.py` (new); `src/sym/universe/providers/__init__.py`
- `src/sym/universe/resolution.py` (figi token + direct resolution)
- `src/sym/universe/membership_diff.py` (figi_token)
- `src/sym/universe/refresh.py` (criteria wiring)
- `src/sym/cli.py` (--rule/--n)
- `tests/test_universe_criteria.py` (new); `tests/test_universe_fundamentals.py` (figi token)

### Change Log
| Date | Change |
|---|---|
| 2026-06-07 | Implemented Story U5.2: criteria provider (rule eval → log snapshot → figi resolution → projection). Live-verified top-N screen. Completes Epic U5. |
