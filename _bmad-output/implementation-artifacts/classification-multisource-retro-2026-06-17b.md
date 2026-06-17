# Retrospective — Multi-source classification (arc 2, completion)

Date: 2026-06-17 · Story: `classification-multisource.md` (standalone) · Facilitator: Amelia (Developer) · Lead: Andre

> Second retrospective on this work. Arc 1 (SEC SIC → Yahoo → LLM, first code review, AC5) is in
> `classification-multisource-retro-2026-06-17.md`. This covers arc 2 — what *completed* the story —
> and builds on (does not repeat) arc 1. Solo owner-operated project, so written retro, not party-mode.

## What arc 2 delivered

The story is now **fully complete — all AC1–AC8 met**. Arc 2 added:
1. **FMP profile source** (the 6th source) — keyed/dormant (no `FMP_API_KEY` in-env), gated so it adds one clean "skipped" line, not noise; uses FMP's `isFund`/`isEtf` to *explicitly decline* funds.
2. **AC1 registry** (`registry.py`) — collapsed the six hand-written pass+report blocks into `FillSpec` + `fill_specs()` + `run_fill_pass()`; the CLI no longer imports concrete fill sources; an import-time guard cross-checks the chain against `SOURCE_PRECEDENCE`.
3. **A 3-layer code review of the registry** — caught a **HIGH equivalence regression** (`spec.factory()` outside the try → an LLM-artifact failure rolled back the whole committed run + crashed the CLI) plus 2 minor; all fixed and the High proven fixed live.
4. **AC6 cadence** — `classify` added to `sym/eod.py` `DAILY_STEPS` (after `map`, before `validate`), riding the existing `sym_eod_daily` Dagster schedule; `run_classification_chain` is now the single orchestrator for both the CLI and the nightly.

End state: 6-source precedence chain (financedatabase → b3 → sec_sic → fmp → yahoo → llm), **99.1% coverage**, runs daily, **733 tests green**, every source ≤ one `FillSpec` entry away.

## Follow-through on arc 1's action items

| # | Arc-1 action item | Status |
|---|---|---|
| 1 | Per-item isolation + throttle into a shared base | ✅ **Done** — throttle → `RequestThrottle` (arc 1); per-pass isolation **centralized** in `run_fill_pass` (arc 2) — every fill source now goes through one isolation point |
| 2 | Fix the `tests`-import one-liner | ✅ Done (arc 1) |
| 3 | Coverage-by-source check in `sym validate` | ✅ **Done (2026-06-17b)** — `check_classification_coverage` now gates coverage + reports by-source in the suite (see action items) |
| 4 | Add FMP to `SOURCE_PRECEDENCE` when built | ✅ Done — FMP built + ranked 3 |
| 5 | AC1 registry generalization if a 6th source lands | ✅ Done — FMP was the 6th; registry built |

Four of five delivered (one via the registry as a side effect); the two *conditional* items (#4, #5) both triggered and were done. Only the `validate` coverage check (#3) carries over.

## The sharpest insight — the recurring theme bit us, predictably

Arc 1's #1 lesson was **per-item error isolation** (the same High-class bug appeared in *both* sec_sic and yahoo because the archetype didn't encode it). Arc 1 left that action item **partial** ("fold into a base when FMP lands"). When arc 2 *did* centralize isolation into `run_fill_pass`, **the centralization itself had an isolation gap** — `spec.factory()` was placed *outside* the try, so the one source whose constructor does I/O (LLM loads its artifact) could escape and roll back the whole run. The exact failure class the prior lesson was about, in the very code that was supposed to fix it.

**Lesson:** centralizing a cross-cutting concern (isolation) is right, but the centralization must preserve the *full* envelope — here, construction, not just fetch/apply. A "behavior-preserving" refactor preserves the *obvious* behavior; the non-obvious behavior (one source deliberately constructed inside the try) is exactly what silently drops. The adversarial review caught it — the **3rd time across this arc a review found a real High that green tests missed**.

## What went well (arc 2)

- **Probe-before-build paid off twice more:** FMP (no key → built dormant + honest, didn't fake it) and AC6 (probed the infra → found `eod.py` + the existing `sym_eod_daily` schedule → *no new schedule needed*, timezone rule already satisfied).
- **Scope discipline held:** FMP didn't sprawl into the registry; the registry didn't sprawl into AC6; each was its own reviewed `--no-ff` merge. Easy to reason about, easy to revert.
- **The registry delivered the AC1 *intent* + arc-1's isolation action item together** — one well-placed abstraction closed two ledgered items.
- **Honest accounting, again corrected by the audit:** the registry's "byte-identical output" claim was contradicted (empty-scope wording) — same self-assessment-drift pattern as arc 1's AC5 overstatement, caught the same way. Twice-confirmed: claim → adversarial check → correction.

## What was hard / friction (arc 2)

- The HIGH regression above — a self-inflicted refactor bug, caught only by review (not tests). Cheap to fix, but it shipped to `main` for one commit before the review.
- No automated equivalence guard: the report-wording drift and the factory regression both slipped past the suite because there's no snapshot/integration test of the `_cmd_classify`/EOD report path.

## Action items

1. **Coverage-by-source check in `sym validate`** — *carried over from arc 1 (#3), now higher value:* classification runs **unattended daily** as of AC6, so a silent regression (a source breaking, coverage dropping) needs an automated gate, not a manual eyeball. — **DONE ✅ (2026-06-17b):** added `validate/classification.py:check_classification_coverage` — gates whole-universe coverage at the same `DEFAULT_COVERAGE_THRESHOLD` via the shared `read_active_coverage` (so the validate + classify gates can't disagree), FAILs below the floor, and always reports the by-source breakdown for drift visibility. Wired into `validate/runner.py` (now 14 checks); runs in the nightly EOD `validate` step too. Live: `[PASS] classification_coverage: 2168/2187 = 99.1%; by source: financedatabase 1968, yahoo_profile 97, b3 49, sec_sic 47, llm 7`. 4 pure-logic tests.
2. **An output/equivalence guard for the classify report** — a snapshot test of `run_classification_chain`'s rendered lines (or the EOD `classify` step status), so the next refactor can't silently drift wording or behavior. Would have caught both arc-2 slips. _Owner: agent/Andre._
3. **Refactor checklist — enumerate non-obvious per-branch behavior before a "behavior-preserving" change.** The factory-in-try detail was knowable (the old code had a comment about it). A 2-minute "what does each branch do that isn't obvious?" pass before refactoring would have caught it. _Process, not code._

## Readiness assessment

- **Complete + scheduled + on `main`.** All AC1–AC8 met; 99.1% coverage; runs nightly via `sym eod`; 733 tests green; ruff clean (one pre-existing eod.py E501, unrelated).
- **No deploy step** — CLI + DB writes; heatmap/validate already consume `gics_scd`. AC6 makes it self-maintaining.
- **Genuinely-left items are all minor/optional** and ledgered in `deferred-work.md`: the `validate` coverage check (#1 above), the output-snapshot test (#2), the per-item-isolation note is now closed, the Yahoo 401-storm circuit-breaker, the SEC dup-ticker dedup, FMP international-symbol verification (needs a key), and the `_cmd_classify` loop-integration test.
- **No carried blocker.** Nothing here blocks any future work.

## No "next epic"

Standalone story, now done. Natural follow-ups (all optional): the two action items above, or pivot entirely (console hardening, etc.). Recommendation: do action item #1 (the `validate` coverage gate) if/when classification correctness needs an automated guardrail now that it runs unattended — otherwise this is a clean close.
