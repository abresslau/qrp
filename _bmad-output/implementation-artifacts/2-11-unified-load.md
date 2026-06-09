# Story 2.11: One loader — `sym load` (scope + window + replace)

Status: done

## Story

As the **QRP owner-operator**,
I want **a single `sym load` command parameterized by scope, start_date, end_date, and replace**,
so that **there's one obvious way to load or re-upload prices — no confusing `delta`/`backfill`/`reload`/`dev` verbs to remember — and "re-upload any date" is just a flag.**

## Context

The loader had grown four verbs (`delta`, `backfill`, `dev`, `reload`) that were really one
operation with different window/overwrite policies. Andre: *"why is there this confusion with load
and reload — it should just be called load"* and *"what is this mode `dev`"*. Collapse them into one
command whose knobs are the real variables: **scope** (which securities), **start_date** / **end_date**
(the window), and **--replace** (overwrite vs append). `dev` (a smoke-test "last 30 days" mode) is
removed — a smoke run is just `load --limit N`.

## Acceptance Criteria

1. **One command:** `sym load --scope <all|universe:ID|figi:FIGI> [--start_date D1] [--end_date D2]
   [--replace] [--limit N]`. `delta`/`backfill`/`dev`/`reload` are removed.
2. **Flag → behavior** (via the pure `plan_load`): no `--start_date` → incremental from each cursor
   (was `delta`); `--start_date` (append) → gap-aware fill of the window (was `backfill`); `--replace`
   → overwrite the window (was `reload`, with the empty-fetch guard). `--replace` requires
   `--start_date`.
3. **Scope:** `all` = active master; `figi:` = one security; `universe:` routes to
   `run_universe_load`. Default `all`.
4. **`dev` mode gone:** the `DEV` mode/branch + `dev_days` removed from `compute_window`/`run_load`;
   `dev_limit` generalized to `--limit` (cap securities, any load).
5. **Replace ergonomics:** after a `--replace`, print a reminder to re-run `sym recompute` and that
   only prices (not corporate actions) were replaced. (Folds in 2-10 review items F3/F4.)
6. **No regression:** EOD still runs the internal `delta` mode; the Dagster `prices_raw` asset now
   materializes via `sym load`; docs updated. Full sym suite green.

### Out of scope
- Re-running `recompute`/`benchmarks` automatically after a replace (operator runs it; reminder added).
- Corporate-action reload (prices only) — unchanged from 2-10.

## Tasks / Subtasks
- [x] `pipeline.py`: remove `DEV`/`DEV_DAYS`/`dev_days`; `dev_limit`→`limit`; add pure `plan_load`.
- [x] `cli.py`: one `_cmd_load` (scope/window/replace) + `load` parser; remove `_cmd_reload`,
  `_add_load_args`, and the `delta`/`backfill`/`dev`/`reload` parsers.
- [x] Update the Dagster `prices_raw` asset (`["delta"]`→`["load"]`) + docs (runbook, universe-maintenance).
- [x] Tests: drop the DEV case; verify the suite + the live `load --replace` replace-semantics.

## Dev Notes
- Internal `run_load` modes (`DELTA`/`BACKFILL`/`RELOAD`) are retained as the window/overwrite
  *policies*; `plan_load` maps the user's flags onto them. The EOD step still calls
  `run_load(…, "delta", …)` directly — unaffected by the CLI collapse.
- `delta` = `load`; `backfill` = `load --start_date <floor>`; `reload` = `load --replace
  --start_date …`. Universe backfill: `load --scope universe:<id> --start_date <floor>`.
- Supersedes the `reload` verb from Story 2.10 (now `load --replace`); the 2-10 data-loss guard
  (skip delete on empty fetch) is on the shared RELOAD path.

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Completion Notes List
- One command verified: `load --help` shows `--scope/--start_date/--end_date/--replace/--limit`;
  `delta`/`backfill`/`dev`/`reload` all removed; `--replace` without `--start_date` rejected.
- Live: `load --replace --scope figi:BBG000B9WX45 --start_date 2026-06-02 --end_date 2026-06-05` →
  `loaded=1 rows=4` + the recompute reminder; `load --limit 1` ran a delta (already-current → skipped).
- 408 sym tests pass; `dagster definitions validate` passes; EOD delta step intact.
### File List
- `packages/sym/src/sym/ingest/pipeline.py`, `packages/sym/src/sym/cli.py`
- `packages/lineage/src/lineage/assets.py`, `docs/runbook.md`, `docs/universe-maintenance.md`
- `packages/sym/tests/test_pipeline.py`
- `_bmad-output/implementation-artifacts/2-11-unified-load.md` (this story)

## Review Findings

_Adversarial code review of commit `8993030` (Blind Hunter + Edge Case Hunter + Acceptance Auditor),
2026-06-09. The Edge Case Hunter's project access dismissed the Blind Hunter's Critical/High suspects
(the `compute_window` BACKFILL `raise` is unreachable — BACKFILL/RELOAD return before it; `floor` vs
`history_floor` routing is correct; the Story 2.10 empty-fetch data-loss guard still fires on the only
write path). 9 findings dismissed as noise/false-positive._

- [x] [Review][Patch] Universe `--replace` silently excludes exited members (leavers) — `run_universe_load(..., RELOAD)` passes `backfill=(mode==BACKFILL)`=False to `universe_securities`, so a historical-window replace re-fetches only names still in the index as-of today; survivorship-sensitive leavers in the window are silently skipped and the run still logs `success`. **Resolved (Option 1, Andre 2026-06-09): no data gaps — RELOAD must cover all point-in-time members.** Fix: select all members for RELOAD too (`backfill=(mode in (BACKFILL, RELOAD))`). Note: V1 completeness only checks current members, so this gap is invisible to `sym validate` — the load layer is the only guard. [`universe/ingest.py:157`] (HIGH)
- [x] [Review][Patch] Scope value not normalized/validated — empty (`universe:`) or whitespace-padded (`figi: BBG…`) ids silently no-op (universe) or false-miss (figi); strip the value and reject empty, symmetric with the figi "not in active master" guard [`cli.py:236-249`] (MED/LOW)
- [x] [Review][Patch] `--limit` silently caps full-scope loads with no warning — generalizing `dev_limit`→`--limit` (AC #4, intended) means a stray `--limit N` on a daily/backfill run loads only the first N names by figi and still logs `success`; emit a notice when `--limit` caps a load so it is not mistaken for a complete run [`cli.py` / `pipeline.py:292-293`] (MED)
- [x] [Review][Patch] `pipeline.py` module docstring still documents the removed `dev` mode and omits `RELOAD`/`plan_load` — contradicts AC #4 / Task 1 (doc-only) [`pipeline.py:1-16`] (LOW)
- [x] [Review][Patch] No direct unit test for the pure `plan_load` mapper (the heart of AC #2) — mapping is only exercised indirectly; add a test [`tests/test_pipeline.py`] (LOW)
