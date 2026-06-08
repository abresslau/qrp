---
epic: FX
title: FX-rate layer (USD-centered, derive crosses)
date: 2026-06-08
status: complete
facilitator: Amelia (Developer)
participants: [Andre (Project Lead), Winston (Architect), John (PM), Mary (Analyst), Amelia (Developer)]
first_retrospective: true
---

# Retrospective — Epic FX: FX-rate layer

**This is sym's first formal BMAD retrospective.** No prior retro exists to follow
through on; sym has no `sprint-status.yaml` (state is derived from `epics-*.md` vs code),
so this retro was run against `epics-fx.md` + git history + the in-epic build-status notes.

## Delivery summary

| | |
|---|---|
| Stories | 5/5 done — FX1, FX2, FX3a, FX3b, FX4 (+ 2 autonomous add-ons + `market_cap_usd` follow-on) |
| Tests | 377 passing (DB-free units + live smokes) |
| Migrations | deployed (`fx_rate` + `v_fx` / `v_fx_daily`) |
| Data landed | 194,341 fx rows · 28 currencies (193,817 Frankfurter + 524 fawazahmed0) |
| Validation | `fx_coverage` → PASS; introduced no new failures |
| Commits | `2ec9f07` (FX1) → `33f2961` (market_cap reorder) |

Stories: FX1 storage + canonical-direction integrity · FX2 Frankfurter USD-base ingest ·
FX3a derivation view + as-of resolver · FX3b conversion API (triangulation) · FX4 CLI +
EOD + validation. Autonomous add-ons: fawazahmed0 fallback (closed TWD), currency
restatement consumer (`fx/restate.py`). Follow-on: `fundamentals.market_cap_usd`.

## What went well

1. **Derive-don't-store held the whole way.** `v_fx` (inverse + injected USD/USD=1) and
   `v_fx_daily` (forward-fill flagged `is_filled`/`observed_date`/`days_stale`) are pure
   views — zero synthetic rows in `fx_rate`. Same reconstructability principle as the
   returns engine; no view/table drift.
2. **The canonical-direction CHECK is one elegant constraint** —
   `base='USD' OR (quote<>'USD' AND base < quote)`. USD-as-quote and self-pairs fall out
   for free; no rank-lookup table, no separate CHECKs.
3. **Pre-build design split paid off.** The advanced-elicitation / party-mode pass split
   FX3 into FX3a (derivation/resolver) + FX3b (convert/triangulation) *before* building —
   two independent concerns, two independent test suites, one clean dependency chain.
4. **`convert()` owns triangulation; the view does not** — a single implementation of the
   cross math. `convert()` returns `Decimal` (explicit precision contract).
5. **The multi-source seam was real, not theoretical** — proven the moment TWD needed it.
6. **Coverage check can't rot into dead code** — defined against the currencies of
   *currently-priced instruments* (a live denominator), not a hardcoded list.
7. **A watched consumer smoke** — `sym fx convert <amt> <from> <to> --as-of` so a human
   saw the loop work, not only the test asserting it.
8. **Source honesty went all the way down** — the Frankfurter provenance asterisk
   (rates are ECB-*rebased* to USD, not primary observations) is recorded in a code
   comment, so the future ECB reconcile starts informed.

## Challenges & lessons

1. **Free data has a hard floor.** Frankfurter's ~31 currencies miss TWD + exotics. The
   fawazahmed0 fallback closed TWD *forward*, but its dated files only reach ~mid-2024 —
   so the **2020→2024 TWD deep-history gap is permanent on free sources.** Lesson:
   surface free-source coverage limits up front, not at validation time.
2. **FR4b was genuinely undeliverable with one source** (cross-source divergence flag) —
   correctly deferred and *labelled* deferred rather than faked. Discipline, not a miss;
   it lands with the second source.
3. **The epic boundary moved during the autonomous session.** FX scope explicitly put
   "applying FX to restate prices/returns in USD" OUT (a downstream/analytics consumer),
   but `fx/restate.py` + `market_cap_usd` were built in sym. The work is correct and QRP
   consumed it immediately — but the architecture doc still describes restatement as
   downstream. **Decision (Andre): the boundary move is deliberate and correct** (a thin
   pure primitive over `fx_rate` belongs next to the data); the architecture doc will be
   updated to match reality. → Action item A2.
4. **Two sym-wide gotchas recurred** (already in operator memory): psycopg per-figi
   durability needs `conn.autocommit=True` (else `conn.transaction()` is only a
   savepoint), and the DB-validation rollback trap when code self-commits. Noted as
   recurring; a standing engineering note was *considered but not tracked* this round.

## Continuity (pattern reuse from prior epics)

Though this is the first formal retro, FX deliberately reused established sym conventions
rather than reinventing: AR-5 source abstraction (the `fx` adapter mirrors the OHLCV
source), AR-6 immutable/explicit inputs, AR-7 derive-don't-store, Sqitch plain-SQL
migrations (Docker + `host.docker.internal`), psycopg3, DB-free unit tests + live
verification, and the `as_of_date` date-naming convention. That reuse is itself the
"lessons applied from earlier epics" story.

## Next / forward look

There is no numbered "Epic FX+1" in sym. Notably, **FX's stated reason-to-exist — folding
the multi-currency universe to a common currency for cross-market comparison and the
analytics/backtest modules — is already realized in QRP** (portfolios/analytics/backtest/
optimiser all consume sym returns + FX). So forward work is consolidation, not a new
dependency chain:

- **ECB SDMX reconcile** (the one tracked action) — second authoritative source.
- Architecture-doc truth-up for the restatement boundary.

**Significant-discovery check: none that invalidate any plan.** The only structural change
is the restatement boundary, which is acknowledged and will be documented (not a surprise
that derails downstream work).

## Action items

**A1 — Wire ECB SDMX as a second authoritative FX source.** ✅ DONE 2026-06-08
(commit `d8eeeaf`). `EcbSdmxSource` (EUR-base rebased to USD through the EUR/USD leg),
deterministic source precedence (`fx_source_rank` SQL fn, mirrored by `SOURCE_PRECEDENCE`),
and **FR4b delivered** via `sym.fx.reconcile` + `sym fx divergence`. Verified live:
Frankfurter vs ECB compared=75 diverged=0; resolver prefers Frankfurter; `fx_coverage` PASS.
**Caveat (honest):** ECB's ~31-ccy set excludes TWD, so the **2020→2024 TWD deep-history gap
is NOT closed** by ECB (free-source floor; stays on fawazahmed0). The reconcile/divergence
half of A1 is fully delivered; the TWD-deep-history half is not achievable from ECB.
*Operational follow-up:* a full `sym fx backfill --source ecb` (only a BRL/EUR/GBP smoke set
is loaded) corroborates Frankfurter's deep history for the covered currencies.

**A2 — Update the architecture doc to record the restatement boundary move.** *(tracked)*
Owner: Andre. State that USD-restatement (`fx/restate.py`, `market_cap_usd`) lives in sym
as a thin pure primitive over `fx_rate` — a deliberate change from the "downstream
consumer" framing in `epics-fx.md`. Success: `architecture.md` describes the actual seam so
the next consumer is not misled.

### Considered but NOT tracked (deliberately, to avoid over-committing)
- Standing engineering note for the psycopg-autocommit + validation-rollback gotchas
  (already captured in operator memory).
- A per-source coverage/history floor doc.
- The pre-existing Brazil GICS validate FAIL (43/78 IBOV unclassified — free-tier coverage,
  not an FX issue).

## Readiness assessment

| Dimension | Status |
|---|---|
| Tests / quality | ✅ 377 passing; `fx_coverage` PASS |
| Data populated | ✅ 194,341 rows / 28 currencies (Frankfurter + fawazahmed0 TWD) |
| Committed | ✅ all stories on `main` (`2ec9f07`→`33f2961`) |
| Validation impact | ✅ no new failures introduced (pre-existing GICS/unpriced FAILs unrelated) |
| Known gaps | TWD 2020→2024 deep history (free-source floor); FR4b pending 2nd source (A1) |

**Epic FX is production-complete.** No blockers carried forward; the two action items are
enhancements, not gates.

## Key takeaways

1. **Defer honestly over faking** — FR4b labelled deferred (not silently dropped) is the
   model to repeat when a requirement needs inputs you don't yet have.
2. **The multi-source seam earned its keep immediately** — design-for-pluggability is only
   worth it when it gets used; here it did, same epic.
3. **Boundaries move during build — record the move.** Good code in the "wrong" layer is
   still a doc-truth problem; A2 closes it.
