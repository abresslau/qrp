# Story B7: Identity-key bridge integrity (Option A) + self-healing map step

Status: done

<!-- Back-filled 2026-06-09: implemented ad-hoc from a conversational design debate, then
documented retroactively as a story (the Option A decision warranted the artifact). Not run
through bmad-code-review; verified by the live validate suite + 398 sym tests. -->

## Story

As the **QRP owner-operator**,
I want **the two-key identity model (`composite_figi` for equities, `sym_id` as the cross-asset spine) made an explicit contract** — the bridge kept current automatically and checked every run,
so that **cross-asset joins (equity returns ↔ index returns via `sym_id`) never silently drop a security, and the "which key goes where" decision is settled and documented rather than implicit "half and half".**

## Context

A design debate (2026-06-09): should sym have forced `sym_id` across the board instead of keeping
`composite_figi`? Investigation showed the split is **deliberate** (the B1 `sym_id` epic), not drift:

- `composite_figi` (CHAR(12) natural key) keys the **equity warehouse** (securities, prices, returns,
  fundamentals, symbology, …) — immutable, human-readable, the way vendor data lands.
- `sym_id` (BIGINT surrogate) is the **vendor-neutral spine** for all instrument kinds — required
  because **indexes have no FIGI** and so cannot key on `composite_figi`.

**"`composite_figi` everywhere" is impossible** (no FIGI for an MSCI index), and migrating equities
onto `sym_id` buys nothing for equities. So the real choice was **A** (keep the split, formalize the
bridge) vs **B** (force `sym_id` everywhere — a large, risky migration). Given the roadmap is **mostly
equities + benchmark indexes**, the decision is **A**.

[B1](B1-instrument-identity.md) built the bridge (`instrument` + `instrument_xref` + resolvers +
`backfill_equity_instruments`) and backfilled 2,047 equity instruments **once**. But the backfill had
**no routine caller**, so it silently drifted: by 2026-06-09, **99 securities added since B1 were
unmapped** — exactly the failure mode that makes "half and half" dangerous (a cross-asset join would
drop those 99 unseen). B7 closes that gap and makes the bridge self-maintaining + self-asserting.

## Acceptance Criteria

1. **Decision recorded:** the two-key model, the rationale (no FIGI for indexes), the rule for new
   tables (single-equity vendor facts → `composite_figi`; cross-asset/vendor-neutral → `sym_id`), and
   the bridge contract are documented in `docs/data-conventions.md` (§3) and in agent memory.
2. **Bridge-integrity check:** a `sym validate` check (`equity_instrument_bridge`) **fails** if any
   `securities` row is unmapped to an `instrument` via a `composite_figi` xref, or if any
   `instrument(kind='equity')` lacks its `composite_figi` xref. Reports actionable samples.
3. **Self-healing:** the equity→instrument backfill runs as a routine EOD step (`map`), idempotent, so
   newly-added securities are mapped every run. Manual path preserved: `sym eod --steps map`.
4. **Holes closed:** the 99 pre-existing unmapped securities are mapped; the bridge check passes.
5. **No regression:** full sym suite green; `dagster definitions validate` passes (the schedule runs
   `sym eod`, now including `map`).

### Out of scope
- Option B (repointing the equity warehouse onto `sym_id`) — explicitly **not** chosen.
- A hard FK from `securities` → `instrument_xref` (kept additive/soft per B1; the validate check is the
  gate). Revisit if QRP becomes a true multi-asset book.

## Tasks / Subtasks

- [x] Task 1: `validate/instrument_bridge.py` — `check_equity_instrument_bridge`; register in
  `validate/runner.py` (next to V2 referential integrity). (AC: #2)
- [x] Task 2: add `map` step to `eod.py` `DAILY_STEPS` (after `delta`) → `backfill_equity_instruments`;
  update module docstring. (AC: #3)
- [x] Task 3: run `sym eod --steps map` to close the 99 holes; re-validate → PASS. (AC: #4)
- [x] Task 4: document Option A + the rule in `docs/data-conventions.md` §3. (AC: #1)
- [x] Task 5: fix `test_eod` step-order expectation; verify suite + dagster. (AC: #5)

### Review Findings
_Adversarial review 2026-06-09 (bmad-code-review, 3 layers: Blind / Edge Case / Acceptance). 1 decision, 6 patch, 3 defer, 2 dismissed. This was code-first then back-filled, so a couple of doc claims ran ahead of the wiring._

- [x] [Review][Decision→Patch] **`map` solved drift that doesn't occur daily and missed the drift that does** — securities are created by `run_universe_load` (CLI universe load), not by any EOD step. RESOLVED (chose option 1): now also call `backfill_equity_instruments` at the source (`run_universe_load`, where securities are born) + keep the nightly EOD `map` as the safety net. Closes the window. [universe/ingest.py:149-156]
- [x] [Review][Patch] Bridge check forward direction now joins `instrument_xref → instrument` and requires `kind='equity'` — a figi xref'd to a non-equity instrument no longer passes as "mapped" [validate/instrument_bridge.py]
- [x] [Review][Patch] Orphan-instrument message + docstring corrected — now state the backfill will NOT repair an orphan (partial-insert; needs manual reconciliation) [validate/instrument_bridge.py]
- [x] [Review][Patch] "Asserted every run" tightened in §3 + this story → "checked every run" (hard non-zero gate only via standalone `sym validate`; logged `[FAIL]` within the non-critical EOD step) [docs/data-conventions.md §3]
- [x] [Review][Patch] Lineage docstring corrected — now notes `instrument_xref` bridges the two key-spaces (cross-key edge not yet drawn) [packages/lineage/src/lineage/assets.py:20-22]
- [x] [Review][Patch] runner.py comment fixed `# B1` → `# B7` [validate/runner.py:34]
- [x] [Review][Patch] Added pure helpers `find_unmapped` / `find_orphan_instruments` (now used by the check) + DB-free tests [validate/instrument_bridge.py, tests/test_instrument_bridge.py]
- [x] [Review][Defer] Add the cross-key bridge edge (securities.composite_figi → instrument_xref → instrument.sym_id) to the lineage DAG — deferred, enhancement [lineage/assets.py]
- [x] [Review][Defer] No warn/exempt tier for delisted/suspended securities in the bridge check — deferred, steady-state consistent (backfill maps all statuses) [validate/instrument_bridge.py]
- [x] [Review][Defer] CHAR(12)↔TEXT identity across the bridge relies on the figi `^[A-Z0-9]{12}$` CHECK (no padding); the check now compares in Python sets so SQL coercion is no longer involved — deferred, latent (safe today) [validate/instrument_bridge.py]

## Dev Notes

- **Bridge invariant** (`instrument_bridge.py`): two anti-joins — `securities` with no
  `instrument_xref(source='composite_figi', value=figi)`, and `instrument(kind='equity')` with no
  `composite_figi` xref. `UNIQUE(source,value)` (B1) already guarantees one figi → one `sym_id`, so the
  only realistic hole is unmapped rows. Modeled on `validate/integrity.py`; returns a `CheckResult`.
- **Map step is non-critical** (matches sym's "a hiccup shouldn't fail the night" tier — monitor/
  benchmarks/fx/validate); the data-critical path stays delta + recompute. `validate` (last step) is
  the gate that turns a residual hole red.
- **Why a step, not a CLI subcommand:** EOD steps are individually runnable (`sym eod --steps map`), so
  one step gives both the daily self-heal and the manual path without touching the CLI subparser.
- **Idempotent:** `backfill_equity_instruments` is `WHERE NOT EXISTS` + inserts only for new securities
  — cheap to run nightly (mapped new=99 existing=2047 on the closing run).

### Project Structure Notes
- Pure follow-on to the B epic / `identity/instrument.py`; no schema migration (additive, code-only).
- New validate check slots into the Epic-V suite ordering in `validate/runner.py`.

### References
- [Source: docs/data-conventions.md#3-identity-keys-composite_figi-vs-sym_id]
- [Source: _bmad-output/implementation-artifacts/B1-instrument-identity.md]
- [Source: packages/sym/src/sym/identity/instrument.py] — `backfill_equity_instruments`, resolvers
- [Source: packages/sym/migrations/deploy/instrument.sql] — instrument + instrument_xref

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09

### Completion Notes List
- Decision: **Option A** (keep the two-key split) — composite_figi (equity natural key) + sym_id
  (cross-asset spine). Driven by roadmap = mostly equities + benchmark indexes; "force sym_id
  everywhere" (Option B) rejected as a large, low-payoff migration; "composite_figi everywhere"
  impossible (indexes have no FIGI).
- `equity_instrument_bridge` check added to `sym validate` — **immediately caught 99 unmapped
  securities** (B1's one-time backfill of 2,047 had no routine caller and drifted).
- `map` EOD step (after `delta`) makes the bridge self-healing; ran it → mapped new=99, existing=2047;
  bridge check now PASS (2146 securities, 0 unmapped, 0 orphan).
- Documented in `docs/data-conventions.md` §3 + memory (`project_identity_key_decision`).
- Verified: 398 sym tests pass; EOD plan shows `map`; `dagster definitions validate` passes.
- Process note: implemented ad-hoc from a live design debate, committed (4a23834), then back-filled as
  this story; not run through `bmad-code-review`.

### File List
- `packages/sym/src/sym/validate/instrument_bridge.py` (new)
- `packages/sym/src/sym/validate/runner.py` (register check)
- `packages/sym/src/sym/eod.py` (`map` step + docstring)
- `packages/sym/tests/test_eod.py` (step-order assertion)
- `docs/data-conventions.md` (§3 Identity keys)
- `_bmad-output/implementation-artifacts/B7-identity-key-bridge.md` (this story)

### Change Log
| Date | Change |
|---|---|
| 2026-06-09 | Implemented (commit 4a23834): bridge-integrity check + self-healing EOD `map` step; closed 99 unmapped securities; Option A documented. Back-filled as Story B7. |
