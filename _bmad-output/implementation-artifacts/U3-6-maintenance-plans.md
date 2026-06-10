# Story U3.6: Maintenance plans for every populated index universe (ledger D4)

Status: review

## Story

As Andre (the operator),
I want a written maintenance plan (source · monitor cadence · gating · PIT boundary) for every populated index universe, the calendar alignment those plans assume actually configured, and the populate-gate rule enforced by `sym validate`,
so that the standing rule "no universe is populated without a plan" stops being violated by 12 of the 13 universes I operate — and can't silently regress.

## Background (why this story exists)

The standing index-maintenance rule (memory + `docs/universe-maintenance.md` header) requires a plan BEFORE populating. The 2026-06-10 chunk-3 review found the S&P 500/400/600 and the 8 European index universes POPULATED WITHOUT WRITTEN PLANS — backlogged as **D4**. Investigation for this story found it is worse than documentation debt:

1. **`ibx` is populated (99 open members, pit 2026-06-08) but its doc section still says "planned, not yet populated" — and it has NEVER had a monitor run** (no liveness row at all).
2. **No universe — including documented `ibov` — has `config.calendar_mic` set.** The monitor's session-snapped `as_of_date` and exchange-calendar event alignment (U3.1) are inert everywhere; `trading_calendar` already covers all 9 needed MICs through 2027.
3. Nothing enforces the populate-gate rule — a 14th universe can be populated tomorrow with no plan and nothing fails.

## Acceptance Criteria

1. **Plans written:** `docs/universe-maintenance.md` carries a maintenance-plan section per populated index universe (sp500, sp400, sp600, dax, cac40, ftse100, ibex35, ftsemib, aex, smi, estoxx50, ibx — ibov already done), each covering the four mandatory fields: **source** (provider/archetype, source nature snapshot-vs-dated), **monitor cadence**, **gating** (live U3.5 behavior restated, corroboration posture stated honestly — all 12 are single-source wikipedia-primary with NO independent `accuracy_reference` available yet), and **PIT boundary** (sp500 1994-09-30 / sp400 2012-01-13 / sp600 2019-12-17 from the Wikipedia changes-table backfill; Europeans + ibx build-forward at inception). The stale "ibx — planned, not yet populated" section is replaced.
2. **Calendar alignment configured:** every index universe gets `config.calendar_mic` (XNYS for the S&Ps; XETR/XPAR/XLON/XMAD/XMIL/XAMS/XSWX for dax/cac40/ftse100/ibex35/ftsemib/aex/estoxx50→XETR/smi; BVMF for ibov/ibx), and the plans state it. estoxx50's pan-European membership aligns on XETR (its token MIC) — noted in its plan.
3. **ibx brought into maintenance:** at least one successful monitor run recorded for ibx (liveness no longer NULL); its plan documents the same cadence as ibov.
4. **Populate-gate enforced:** a new `sym validate` check `maintenance_plan_coverage` FAILs when a populated index universe (≥1 open member) has no `## <universe_id>` section in `docs/universe-maintenance.md`, and WARNs (not crashes) when the doc file cannot be located. Wired into `run_all` and error-isolated like every other check.
5. **Tests:** DB-free tests for the new check (covered universe passes, uncovered fails, missing doc warns, unpopulated universe ignored). Full suite green.
6. **Ledger:** D4 marked done in `deferred-work.md`.

## Tasks / Subtasks

- [x] Task 1: `maintenance_plan_coverage` validate check (AC: 4, 5)
  - [x] New `packages/sym/src/sym/validate/plans.py`: parse `## <slug>` headings from the doc; compare against populated index universes; FAIL per missing plan, WARN if doc missing; doc located relative to repo root (walk up from package for robustness), overridable via parameter for tests
  - [x] Wire into `runner.run_all`
  - [x] DB-free tests (fake conn + tmp doc file) — 5 tests
- [x] Task 2: Write the 12 plans + restate ibx (AC: 1, 2)
  - [x] Shared-mechanics section for the 11 wikipedia-sourced universes + per-universe sections with the four mandatory fields; honest corroboration posture stated once
  - [x] Stale ibx section replaced (it was populated with 99 members)
- [x] Task 3: Configure `calendar_mic` for all 13 universes (AC: 2)
  - [x] jsonb config update applied + re-queried (XNYS×3, XETR×2, XPAR, XLON, XMAD, XMIL, XAMS, XSWX, BVMF×2)
  - [x] Live ibov/ibx monitor runs exercised the calendar-backed `as_of_date` path (calendar_mic branch) successfully
- [x] Task 4: ibx first monitor run + liveness sweep (AC: 3)
  - [x] `monitor ibx` → success 0/0 (snapshot matches the 99 open members); `stale_monitors` → none
- [x] Task 5: Ledger + validate run (AC: 6)
  - [x] D4 → done; `sym validate`: `maintenance_plan_coverage` PASS (13 universes), suite overall FAIL only on pre-existing GICS/unpriced data-quality findings

## Dev Notes

### Per-universe facts (queried 2026-06-10)

| universe | open members | pit_valid_from | last live monitor | wikipedia spec MIC | calendar_mic to set |
|---|---|---|---|---|---|
| sp500 | 503 | 1994-09-30 | 2026-06-07 | XNYS | XNYS |
| sp400 | 411 | 2012-01-13 | 2026-06-07 | XNYS | XNYS |
| sp600 | 600 | 2019-12-17 | 2026-06-07 | XNYS | XNYS |
| dax | 40 | 2026-06-07 | 2026-06-07 | XETR (yahoo_suffix) | XETR |
| cac40 | 40 | 2026-06-07 | 2026-06-07 | XPAR (yahoo_suffix) | XPAR |
| ftse100 | 92 | 2026-06-07 | 2026-06-07 | XLON (yahoo_suffix) | XLON |
| ibex35 | 35 | 2026-06-07 | 2026-06-07 | XMAD (yahoo_suffix) | XMAD |
| ftsemib | 40 | 2026-06-07 | 2026-06-07 | XMIL (yahoo_suffix) | XMIL |
| aex | 25 | 2026-06-07 | 2026-06-07 | XAMS (yahoo_suffix) | XAMS |
| smi | 19 | 2026-06-07 | 2026-06-07 | XSWX (yahoo_suffix) | XSWX |
| estoxx50 | 49 | 2026-06-07 | 2026-06-07 | XETR (yahoo_suffix) | XETR |
| ibov | 78 | 2026-06-08 | 2026-06-10 | (b3) | BVMF |
| ibx | 99 | 2026-06-08 | **NEVER** | (b3) | BVMF |

`trading_calendar` current-version coverage confirmed for all 9 MICs (≥9,400 sessions each, through 2027-12-30/31). All 12 undocumented universes are `source_pref=['wikipedia']`; ibov/ibx are `['b3']`.

### Rebalance cadences (for the plans; daily monitoring regardless)

S&P 500/400/600: quarterly rebalance (Mar/Jun/Sep/Dec) + ad-hoc corporate events. DAX: quarterly review (Mar/Jun/Sep/Dec). CAC 40: quarterly (Mar/Jun/Sep/Dec). FTSE 100: quarterly (Mar/Jun/Sep/Dec). FTSE MIB: quarterly. IBEX 35: semi-annual review (Jun/Dec) + technical follow-ups. AEX: annual March review + quarterly partials. SMI: annual September review. EURO STOXX 50: annual September review + fast-entry/exit rule. IBrX 100: B3 three times a year (Jan/May/Sep), same as ibov.

### Constraints

1. **Plans are documentation of CURRENT live behavior** (post-U3.5): leaver derivation from declared snapshots, two-stage gating with 10% churn gate / 2-day persistence / 30-day rejected-resight cooldown, `MONITOR_GATED` + review digest. Do not describe aspirational machinery.
2. **Honesty about corroboration:** every wikipedia-primary universe is single-source scraped. `accuracy_reference` candidates (fmp, etf_holdings) are NOT usable in this environment today (FMP unreachable; no ETF holdings URLs configured). Say so; don't configure a reference that errors.
3. **No Dagster schedule in this story** — cadence is documented; the schedule (with explicit `execution_timezone`, hard standing rule) is a separate operational story.
4. **The validate check must not crash the suite** when the doc is missing (deployments without docs/) — WARN with detail. `run_all` error-isolates anyway, but the check itself should degrade gracefully.
5. **`as_of_date` canonical naming** in any new code.
6. **Config updates are data changes** — apply via a connected script (autocommit), verify by re-query; no migration needed (config is jsonb).
7. **estoxx50 alignment caveat:** members trade on multiple venues; XETR is the token/alignment calendar (matches its wikipedia spec mic). State it in the plan.

### Previous-story intelligence (U3.5 + its two review rounds)

- Gating/monitor behavior to restate in plans: discoveries stage as proposals; churn >10% gates the run (`status=gated`, counts as ALIVE for staleness); promotion after 2-day persistence or 2nd-source corroboration; rejections cool down 30 days; `sym universe reverse`/`confirm`/`accuracy` exist.
- The monitor session-snaps `as_of_date` ONLY when `calendar_mic` is set — that's why Task 3 matters.
- Test patterns: DB-free `_Conn` SQL-substring fakes (`tests/test_universe_monitor_routing.py`); validate checks return `CheckResult.from_items(...)` (see `src/sym/validate/fx.py` for a compact template).
- Suite baseline: 465 tests, ~3s. Zero new lint expected (repo has 18 pre-existing).

### Project Structure Notes

- New code: `packages/sym/src/sym/validate/plans.py` + `tests/test_validate_plans.py` + one wiring line in `runner.py`. Everything else is docs (`docs/universe-maintenance.md`), data (config updates), and ledger.

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md#chunk 3 D4]
- [Source: docs/universe-maintenance.md] — template (ibov), header rule
- [Source: _bmad-output/implementation-artifacts/U3-5-wire-safety-machinery.md] — live gating behavior to restate
- [Source: packages/sym/src/sym/validate/{runner,results,fx}.py] — check pattern

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor for the code task.

### Debug Log References

- Task 1 RED: collection error (module absent) → GREEN: 5/5 after implementing `plans.py`.
- The heading regex requires a lowercase slug start, so prose headings ("## Wikipedia-sourced universes") don't register as plan slugs.

### Completion Notes List

- **Task 1:** `check_maintenance_plan_coverage` enforces the populate gate: populated index universe (≥1 open member) without a `## <slug>` section → FAIL; missing doc → WARN (suite must not crash on docs-less deployments); unpopulated universes ignored (the rule gates populating, not registering). Doc located by walking up from the package to the repo root; `doc_path=` injectable for tests. Wired as the 12th check in `run_all`.
- **Task 2:** 12 new plan sections + a shared-mechanics section for the 11 wikipedia-sourced universes (source nature, cadence, gating, honest single-source corroboration posture stated once). ibov plan updated with `calendar_mic=BVMF`. The stale "ibx — planned, not yet populated" section replaced — ibx had 99 open members.
- **Task 3:** `calendar_mic` configured on all 13 universes (jsonb merge, verified by re-query): sp500/sp400/sp600=XNYS, dax/estoxx50=XETR, cac40=XPAR, ftse100=XLON, ibex35=XMAD, ftsemib=XMIL, aex=XAMS, smi=XSWX, ibov/ibx=BVMF. Session-snapped `as_of_date` and event alignment are now live everywhere (previously inert — no universe had the key).
- **Task 4:** first-ever `monitor ibx` run: success, 0 discoveries (B3 snapshot matches all 99 open members); `stale_monitors()` → empty.
- **Task 5:** `sym validate`: `maintenance_plan_coverage` PASS (checked=13). Overall suite FAIL persists on the two pre-existing data-quality checks (universe_member_completeness GICS gaps; unpriced_securities) — unrelated to this story.
- Known follow-ups kept on the ledger: independent `accuracy_reference` per wikipedia universe (no reachable second source today); daily monitor schedule (Dagster, explicit `execution_timezone`) is deliberately out of scope.

### File List

- packages/sym/src/sym/validate/plans.py (new)
- packages/sym/src/sym/validate/runner.py (modified — wire check)
- packages/sym/tests/test_validate_plans.py (new — 5 tests)
- docs/universe-maintenance.md (modified — header, ibov calendar line, ibx restated, shared mechanics + 11 plans)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D4 done)
- (data) `universe.config.calendar_mic` set for 13 universes; `universe_monitor_log` row for ibx

### Change Log

- 2026-06-10: Story implemented (Tasks 1-5); suite 465 → 470 green; `maintenance_plan_coverage` live and passing for all 13 universes. Status → review.
