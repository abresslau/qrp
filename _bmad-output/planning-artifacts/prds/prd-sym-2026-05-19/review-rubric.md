---
title: "PRD Quality Review — sym Global Equity Security Master & Market Data"
prd_ref: prd-sym-2026-05-19/prd.md
reviewer: PRD Quality Review Agent
review_date: 2026-05-20
---

# PRD Quality Review: sym

---

## Dimension 1: Decision-Readiness

**Verdict: CONCERN**

Most FRs are well-specified. However, several leave the architect/developer with design decisions that require clarification or hidden specs:

- **FR-6 (backfill progress tracking):** "Progress tracking so interrupted runs resume without re-fetching completed securities" specifies the outcome but not the mechanism. The developer must decide whether progress state is stored in the database (a run_progress table), a flat file, or the existing pipeline log table. This matters for schema design and is not deducible from context.
- **FR-11 (incremental return computation):** The stated testable consequence ("A daily delta run recomputes 1D, WTD, MTD, QTD, YTD, and rolling windows whose base date is within the new data range") is internally contradictory with the follow-on bullet ("Annualized multi-year windows are recomputed daily"). If multi-year windows are recomputed daily regardless, the FR is describing a partial optimization only — but the boundary rule for rolling windows is still ambiguous. Does "within the new data range" mean the base date is ≤ the new data's earliest date? Needs tightening.
- **FR-1 (FIGI assignment — multiple candidates):** "Flags the record for manual review" — flags it where? In the pipeline log table (FR-8)? In a separate review queue? No target surface is named. Architect cannot design the flagging schema without this.
- **FR-9 / FR-10 (return window "same calendar date N periods back"):** "Rolling windows (1M–1Y) use the same calendar date N periods prior as the base." What is the rule when the base date is a non-trading day (weekend, holiday)? Prior trading day? Next trading day? This is a testable edge case that is not spec'd and affects validation against FactSet (SM-3).
- **NFR-2 (adjusted_close > close):** Stated as a data error flag, but the assumption tag is inline rather than indexed. The rule also breaks for securities that traded ex-dividend on a given day where the unadjusted close reflects a higher pre-div price — adjusted close can legitimately exceed unadjusted close for some adjustment methodologies. The flag logic may produce false positives unless clarified.

---

## Dimension 2: Substance (Testability)

**Verdict: PASS (with minor caveats)**

The PRD's consequence-per-FR structure is a genuine strength. Most consequences are concrete and testable. Specific observations:

- **FR-2:** "All identifier columns are indexed for performant lookup" is non-specific — performant relative to what? Since this is a local single-user database with a small dataset, this FR consequence is effectively untestable as written. Consider removing the performant qualifier or replacing it with a concrete threshold (e.g., lookup by ISIN returns in <100ms on expected dataset size).
- **FR-4:** "Non-null for at least 90% of active securities at launch" is testable and consistent with SM-5. Good.
- **FR-8:** "A run that completes with zero errors produces a single log record with `status = success`" is testable. But the FR does not specify what constitutes a "failure" vs. a "skip" for the securities_failed/skipped counter — a distinction that affects FR-3 (delisted) and FR-6 (already up-to-date). This ambiguity will surface during implementation.
- **SM-3:** "Within ±50 basis points" is a clear numeric threshold. However, A-4 notes that FactSet's sample data is price return, not total return — meaning SM-3's stated target table (`returns_total`) cannot currently be validated. The PRD acknowledges this as an assumption but does not provide an interim validation target for `returns_price`. This is a gap in the success metrics.
- **NFR-1 (±50% anomaly threshold):** Testable threshold. However, the consequence ("not written to the returns tables until manually reviewed or confirmed") implies a holding/staging mechanism that is not described anywhere in the FRs. Is there a `returns_staging` table? A flag column? This is a missing FR.

---

## Dimension 3: Strategic Coherence

**Verdict: PASS**

The PRD is internally coherent. The FIGI-as-universal-key design is consistently applied across all FRs, NFRs, and integration points. The FactSet-mirroring return format is a clear, well-motivated design choice that appears in the vision, FR-9/FR-10, and SM-3.

One minor tension worth noting:

- **yfinance ToS risk vs. production design intent.** The PRD explicitly notes yfinance as "Yahoo ToS risk" in the integration table but uses it as the sole v1 data source. FR-7 (source abstraction) and the EODHD-readiness design are the mitigation. The tension is acknowledged and resolved structurally — no contradiction.
- **A-5 vs. Open Question 4:** A-5 assumes yfinance adjusted close is sufficient to derive total return for v1. Open Question 4 asks whether yfinance adjusted close already reflects dividend reinvestment or requires separate dividend fetching. These are logically the same question — one is filed as a resolved assumption, the other as an open question. This is a minor inconsistency in document housekeeping.

---

## Dimension 4: Scope Integrity

**Verdict: PASS (with one finding)**

The non-goals list is comprehensive and well-curated. Most scope boundaries are crisp.

- **Data quality anomaly flagging** appears in §6.1 (In Scope) as "±50% single-day return threshold" and in NFR-1, but there is no corresponding FR that specifies how the hold/review mechanism works (see also Dimension 2 finding on NFR-1). The feature is in-scope but under-specified.
- **Open Question 1 (investable filter criteria)** is deferred to the universe module, which is appropriate. However, A-3 acknowledges the pipeline needs a seed list to start the initial load. The non-goals section does not explicitly state that "defining the investable filter criteria" is out of scope for sym — it only says "universe management" is out of scope. A clarifying sentence would close this.
- Nothing in the FRs appears to belong in the non-goals list — scope creep is not evident.

---

## Dimension 5: Completeness

**Verdict: CONCERN**

Several FRs implied by stated features and goals are absent or insufficiently specified:

- **Missing FR: Anomaly hold/staging mechanism.** NFR-1 blocks anomalous returns from being written to the returns tables pending review. There is no FR describing the staging state, how the researcher reviews and approves/rejects held records, or how they are eventually written or discarded. This is a behavioral gap that will require ad-hoc decisions during implementation.
- **Missing FR: FIGI flagging target surface (follow-on from FR-1).** FR-1's third consequence ("flags the record for manual review") has no home. The pipeline log table (FR-8) only tracks run-level aggregate counts. A `securities_review_queue` table or a flag column on the securities table is implied but not specified.
- **Missing FR: Schema documentation / column comments.** §6.1 lists "Schema documentation: column comments in PostgreSQL, DBeaver-compatible" as in-scope. There is no FR for this. For a one-person project it may be fine to leave as an implementation task, but it is an in-scope deliverable without a requirement.
- **Missing FR or NFR: Holiday/trading-day calendar.** FR-9/FR-10 define calendar-anchored windows (WTD, MTD, QTD, YTD) and FR-12 stores timezone per exchange. But there is no FR specifying how the pipeline determines whether a given date is a trading day for a given exchange. This is a non-trivial dependency for correct return computation (particularly for multi-market coverage) and for NFR-3 (flagging missing data on days the exchange was open).
- **Missing FR: Backfill progress state storage.** FR-6 requires resume-on-interrupt but does not specify where progress state is persisted (see also Dimension 1 finding).
- **Underdefined: EODHD source adapter.** FR-7 requires the EODHD adapter to be "EODHD-ready" and lists it as In Scope (§6.1), but §6.2 Out of Scope says "EODHD migration" is v1.1. The boundary between "adapter built" and "adapter activated" is described in prose but not in the FRs. If the adapter is to be built in v1, there should be a testable FR for it; if not, it should be removed from §6.1.

---

## Dimension 6: Assumptions

**Verdict: PASS (with minor finding)**

The assumption indexing discipline is good. Five assumptions are tagged inline and cross-referenced in §9 with section and FR anchors. The NFR-2 inline assumption tag is not indexed in §9 — this is a minor housekeeping gap.

**Hidden assumptions not tagged:**

- **Holiday/trading-day calendar source.** The PRD implicitly assumes a trading calendar is available (needed for NFR-3 and return window base-date logic) but neither names the source nor tags this as an assumption. `pandas_market_calendars` or `exchange_calendars` are common choices; the selection has downstream testability implications.
- **10-year history availability from yfinance.** FR-6 targets 10 years of history. yfinance provides up to ~10 years for most tickers, but coverage is patchy for non-US securities (particularly Brazil and smaller developed markets). This is a meaningful risk for the stated universe scope and is not tagged.
- **A-5 / Open Question 4 overlap.** As noted in Dimension 3, the treatment of yfinance adjusted close as total-return-sufficient is simultaneously a resolved assumption (A-5) and an open question (OQ-4). One of these should be removed or explicitly reconciled.

---

## Gate Recommendation

**PROCEED WITH FIXES**

The PRD is structurally sound, internally coherent, and well above average for a personal-project quant warehouse spec. The FIGI-key design, source abstraction, and FactSet-mirrored return methodology are well-motivated and consistently applied. The consequence-per-FR format is a genuine quality feature.

**Required fixes before architecture begins:**

1. **(FR-1 / FR-8)** Define the target surface for FIGI multi-candidate and lookup-failure flags — add a column, a table, or explicitly route to the pipeline log with a specified schema.
2. **(NFR-1)** Add an FR specifying the anomaly hold/staging mechanism: where held records live, how they are reviewed, and how they are promoted or discarded.
3. **(FR-9 / FR-10)** Specify the non-trading-day fallback rule for rolling window base dates (prior trading day vs. next trading day).
4. **(FR-6)** Specify where backfill progress state is persisted (database table vs. flat file vs. pipeline log).
5. **Add [ASSUMPTION] tag + §9 entry** for trading-day calendar source and for yfinance 10-year history coverage for non-US securities.

**Recommended (not blocking):**

- Reconcile A-5 and Open Question 4 — either close OQ-4 with the assumption or reopen A-5.
- Add a minimal FR or implementation note for schema documentation (column comments), since it appears in §6.1 In Scope.
- Clarify the EODHD adapter boundary: built-but-not-activated in v1 (needs a testable FR) vs. deferred to v1.1 (remove from §6.1).
- Index the NFR-2 inline assumption in §9.

---

*Review complete. No blocking defects; the identified gaps are resolvable with targeted FR additions and assumption tagging.*
