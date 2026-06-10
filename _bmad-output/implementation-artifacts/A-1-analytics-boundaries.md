# Story A.1: Analytics boundaries — own prefix, owned weights reads (chunk-1 D7)

Status: done

## Story

As Andre (the operator),
I want the analytics module to live under its own URL namespace and to read portfolio weights through the portfolios package instead of raw cross-package SQL,
so that module toggles mean what they say (an analytics route can't squat in `/api/portfolios/*` while that toggle is off) and the weights schema has ONE owner.

## Background + scope decision

Chunk-1 review (2026-06-10), ledger **D7**. Verified live:

1. **Namespace squat:** the analytics router declares the full path `/api/portfolios/{pid}/analytics` — mounted whenever the ANALYTICS toggle is on, so the route exists under the portfolios namespace even with the portfolios toggle OFF.
2. **Boundary violation:** `analytics/gateway.py` SELECTs `portfolios.portfolio_weight` directly — two packages own one table's read SQL; drift between them is unguarded.
3. **Retroactive latest-weights weighting** stays PARKED with FR-15 (time-weighted returns) per the ledger's own pairing — replacing the weighting model without the returns model is churn.

**Consumer impact:** one console fetch (`analytics-panel.tsx`) uses the old path; `lib/api-types.ts` is generated-and-committed with a CI freshness check — the path change requires a types regen.

## Acceptance Criteria

1. **Own prefix:** both analytics routes live under `/api/analytics/*` (`/api/analytics/benchmarks` unchanged; portfolio metrics moves to `/api/analytics/portfolios/{pid}`); the old `/api/portfolios/{pid}/analytics` path NO LONGER EXISTS (verified by route-table test).
2. **Owned reads:** the portfolios package exports `read_latest_weights(conn, pid) -> (as_of_date | None, {figi: weight})`; the analytics gateway calls it; zero `portfolio_weight` SQL remains in the analytics package (grep-asserted).
3. **Console + types:** `analytics-panel.tsx` fetches the new path; `lib/api-types.ts` regenerated (CI freshness stays green).
4. **FR-15 pairing recorded:** the ledger's D7 entry marks parts 1-2 done and part 3 explicitly parked with FR-15.
5. **Tests + live:** route-table test (new path mounted, old path absent); `read_latest_weights` unit test; live — the console panel loads metrics through the new path; ledger updated.

## Tasks / Subtasks

- [x] Task 1: `portfolios.read_latest_weights` (module-level seam; Decimals as stored) + analytics gateway consumes it — zero `portfolio_weight` SQL left in analytics (AC: 2)
- [x] Task 2: Router prefix rework — `prefix="/api/analytics"`, metrics at `/portfolios/{pid}` (AC: 1)
- [x] Task 3: Console path + types regen (AC: 3) — caught a near-miss: the first regen ran against the STALE running API and baked the old paths; restarted, regenerated, verified the old path absent from types
- [x] Task 4: Tests + live + ledger (AC: 4, 5) — 3 new tests (route table, grep-assert, seam contract; api suite 22 → 25); live: new path 200 with REAL metrics (the seam works end-to-end), old path 404 with the O.4 envelope; D7 split recorded

## Dev Notes

### Constraints

1. **A module-level FUNCTION, not the gateway class** — `DbPortfolioGateway` requires a sym gateway for figi resolution; a weights read needs neither. Library-first: the SQL lives in the owning package, importable without class baggage.
2. **Float conversion stays at the analytics side** (portfolios returns Decimals as stored; consumers choose representation).
3. **Route rename is a breaking API change** — acceptable solely because the ONLY consumer is the one console panel (verified); regen types in the same commit.
4. **`as_of_date` canonical naming.**
5. Services running — restart the API; the Next dev server hot-reloads the panel.

### References

- [Source: deferred-work.md — chunk-1 D7; architecture-qrp.md §typed-seam rule (types regen)]
- [Source: packages/analytics/src/analytics/{router,gateway}.py; packages/portfolios/src/portfolios/gateway.py; apps/web/components/analytics-panel.tsx]

### Review Findings (code review 2026-06-10, commit 914646b — ALL RESOLVED)

- [x] [Review][Patch] Two-statement read race in the seam: a concurrent weight write between `max(as_of_date)` and the row fetch yields a partial/mismatched vector — collapse to ONE query (`WHERE as_of_date = (SELECT max(...))`) [portfolios/gateway.py:27-37]
- [x] [Review][Patch] The seam is the least-typed code in the diff: annotate `conn: psycopg.Connection` and `-> tuple[date | None, dict[str, Decimal]]` [portfolios/gateway.py:18]
- [x] [Review][Patch] Undeclared cross-package dependency: analytics imports `portfolios` but its pyproject doesn't declare it (operate→sym is the established convention); also hoist the import from inside `_portfolio_daily` to module level [packages/analytics/pyproject.toml, analytics/gateway.py:98]
- [x] [Review][Patch] The grep-test checks ONE module while AC2 claims the PACKAGE: walk every module under `packages/analytics/src` instead of `inspect.getsource(analytics.gateway)` [test_analytics_boundaries.py:378-383]
- [x] [Review][Patch] No toggle-off test for the motivating defect class: analytics disabled ⇒ zero `/api/analytics/*` routes [test_analytics_boundaries.py]
- [x] [Review][Patch] Seam contract test never verifies `portfolio_id` reaches the SQL params — the fake ignores `params`; a hard-coded pid would pass [test_analytics_boundaries.py:399-404]
- [x] [Review][Patch] Nonexistent portfolio and weightless portfolio are indistinguishable — router 200s on garbage pids: add `portfolios.gateway.portfolio_exists` seam + 404 in the analytics router (existing-but-weightless keeps the 200-empty) [analytics/router.py:72]
- [x] [Review][Patch] Console fetch parses error responses as success — no `r.ok` check, so a 404/422/500 envelope is stored as `Analytics`; worst pairing with a breaking rename [analytics-panel.tsx:53-55]
- [x] [Review][Patch] OVERNIGHT.md still documents the OLD path (`/api/portfolios/{id}/analytics`) — the operator doc now describes a 404 [OVERNIGHT.md:142]
- [x] [Review][Defer] Types freshness is not an enforced gate: O.2's surface sat stale in the committed types until this regen caught it up — the "CI check" is a script with no runner [process] — deferred, pre-existing
- [x] [Review][Defer] NUMERIC NaN weight would slip the `total_w <= 0` guard (NaN comparisons are False) — no writer produces NaN today [analytics/gateway.py:103-106] — deferred, pre-existing
- Dismissed (5): conn-passing through the seam (the recorded design — connection topology is restructure-paired work); "DB-free" docstring (accurate — `create_app()` builds no DB connection; sibling test files do the same); no `__init__` re-export (docstring-only `__init__` is the repo convention; the module path IS the export); the call-site comment (it explicitly states seam ownership; "here" contrasts databases, accurately); unbounded `limit` on operate history (false positive — `Query(ge=1, le=500)`).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- Types-regen ordering hazard: `gen:types` reads the RUNNING API's openapi.json — regenerating before restarting baked the old paths into the committed types; caught by grepping the output, fixed by restart-then-regen.

### Completion Notes List

- The seam is a module-level FUNCTION (constraint 1): `DbPortfolioGateway` needs a sym gateway for figi resolution; a weights read needs neither. The `portfolio_weight` SQL now has exactly one owner.
- Float conversion stays analytics-side (the seam returns Decimals as stored).
- The route rename was breaking-by-design: the only consumer was the one console panel (verified by grep), updated in the same commit with regenerated types.
- Part 3 (effective-dated weighting) parked with FR-15 per the ledger's own pairing.

### File List

- packages/portfolios/src/portfolios/gateway.py (modified — read_latest_weights seam)
- packages/analytics/src/analytics/gateway.py (modified — consumes the seam)
- packages/analytics/src/analytics/router.py (modified — own prefix)
- apps/web/components/analytics-panel.tsx (modified — new path)
- apps/web/lib/api-types.ts (regenerated)
- services/api/tests/test_analytics_boundaries.py (new — 3 tests; review round: rewritten, 6 tests)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D7 split + review defers)
- packages/analytics/pyproject.toml (review round — portfolios dependency declared)
- packages/analytics/src/analytics/router.py (review round — LookupError → 404)
- OVERNIGHT.md (review round — endpoint doc updated to the new path)
- uv.lock (review round — analytics→portfolios edge)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-4); api suite 22 → 25 green; live verified both directions (new path 200 w/ real metrics, old path 404). Status → review.
- 2026-06-10: Code review (3 adversarial layers) — 9 patches applied (seam hardened: single-query read + full types + `portfolio_exists`; declared dependency + hoisted import; nonexistent portfolio now 404 LIVE-VERIFIED with the envelope while weightless stays 200-warning; console guards `r.ok`; package-wide grep-test, toggle-off test, params-asserting fake; OVERNIGHT.md path fixed), 2 deferred (types-freshness gate, NaN hypothetical), 5 dismissed (incl. 2 false positives). api suite 25 → 28; sym 544, operate 14, lint clean. Status → done.
