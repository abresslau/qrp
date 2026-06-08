---
title: "Brief-to-PRD Reconciliation — sym"
input: "brief-sym-2026-05-19/brief.md"
prd: "prd-sym-2026-05-19/prd.md"
created: 2026-05-20
---

# Brief-to-PRD Reconciliation: sym

## Summary

The PRD is substantially faithful to the brief and in several areas materially expands it (return window spec, NFR layer, glossary, assumptions index). The gaps below are qualitative signals, constraints, and intent statements from the brief that did not make it into the PRD's requirement or risk surfaces.

---

## Gaps — Brief Content Not Reflected in the PRD

### GAP-1: yfinance ToS Risk Not Surfaced as a Formal Risk or NFR

The brief explicitly states: *"Yahoo ToS that prohibits commercial automated access."* It categorizes this as the primary data sourcing risk accepted for the development phase with a documented migration plan. The PRD mentions yfinance's Yahoo ToS risk in the Integration table (a note in the Dependencies section) but does not elevate it to a named risk, a gating condition for the EODHD migration, or a non-functional constraint. There is no requirement or policy stating that yfinance must not be used once the system moves to production use at a firm.

**Recommendation:** Add a risk item or NFR along the lines of: "yfinance must not be used as the active data source once sym is in production use at a firm. EODHD (or equivalent) migration is a prerequisite for that transition." This could also be a gating condition attached to the EODHD migration item in §6.2.

---

### GAP-2: Brazil-Specific Corporate Action Complexity (IOE) — Risk Understated

The brief dedicates a named "Brazil-specific complexity" risk block to two distinct issues: (1) IOE quasi-dividends requiring correct adjusted-price treatment, and (2) Brazilian share classes (ON/PN) requiring careful OpenFIGI mapping to avoid conflating distinct instruments. The PRD handles IOE at the requirement level (FR-5, FR-10 consequences) and mentions share classes (FR-4.1 description). However:

- The brief explicitly flags that *open-source providers handle both inconsistently* — this is a data quality risk specific to Brazil that is not reflected as a validation rule, pipeline check, or NFR.
- There is no testable consequence in the PRD that catches IOE being omitted or mishandled by the source (e.g., a known Brazilian dividend-payer used as a validation fixture).
- The share class mapping risk (PETR3 vs PETR4 receiving the same FIGI) is mentioned in the Glossary but not in any FR consequence or data quality check.

**Recommendation:** Add a Brazil-specific data quality NFR or FR consequence: (a) a validation fixture using a known IOE-paying security to confirm adjusted prices reflect IOE, and (b) a FIGI mapping check ensuring ON/PN share classes resolve to distinct CompositeFIGIs.

---

### GAP-3: "Technical Debt Accumulation" Framing — Cost-of-Delay Rationale Dropped

The brief contains a substantive argument: *"A security master built on unstable identifiers accrues technical debt that becomes expensive to unwind once downstream tools depend on it. The earlier the identity layer is established correctly, the less it costs."* This is the core justification for building sym now rather than later, and it frames the FIGI-first architecture as a cost-minimization decision, not just a technical preference.

The PRD's Vision (§1) restates the FIGI rationale but frames it as a convenience ("every other module inherits a stable, vendor-neutral key for free") rather than a risk-avoidance argument. The economic argument — that delaying or compromising the identity layer is costly to unwind — is absent.

**Recommendation:** This belongs either in the Vision (§1) or as a brief sentence in §6 MVP Scope rationale. It is relevant to any future decision to defer FIGI assignment or accept a shortcut identifier (e.g., ticker-keyed intermediate tables).

---

### GAP-4: Quant Research Tool Dependency — Stability Contract Not Formalized

The brief names the Quant Research Tool as a secondary consumer and states: *"sym's schema and query interface become the contract the research platform depends on. Stability of the identity layer is what makes the downstream tool's results reproducible over time."* The PRD includes NFR-4 (securities table schema is a public contract for downstream modules) but does not:

- Name the Quant Research Tool explicitly as a dependent consumer.
- State that schema stability is what makes downstream results reproducible (a causal claim, not just a policy).
- Address the query interface contract beyond the table schema (e.g., are views or stable column names part of the contract?).

**Recommendation:** Strengthen NFR-4 to explicitly name known downstream consumers (Quant Research Tool, universe module) and tie schema stability to reproducibility of downstream research outputs, not just "requires a migration plan."

---

### GAP-5: Survivorship Bias — Accepted Limitation Not Flagged as Researcher Risk

The brief names survivorship bias as an accepted limitation with a clear description: *"Historical analysis has survivorship bias for periods where delistings are not captured."* The PRD lists "survivorship-bias-free historical universe" as a Non-Goal (§5) and an out-of-scope item (§6.2), which is correct. However, there is no user-facing note or operational guidance stating that researchers using sym's historical data should be aware that cross-sectional return analysis on long lookback windows is subject to survivorship bias.

**Recommendation:** Add a brief note in §5 Non-Goals or §7 Success Metrics that flags this as a known analytical limitation that researchers must account for when interpreting factor backtest results. This is information that belongs in the PRD as a user guidance note, not just in the architecture addendum.

---

## Items Correctly Carried Forward

The following brief content is well-represented in the PRD:

- **FIGI-first identity architecture** — fully realized in §4.1, Glossary, Vision (§1), and NFR-4.
- **Universe scope** — US, developed markets, Brazil, 5k–10k securities, 10Y history — covered in §6.1 and §4.2.
- **yfinance rate limiting (~950 tickers/session)** — captured in Open Questions (OQ-3) and Integration table.
- **EODHD as production migration target (~$20/month)** — noted in §6.2 and Integration table.
- **GICS licensing limitation** — A-1 assumption, FR-4, §6.2 out-of-scope item.
- **Adjusted price sanity check (±50% single-day return)** — NFR-1 and SM success metric.
- **Daily unattended pipeline with anomaly surfacing** — FR-8, SM-2.
- **DuckDB + Parquet → PostgreSQL architecture decision** — PostgreSQL selected in §6.1; DuckDB/Parquet decision is correctly placed in addendum.
- **Vendor independence / source abstraction** — FR-7 fully captures this intent with testable consequences.
- **IOE as dividend for return purposes** — FR-5, FR-10 consequences.
- **Cross-sectional query as primary researcher workflow** — UJ-1, SM-4.
- **Out-of-scope items** — intraday, fundamentals, options/futures/ETFs/crypto, additional EM, real-time — all reflected in §5 Non-Goals.

---

## Brief Content That Belongs in Addendum Rather Than PRD

The following brief content is informational context or rationale, not a product requirement. It is appropriately omitted from the PRD body; if not already in addendum.md, it should be added there.

- **Commercial alternative pricing context** (FactSet/Bloomberg being enterprise-priced) — background rationale, not a requirement. Belongs in addendum as market context or "why not X" section.
- **DuckDB + Parquet as initial storage layer** — an architecture decision with tradeoffs (suited to analytical query patterns, batch writes, heavy cross-sectional reads). The PRD correctly moves to PostgreSQL without explaining the prior evaluation. The DuckDB rationale and the migration rationale belong in addendum.
- **"sym becomes the integration target when a commercial license is acquired"** — the long-run vision for vendor onboarding. Appropriately a Vision statement in the PRD, but the detailed argument (FIGI mapping ensures data drops cleanly without rebuild) is addendum-level detail.
- **yfinance session count (~950/session) as a documented limitation** — the specific number is implementation detail. The PRD references it; the retry/session strategy design belongs in addendum or OQ-3 resolution.
