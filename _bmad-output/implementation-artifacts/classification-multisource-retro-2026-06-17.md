# Retrospective — Multi-source industry classification

Date: 2026-06-17 · Story: `classification-multisource.md` (standalone, not a sprint-status epic) · Facilitator: Amelia (Developer) · Lead: Andre

> Format note: QRP is owner-operated, so this is a written retrospective grounded in the
> actual artifacts (story file, 10 commits, 3-layer code review, deferred-work ledger) rather
> than a multi-role party-mode session. The discipline — wins, friction, lessons, action
> items, readiness — is intact.

## Summary / metrics

- **Scope delivered:** a 5-source GICS classification fill-chain — financedatabase → b3 → sec_sic → yahoo_profile → llm — with provenance + precedence.
- **Outcome:** whole-universe coverage **90.0% → 99.1%** (2168/2187 active). Non-Brazil GICS gap CLOSED (HON classified; `universe_member_completeness` on nasdaq100/ftse100 went to ~0). The ~19 still-unclassified are funds/ETFs that *correctly* have no GICS sector.
- **ACs:** all of AC1–AC8 landed (AC1 registry partial-but-defensible; AC3/AC4 were locked-scope deferrals, built anyway; AC5 deferred-then-built).
- **Delivery shape:** 10 commits across 5 feature branches, each `--no-ff` merged to main; every branch reviewed before merge.
- **Quality:** 685 tests green (1 pre-existing unrelated `tests`-import failure); ruff clean. DB-free unit tests per source (fake clients, no network, no LLM call at runtime).
- **Review:** 3-layer adversarial code review (Blind / Edge / Acceptance) — 4 patches applied, 4 deferred, 9 dismissed; plus 2 focused per-source reviews during dev that each found a High bug.

## What went well

1. **Probe-before-build directly unblocked work.** Re-probing the Yahoo crumb flow (per the "name the probe" rule) confirmed `getcrumb → assetProfile` works in-env *before* committing to AC3 — and the SEC submissions probe de-risked the MVP. No source was built on an unverified assumption.
2. **The abstraction already existed.** `GicsSource` protocol + `SecurityIdentity` + the `read_unclassified_identities` fill-scope + the source-tagging SCD writer (from the b3 work) meant "multi-source" was mostly *new source classes*, not a framework rebuild. Reading the b3 archetype first was the highest-leverage move of the whole effort.
3. **Adversarial review caught real High bugs unit tests missed** — the dead 401-retry (`raise` without `from`, so `__cause__` was never the HTTPError — looked correct), the `quoteSummary: null` AttributeError escaping per-symbol isolation, and the unguarded `read_active_coverage` (a non-OperationalError there would silently roll back the whole atomic classify run). None of these were visible from green tests.
4. **Looking at the data reframed the LLM task.** Pulling the actual residual list showed ~18 of 26 were funds/ETFs (no GICS sector exists) — so the LLM's real job was ~7 operating companies, with a "fund → leave unclassified" guard. This prevented hallucinating sectors for ETFs.
5. **Topology discipline held cleanly.** The SEC client was *replicated* (not imported from altdata — peer-package rule); Yahoo reused the in-package `YAHOO_SUFFIX`. No cross-package coupling introduced.
6. **Vocabulary drift — the single highest risk for a multi-source classifier — was zero.** All three new crosswalks emit byte-identical canonical GICS labels; the LLM loader actively *refuses* a non-GICS sector at load.

## What was hard / friction

1. **The same High-severity bug recurred across sources.** Per-item error isolation (one bad CIK / one bad symbol aborting the whole pass) was found in *both* sec_sic and yahoo_profile — the source archetype didn't encode it, so each source reinvented (and initially missed) it. Same for the per-name throttle.
2. **AC5 looked satisfied but wasn't.** "Fill-only first-writer-wins" cleanly covered *precedence into an empty slot*, which felt like AC5 — but AC5's actual text ("a higher-precedence source later closes the lower one") was unbuilt, and the dev record **overstated it as fully met**. The Acceptance Auditor caught the self-assessment drift.
3. **A constraint surfaced mid-build:** no Anthropic API key in-env forced a design pivot for AC4 (human-in-the-loop artifact instead of an API-calling source). Good outcome, but discovered during, not before.
4. **Recurring test-run noise:** the pre-existing `tests.test_fx_coverage` import-path failure showed up in every full-suite run, has been ledgered *twice*, and still isn't fixed — it dilutes signal on every green/red check.

## Key lessons

- **Read the existing archetype before adding the Nth instance.** The fill-pass/provenance model already encoded the answer; building on it beat designing a new "registry."
- **A green test suite is necessary but not sufficient — adversarial review finds a distinct bug class** (exception-chaining subtleties, transaction blast radius, malformed-payload escapes). Both the per-source dev reviews *and* the holistic end-of-feature review earned their keep.
- **Self-assessment drifts optimistic.** Claiming an AC "fully met" deserves an adversarial acceptance check; the auditor's correction on AC5 was the most valuable single finding.
- **Look at the data before designing the fix** (the funds-vs-companies reframing).

## Action items

1. **Encode per-item error isolation + per-name throttle into a shared source pattern/base** so the next classification source inherits them — directly addresses the recurring High finding. _Owner: Andre/agent · before the FMP source._ — **PARTIAL ✅ (2026-06-17):** the duplicated throttle is now a shared `sym/classification/_http.py:RequestThrottle` used by both the SEC + Yahoo clients (with its own test). Per-item *isolation* stays per-source for now (already uniform + reviewed in both; would risk over-abstraction to force into a base) — fold into a base when the FMP source lands.
2. **Fix the ledgered `tests`-import-path one-liner** (`from tests.test_fx_coverage import _Conn` → a top-level import) — deferred twice; it adds noise to every run. _Owner: Andre/agent · quick win._ — **DONE ✅ (2026-06-17):** changed to `from test_fx_coverage import _Conn`; full suite now **688 passed, 0 failed**.
3. **Add a coverage-by-source check to `sym validate`** (or a periodic gate) so classification regression/drift is caught automatically, not only on a manual `sym classify`. _Owner: Andre/agent._
4. **When building the FMP source (next deferred source), add it to `SOURCE_PRECEDENCE`** and reuse the now-built AC5 precedence scope — no new merge machinery needed. _Owner: Andre/agent._
5. **Revisit the AC1 registry generalization only if a 6th source lands** — concrete-source hard-coding is defensible at 5; the ledger already flags it. _Owner: Andre/agent · conditional._

## Readiness assessment

- **Functionally complete + on main.** 99.1% coverage; remaining residual is correctly-unclassified funds. All branches merged `--no-ff`; tests green; ruff clean.
- **No deploy step** — it's a CLI maintenance command writing to the DB; no service/console change (heatmap + validate already read `gics_scd`).
- **The one real gap (AC6):** classification is whole-universe + idempotent but **not scheduled** — it won't stay fresh automatically as universes/data change. A Dagster schedule (with explicit `execution_timezone`) is the productionisation if this needs to self-maintain.
- **Deferred-work ledger is current:** AC5 ✅ done; remaining — FMP profile source, AC6 cadence hook, Yahoo 401-storm circuit-breaker, SEC duplicate-ticker dedup.

## Follow-up candidates (no formal "next epic")

This was a standalone story. Natural next work: the **FMP source** (would benefit most from action item #1), the **AC6 scheduling hook**, or unrelated tracks (console hardening, the `tests` fix). No blocking dependency on this work for any of them.
