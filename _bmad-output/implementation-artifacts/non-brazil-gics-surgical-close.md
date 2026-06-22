# Story: Non-Brazil GICS — surgical close of the live residual

Status: done

<!-- The long-standing "non-Brazil GICS gap" (the one functional thread from the QH retros). On
investigation 2026-06-22 the gap is already ~closed (sec_sic + yahoo_profile + wikidata, shipped
2026-06-17, took it to 99.1%). This story closes the LIVE residual surgically rather than building
the obsolete 134-row SIC→GICS mapping (which already exists in sec_sic.py). -->

## Reframe (investigation 2026-06-22)

The "134 FAIL rows / SEC SIC→GICS mapping" task is **obsolete**: the multi-source fill chain
(`financedatabase → b3 → sec_sic → yahoo_profile → wikidata`, the last three shipped 2026-06-17)
already closed the gap. Live measurement (pre-today's-EOD):

- **19 active securities unclassified** total (= the 99.1% `classification_coverage` PASS residual).
- **Only 4 are CURRENT universe members** (what `universe_member_completeness` actually flags):

| Ticker | FIGI | What it is | Universe | Root cause |
|---|---|---|---|---|
| FB | BBG01VRMNFB1 | **ProShares S&P Dynamic Buffer ETF** | S&P 500 | **spurious member** — an ETF mis-resolved onto the retired Facebook "FB" ticker; PCLN-class (stale JOIN, no LEAVE). NOT a classification gap. |
| ALW | BBG000BFH585 | Alliance Witan PLC | FTSE 100 | LSE investment trust (closed-end fund); `sec_sic` is US-only |
| PCT | BBG000HHH6S1 | Polar Capital Technology Trust | FTSE 100 | LSE investment trust |
| SMT | BBG000BFZM24 | Scottish Mortgage Investment Trust | FTSE 100 | LSE investment trust |

The other 15 unclassified are delisted legacy tickers (JAVA/EMC/SHLD/SPLS/PCLN/…) in NO current
universe — survivorship retention, not the gap.

**Decision (Andre 2026-06-22): Surgical close** — fix the FB data bug (+ sweep for siblings), and
classify the 3 FTSE-100 investment trusts as Financials via the cleanest sourced path.

## Acceptance Criteria

1. **FB spurious member removed from S&P 500.** The ProShares ETF (`BBG01VRMNFB1`) mis-resolved onto
   the dead `FB@XNYS` ticker is removed from S&P 500 current membership via an **auditable, reversible**
   `gating.reverse_change` tombstone (the proven PCLN path) + `rebuild_projection` — never a hard delete.
   META remains the real S&P 500 member. S&P 500 count drops by exactly 1.
2. **Sweep for siblings.** All index universes are swept for the same failure mode (an ETF/fund FIGI
   mis-resolved as an index *constituent*); any true hit is fixed the same way, false positives
   (legit REITs/trusts that ARE constituents) are left alone and listed.
3. **The 3 FTSE-100 investment trusts carry a GICS sector = Financials**, via a real source row
   (`yahoo_profile`/`wikidata` fill if today's EOD classify reaches them; otherwise the cleanest
   sourced fallback — NOT a hardcode). Closed-end investment trusts are GICS **Financials**.
4. **`sym validate --universe ftse100` and `--universe sp500`** no longer flag these names in
   `universe_member_completeness`; no NEW validate regressions; the global `classification_coverage`
   stays ≥ its current 99.1% PASS.
5. **No regression.** sym tests + ruff green; the membership corrections are reversible + audited
   (paired_corrections, no toggle/dangling), same posture as the nasdaq100/PCLN fix.

## Tasks / Subtasks

- [x] Task 0: Re-measured after today's `sym eod` classify — `fills touched 0` (Yahoo `quoteSummary`
  is HTTP-404-blocked in the sim env; Wikidata no-match), so the 3 trusts were NOT auto-closed; residual
  stayed the same 4 names. Confirmed before any code change.
- [x] Task 1: FB spurious-member fix (AC1) — confirmed META (`BBG000MM2P62`) IS the real sp500 member;
  the spurious join was event 1089 `ticker:FB@XNYS` (2013-12-23, no LEAVE) resolving to the ProShares
  ETF (the recycled "FB" ticker). `sym universe reverse sp500 ticker:FB@XNYS join 2013-12-23` → corrective
  appended + projection rebuilt. **sp500 502 → 501; ProShares ETF dropped; META retained.**
- [x] Task 2: Sibling sweep (AC2) — swept all index universes for ETF/fund-vehicle current members.
  Only FB was a true spurious member; **WT/"WisdomTree Inc" was a false positive** (the real
  publicly-traded asset manager, a legit S&P SmallCap 600 company, already classified). Left alone.
- [x] Task 3: Trusts → Financials (AC3) — probed in-chain sources: yahoo `*.L` → **404 in-env**,
  wikidata **no-match**. Per Andre's call, built a new **`manual`** (operator-asserted) classification
  source: `manual.py` + curated `manual_classifications.json` (the 3 trusts → Financials, matched by
  `composite_figi`, source-tagged honestly), ranked **1** in `SOURCE_PRECEDENCE` (above every automated
  source, below the FD primary), always-on, fill-only, sector-only. `sym classify` → **3 inserted**,
  whole-universe coverage 99.1% → **99.3%**.
- [x] Task 4: Verify (AC4, AC5) — `sym validate --universe ftse100` + `--universe sp500`:
  `universe_member_completeness` **PASS** (0 incomplete) on both; `classification_coverage` PASS 99.3%
  (`manual 3` in the source breakdown). Current-universe-member unclassified residual = **0**. The lone
  remaining overall-FAIL is the pre-existing global `unpriced_securities` (out of scope; 0 of these
  universes' members affected). **838 sym tests pass, ruff clean.**

## Dev Agent Record

### Completion Notes
- The "non-Brazil GICS gap" reframe held: the 134-row figure was obsolete; the live residual was 4
  names = 1 data bug (FB) + 3 FTSE-100 investment trusts. Both classes closed surgically.
- **FB**: a PCLN-class spurious member (recycled ticker resolving to a ProShares ETF), fixed with the
  same reversible/audited `reverse_change` path — no destructive edit.
- **Trusts**: the clean automated path (yahoo_profile) is env-blocked (404), so a new high-trust
  `manual` source records the verifiable ICB/GICS fact (investment trusts → Financials) with an honest
  `source='manual'` tag — not a fabrication, not a mislabel. Reusable for any future operator-asserted
  fact a live source can't reach. In production, yahoo_profile would corroborate it (same sector → an
  in-place provenance upgrade, never a conflict).
- The precedence renumber (inserting `manual`=1) updated two existing tests that had used `"manual"` as
  their *unknown-source* placeholder — swapped to `"legacy_import"` and added positive `manual`-ranking
  assertions.

### File List
- `packages/sym/src/sym/classification/manual.py` (new — `ManualGicsSource` + loader)
- `packages/sym/src/sym/classification/manual_classifications.json` (new — the 3 trusts → Financials)
- `packages/sym/src/sym/classification/gics.py` (modified — `manual`:1 in `SOURCE_PRECEDENCE`, renumber)
- `packages/sym/src/sym/classification/registry.py` (modified — `manual` in `fill_specs` + opinion matrix + `_render_manual`)
- `packages/sym/tests/test_classification_manual.py` (new — 9 tests)
- `packages/sym/tests/test_classification.py` (modified — `manual` is now a known source; placeholder swap + ranking asserts)
- Data: `sym universe reverse` corrective event on `sp500` (FB) + 3 `gics_scd` rows (source=`manual`) — live in the sym DB.

## Dev Notes

### Critical conventions
- **Membership corrections are reversible + audited** — `gating.reverse_change` (tombstone the named
  event) + `rebuild_projection`, never a destructive edit. Exactly the PCLN/nasdaq100 pattern.
- **Classification stays sourced + fill-only + SCD** — never hardcode a sector; every GICS row carries
  a real `source` and respects `SOURCE_PRECEDENCE`. Investment trusts → Financials is the GICS-standard
  mapping (closed-end funds sit in Financials).
- **No fabrication** — if a trust genuinely has no resolvable sector from any source, leave it honestly
  unclassified + documented rather than guess.

### References
- [Source: packages/sym/src/sym/classification/{registry,sec_sic,yahoo_profile,wikidata}.py] — the fill chain.
- [Source: packages/sym/src/sym/universe/gating.py] — `reverse_change` (the PCLN/nasdaq100 correction path).
- [Source: _bmad-output/implementation-artifacts/nasdaq100-universe.md] — the PCLN-class precedent + sweep.
- [Source: memory project_classification_sources] — 5-source fill chain; "GICS gap CLOSED (99.1%), rest are funds".

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created. Investigation reframed the "non-Brazil GICS" task: the gap is already ~closed (99.1%); the live residual is 4 names = 1 spurious-ETF-in-S&P-500 data bug (FB) + 3 FTSE-100 investment trusts. Scope = surgical close (Andre). Awaiting today's EOD classify to re-measure before fixing. |
| 2026-06-22 | Done. FB spurious ProShares-ETF member reversed out of S&P 500 (502→501, META retained; sweep found no siblings — WT was a false positive). New `manual` operator-asserted classification source (rank 1, above all automated, below FD primary) closes the 3 FTSE-100 investment trusts → Financials (yahoo `*.L` is 404-blocked in-env). Coverage 99.1%→99.3%; ftse100 + sp500 `universe_member_completeness` PASS; current-member unclassified residual = 0. 838 sym tests + 9 new manual-source tests green; ruff clean. Status → done. |
