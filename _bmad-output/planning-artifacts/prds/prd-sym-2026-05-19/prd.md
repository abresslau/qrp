---
title: "sym — Global Equity Security Master & Market Data"
status: final
created: 2026-05-19
updated: 2026-06-05
---

# PRD: sym — Global Equity Security Master & Market Data

## 0. Document Purpose

This PRD defines the functional and non-functional requirements for **sym**, the security master and market data module of a personal quantitative investment data warehouse. The primary audience is the builder and any future architecture reviewers. It uses a Glossary-anchored vocabulary, features grouped with globally-numbered FRs, and inline `[ASSUMPTION]` tags indexed in §9.

Inputs: product brief at `_bmad-output/planning-artifacts/briefs/brief-sym-2026-05-19/brief.md`. Architecture decisions and supporting research are in `addendum.md`. Downstream modules (universe, alt data, research) are out of scope for this PRD and will be specified separately.

---

## 1. Vision

sym is the identity and market data spine of a personal quantitative investment data warehouse. It answers two questions reliably — *what is this security?* and *how has it performed?* — for every investable equity in the US and developed markets.

Every security is anchored to a **CompositeFIGI**: an open, permanent identifier that survives renames, redomiciles, and ticker changes. This FIGI is the universal join key across the warehouse — the universe module, alt data, research outputs, and portfolio construction layer all reference it. A stable identity layer means every downstream module inherits a vendor-neutral key without extra work.

sym's market data layer mirrors the return format of professional data services (FactSet, Bloomberg): pre-computed price and total return matrices across 18 standard lookback windows. Downstream research tools query performance directly rather than recomputing from raw prices. When a commercial data license is acquired, sym is already structured to receive it without a rebuild.

A ticker-based security master breaks silently when companies rename or relist. Unwinding that debt after the Quant Research Tool, universe module, and research layer all depend on sym is expensive. FIGI-first is the risk-avoidance decision.

Beyond personal research, sym is built with the option of being productized — distributed or licensed to other independent quant practices. The commercial path is not the v1 target. But design choices that would make sym credible to a future buyer — a stable, documented schema treated as a public contract (NFR-4); data sourcing abstracted from any vendor including the buyer's (FR-7); classifications chosen to survive licensing constraints (FR-4) — are made now, not retrofitted later.

---

## 2. Target User

### 2.1 Primary Persona

Andre: quantitative researcher and sole developer. Background in professional investment management using FactSet and Snowflake; now building a personal-scale equivalent with open-source tooling. Comfortable with SQL, Python, and DBeaver. Building infrastructure for his own research today, with optionality preserved for later productization or distribution to other independent quant practices.

### 2.2 Jobs To Be Done

- Retrieve clean, FIGI-keyed price and return history for any equity in the investable universe without resolving data identity issues first
- Run cross-sectional return analysis across the full universe using pre-computed return windows
- Validate data quality against known benchmarks (FactSet sample data)
- Add new equities to the security master without disrupting existing records
- Swap the underlying data source (yfinance → EODHD) without changing the schema or downstream queries

### 2.3 Key User Journeys

- **UJ-1. Researcher pulls cross-sectional returns for a factor screen.** Opens DBeaver, queries the returns table for all securities in a given date, retrieves 1Y total return and market cap, exports to Python for analysis. Expects no null FIGIs, consistent return window definitions, and local currency values.

- **UJ-2. Pipeline runs overnight, researcher checks quality in the morning.** Daily batch completes unattended. Researcher opens a pipeline log or status table to confirm all securities updated, no anomalous returns flagged. No manual intervention required for a clean run.

- **UJ-3. Researcher onboards a new equity.** Queries OpenFIGI for the FIGI, adds the record to the securities table, and the next pipeline run automatically backfills available price and return history.

---

## 3. Glossary

- **CompositeFIGI** — Bloomberg-originated open-standard permanent identifier for a security across all exchanges where it trades. The primary key of the sym security master. Survives ticker changes, SEDOL reassignments, and exchange transfers. Issued and maintained via the OpenFIGI API.
- **ShareClassFIGI** — A FIGI scoped to a specific share class on a specific exchange (e.g., GOOG vs GOOGL on NASDAQ for Alphabet's dual share classes). Stored as a cross-reference; CompositeFIGI is the master key.
- **Price Return (PR)** — Return from price change only; dividends excluded. Equivalent to FactSet `dividend_adjust=PRICE`.
- **Total Return (TR)** — Return from price change plus dividends reinvested on ex-date (gross, no withholding tax). Equivalent to FactSet `dividend_adjust=EXDATE_C`.
- **Return Window** — A defined lookback period for computing a return. See §4.3 for the full set. Calendar-anchored windows (WTD, MTD, QTD, YTD) measure from prior period-end. Rolling windows (1M–1Y) use the same calendar date N periods back. Annualized windows (2Y–30Y, IPO) express as CAGR.
- **Adjusted Close** — Closing price retroactively adjusted for all splits and dividends, making the series consistent and comparable across all historical dates.
- **OHLCV** — Open, High, Low, Close (unadjusted), Volume. The raw daily price record.
- **Investable Universe** — A named, criteria-based subset of securities (e.g., filtered by market cap and exchange). Managed by the separate universe module; sym does not enforce universe membership.
- **Pipeline** — The scheduled Python ETL process that fetches, validates, and writes market data to sym daily.
- **Data Source** — The provider supplying raw price and corporate action data. Currently yfinance (dev); EODHD (production target). The schema is source-agnostic.
- **GICS** — Global Industry Classification Standard. Hierarchical sector/industry taxonomy maintained by MSCI and S&P. sym uses GICS-approximated classifications from open sources in v1.

---

## 4. Features

### 4.1 Instrument Identity Management

**Description:** The security master is a FIGI-keyed registry of all equities sym tracks. Each record maps a CompositeFIGI to its cross-reference identifiers (ticker, SEDOL, CUSIP, ISIN, exchange MIC) and reference attributes (name, country, currency, exchange, GICS classification). CompositeFIGI is immutable once assigned; all other fields may be updated. Multi-class equities (e.g., GOOG/GOOGL) are stored as distinct records that may share a company-level grouping. Realizes UJ-1, UJ-3.

**Functional Requirements:**

#### FR-1: FIGI Assignment via OpenFIGI API
The pipeline can look up and assign a CompositeFIGI for any equity given one or more input identifiers (ticker + exchange MIC, ISIN, SEDOL, or CUSIP) by querying the OpenFIGI API.

**Consequences (testable):**
- Given a valid ticker and exchange MIC, the system returns a CompositeFIGI and writes it to the securities table.
- Given an identifier that returns no FIGI match, the system logs the failure with `review_status = 'no_figi_found'` in the securities review queue (FR-14) and skips the record without halting.
- Given an identifier that returns multiple FIGI candidates, the system writes the candidates to the review queue with `review_status = 'ambiguous_figi'` and does not auto-assign.
- For multi-class equities (e.g., Alphabet GOOG/GOOGL, Berkshire BRK.A/BRK.B), the pipeline verifies that distinct share classes of the same issuer receive distinct CompositeFIGIs. A single FIGI assigned to multiple classes is flagged as `review_status = 'share_class_conflict'`.

#### FR-2: Cross-Reference Identifier Storage
Each security record stores all known identifiers as queryable columns: CompositeFIGI (PK), ShareClassFIGI, ticker, exchange MIC, ISIN, CUSIP, SEDOL, local exchange code, and country ISO code.

**Consequences (testable):**
- A query on any cross-reference identifier (e.g., ISIN) returns the corresponding CompositeFIGI.
- All identifier columns are indexed for performant lookup.

#### FR-3: Security Record Lifecycle
The security master records a lifecycle `status` (`active`/`delisted`/`suspended`) and `delist_date` for each security. A delisted security retains its CompositeFIGI and full history; only the status changes.

**Consequences (testable):**
- A security delisted after sym ingests it is marked `status = 'delisted'` with a `delist_date`; its price and return history is preserved.
- Queries can filter active-only or include delisted securities explicitly.

#### FR-4: GICS Classification Storage
Each security stores GICS sector, industry group, industry, and sub-industry codes and labels. Source is financedatabase (open-source, GICS-approximated) for v1. `[ASSUMPTION: GICS-approximated classifications from financedatabase are sufficient for v1 factor research; licensed GICS deferred.]`

**Consequences (testable):**
- All four GICS levels are present and non-null for at least 90% of active securities at launch.
- GICS fields are queryable and indexed.

---

### 4.2 Market Data Pipeline

**Description:** The pipeline fetches daily OHLCV and adjusted close data for all active securities and writes it to the prices table. It operates in three modes: dev load (small set), full historical backfill (10 years, resumable across sessions), and daily incremental delta. The data source layer is abstracted so that swapping yfinance for EODHD requires only a configuration change — no schema or query changes. Realizes UJ-2, UJ-3.

**Functional Requirements:**

#### FR-5: Adjusted Price Ingestion
For each active security, the pipeline stores daily OHLCV (unadjusted) and adjusted close, sourced from the configured data provider, in local currency.

**Consequences (testable):**
- Each price record contains: CompositeFIGI, date, open, high, low, close (unadjusted), adjusted\_close, volume, currency code, source identifier.
- Adjusted close reflects all splits and dividends applied retroactively.
- No price record exists without a corresponding CompositeFIGI in the securities table (FK constraint enforced).

#### FR-6: Three-Phase Load Support
The pipeline supports three operating modes selectable at runtime:
- **dev**: load a small named subset (e.g., list of FIGIs passed as input) for schema validation
- **backfill**: load full history for all active securities up to 10 years; designed to run across multiple sessions with progress tracking so interrupted runs resume without re-fetching completed securities
- **delta**: fetch only dates since the last successful run for each security

**Consequences (testable):**
- In delta mode, securities already up-to-date are skipped without API calls.
- A backfill interrupted mid-run resumes from the last completed security, not from scratch. Progress is tracked in a `pipeline_backfill_progress` table (one row per security, columns: CompositeFIGI, status, last\_date\_fetched, updated\_at).
- Dev mode completes in under 5 minutes for ≤50 securities.

#### FR-7: Source Abstraction Layer
The data source (yfinance, EODHD, or future providers) is configured via a single setting. All source-specific logic (API calls, authentication, field mapping) lives in a source adapter module. The prices table schema and all downstream queries are source-agnostic.

**Consequences (testable):**
- Swapping `source=yfinance` to `source=eodhd` in configuration requires zero changes to the prices table schema or the returns computation logic.
- The source adapter for each provider implements a common interface: `fetch_ohlcv(figi, start_date, end_date) → DataFrame`.
- If sym is ever distributed to other practices, the same adapter abstraction lets each deployment plug in a buyer-supplied licensed feed (EODHD, Bloomberg, FactSet, etc.) without changes to the security master or returns schemas.

#### FR-8: Pipeline Run Logging
Each pipeline run writes a log record containing: run timestamp, mode (dev/backfill/delta), securities attempted, securities succeeded, securities failed/skipped, and any anomalies detected.

**Consequences (testable):**
- A pipeline log table is queryable in DBeaver.
- A run that completes with zero errors produces a single log record with `status = success`.
- A run with any failures produces a log record with `status = partial` and a count of failures.

---

### 4.3 Returns Computation

**Description:** After each pipeline run, the returns computation step calculates and stores pre-computed price return (PR) and total return (TR) for all 18 standard windows, per security per date. Results are stored in two tables (`returns_price` and `returns_total`) with identical schemas; return type is explicit at the table level. Window definitions match FactSet's return snapshot methodology (see Glossary and Addendum A-2). Where history is insufficient for a window, NULL is stored. Realizes UJ-1, UJ-2.

**Functional Requirements:**

#### FR-9: Price Return Matrix
The `returns_price` table stores, for each (CompositeFIGI, date) pair, the price return for all 18 windows: 1D, WTD, MTD, QTD, YTD, 1M, 3M, 6M, 9M, 1Y, 2Y\_ANN, 3Y\_ANN, 5Y\_ANN, 10Y\_ANN, 20Y\_ANN, 30Y\_ANN, IPO\_ANN.

**Consequences (testable):**
- Calendar-anchored windows (WTD, MTD, QTD, YTD) use the prior period-end close as the base.
- Rolling windows (1M–1Y) use the same calendar date N periods prior as the base.
- Annualized windows (2Y+) express as compound annual growth rate (CAGR), not cumulative return.
- IPO\_ANN uses the first available closing price as the base (not the offer price).
- Rolling window base dates that fall on a weekend or market holiday use the last available trading day on or before that calendar date.
- Where fewer than the required trading days of history exist, the window value is NULL.
- Values are stored as decimals (e.g., 0.0850 = 8.50%), not percentage strings.

#### FR-10: Total Return Matrix
The `returns_total` table stores total return (price + dividends reinvested on ex-date, gross) for the same 18 windows and the same (CompositeFIGI, date) pairs as `returns_price`. Same schema and NULL rules.

**Consequences (testable):**
- For a security with no dividends in a period, `returns_total` and `returns_price` values for that window are equal.
- For a dividend-paying security over a multi-year window, `returns_total` > `returns_price` (testable with a known dividend payer).

#### FR-11: Incremental Return Computation
On a delta pipeline run, only return windows affected by new price data are recomputed. Windows anchored to periods with no new data are not rewritten.

**Consequences (testable):**
- A daily delta run recomputes 1D, WTD, MTD, QTD, YTD, and rolling windows whose base date is within the new data range.
- Annualized multi-year windows are recomputed daily (the CAGR endpoint changes each day).

---

### 4.4 Data Review & Anomaly Staging

**Description:** Two review surfaces catch data quality exceptions before they reach the returns tables. The securities review queue holds FIGI assignment issues. The returns anomaly staging table holds price return outliers pending manual confirmation before promotion. Realizes UJ-2.

**Functional Requirements:**

#### FR-14: Securities Review Queue
A `securities_review_queue` table stores records that require manual inspection before entering or updating the master securities table. Each row contains: CompositeFIGI or raw input identifier, review\_status (e.g., `no_figi_found`, `ambiguous_figi`, `share_class_conflict`), source input, candidate values if multiple, created\_at, resolved\_at, resolved\_by.

**Consequences (testable):**
- Records in the queue are visible and queryable in DBeaver.
- Resolving a queue item (marking `resolved_at`) triggers inclusion or rejection of the security on the next pipeline run.
- The pipeline does not re-attempt auto-resolution for records already in the queue until manually resolved.

#### FR-15: Returns Anomaly Staging
A `returns_anomaly` staging table holds computed return records that fail the ±50% single-day threshold (NFR-1) before manual review. Each row contains: CompositeFIGI, date, window, return\_type (PR/TR), computed value, anomaly\_reason, status (`pending_review`, `approved`, `rejected`).

**Consequences (testable):**
- A flagged return is written to `returns_anomaly` with `status = 'pending_review'` and is NOT written to `returns_price` or `returns_total`.
- Setting `status = 'approved'` causes the next pipeline run to promote the record to the appropriate returns table.
- Setting `status = 'rejected'` leaves the return NULL in the returns tables and logs the rejection.
- The pipeline log for a run containing anomalies shows `status = 'partial'` with a count of pending anomalies.

---

### 4.5 Reference Data

**Description:** Supporting metadata stored alongside the security master for filtering, grouping, and joining in downstream research queries. Loaded statically at setup with periodic refresh. Realizes UJ-1.

**Functional Requirements:**

#### FR-12: Exchange and Market Reference Table
A reference table maps exchange MIC codes to exchange name, country, country ISO code, market timezone, and currency. Covers all exchanges in scope for v1. `[ASSUMPTION: A curated static list of ~30 major developed-market exchanges is sufficient for v1.]`

**Consequences (testable):**
- Every security's exchange MIC resolves to a row in the exchange reference table (FK).
- Timezone is stored per exchange to support correct business-day calculations.

#### FR-13: Currency Reference Table
A reference table of ISO 4217 currency codes covering all currencies of securities in scope. Used to label price and return records.

**Consequences (testable):**
- Every price and return record's currency code resolves to the currency reference table.

---

## 5. Non-Goals (Explicit)

- **Universe management.** sym does not define, store, or enforce investable universe membership. That is the universe module's responsibility. sym provides the FIGI-keyed security master that the universe module queries against.
- **Custom UI or dashboard.** No web interface, charting tool, or custom visualization in v1. DBeaver is the intended query/exploration surface.
- **USD or cross-currency normalization.** Prices and returns are in local currency only. Currency conversion is the downstream consumer's responsibility.
- **Real-time or intraday data.** sym is daily EOD only.
- **Fundamental data.** No income statement, balance sheet, earnings, or guidance data.
- **Corporate actions history table.** Adjusted prices account for corporate actions; a structured event-by-event actions log is not stored in v1.
- **Survivorship-bias-free historical universe.** Delisted securities already in sym are retained, but free data sources do not guarantee systematic coverage of all historical delistings. **Researcher impact:** cross-sectional analysis beyond 2–3 years will systematically overstate average returns. Factor backtests must account for this explicitly. Resolution requires a licensed survivorship-corrected dataset.
- **Withholding tax netting in total return.** Total return is gross (pre-tax). Net-of-withholding total return requires licensed data.
- **Options, futures, ETFs, fixed income, crypto.**
- **Emerging markets in v1** (including Brazil — deferred to v1.x; see §6.2).
- **REST API or any programmatic service layer in v1.** sym is a local PostgreSQL database accessed via direct SQL.
- **Multi-user access, authentication, or tenancy in v1.**

---

## 6. MVP Scope

### 6.1 In Scope

- PostgreSQL database, local deployment
- Securities table: FIGI-keyed, cross-reference identifiers, GICS, exchange, country, currency metadata
- OpenFIGI integration for FIGI assignment
- Prices table: daily OHLCV + adjusted close, local currency, yfinance as source
- Returns tables: `returns_price` and `returns_total`, 18 windows each, daily computation
- Pipeline: dev load, full backfill (multi-session), daily delta modes
- Source abstraction layer (yfinance in v1, EODHD-ready)
- Pipeline run log table
- Data quality anomaly flagging (±50% single-day return threshold)
- Universe coverage: US (NYSE, NASDAQ, NYSE Arca), developed markets (major exchanges)
- Target security count: ~4,000–8,000 (investable filter criteria defined at implementation; revised down from 5k–10k after Brazil removal on 2026-05-20)
- History depth: 10 years EOD
- Schema documentation: column comments in PostgreSQL, DBeaver-compatible

### 6.2 Out of Scope for MVP

- EODHD migration (v1.1 — triggered before any commercial activity per NFR-8: distribution to third parties, paid analysis derived from sym, or firm production use) `[NOTE FOR PM: budget ~$20/month; migration requires only source adapter change]`
- Universe module (separate PRD)
- Alt data, research, portfolio construction modules (future PRDs)
- REST API (v2 — prerequisite for Quant Research Tool integration)
- Custom visualization UI (deferred indefinitely unless DBeaver is insufficient)
- Corporate actions history table (v2 — useful for auditing return adjustments)
- Licensed GICS classifications (future — when MSCI/S&P license acquired)
- USD-normalized returns (future — if cross-currency factor analysis requires it)
- Survivorship-bias-free data (requires paid survivorship-corrected source)
- Emerging markets (including Brazil) — deferred to v1.x. Adding Brazil back later reinstates the IOE handling and ON/PN-style risk content removed from this PRD on 2026-05-20.

---

## 7. Success Metrics

**Primary**
- **SM-1:** All active securities in scope have a non-null CompositeFIGI. Target: 100%. Validates FR-1, FR-2.
- **SM-2:** Daily delta pipeline runs unattended to completion with `status = success` for ≥95% of calendar trading days in the first 30 days of production operation. Validates FR-6, FR-8.
- **SM-3:** `returns_total` 1Y value for a sample of 10 US securities matches a FactSet reference value within ±50 basis points. Validates FR-9, FR-10.
- **SM-6:** sym's price-return and total-return values for the ~50 adversarial benchmark names (deliberately chosen to span splits, reverse splits, special and stock dividends, spin-offs, multi-currency, ADRs, and at least one delisting) match an independent published reference series across all 18 return windows, within a per-window tolerance — tight (~5 bps) for clean names, explicitly looser for corporate-action-heavy names. This is a **regression gate that runs on every change to the returns engine**, not a one-time launch check: any returns-engine change that breaks a previously-passing benchmark fails the gate. Validates FR-9, FR-10, FR-11; generalizes SM-3 from a 1Y/10-name spot-check to a full-window correctness gate. (Reference series per [A-4]: an independent TR/PR source must be pulled separately, since the existing FactSet sample is price-return only.)

**Secondary**
- **SM-4:** Cross-sectional return query for all active securities on a given date executes in under 10 seconds in DBeaver on local hardware. Validates FR-9, FR-10.
- **SM-5:** GICS classification present for ≥90% of active securities at launch. Validates FR-4.

**Counter-metrics (do not optimize)**
- **SM-C1:** Do not optimize completeness at the cost of accuracy. A security with missing adjusted-close data stays NULL rather than being forward-filled silently. Counterbalances SM-1 and SM-2.
- **SM-C2:** Do not widen SM-6 tolerances to force a pass. A failing benchmark is a signal to fix the returns engine (or to justify and document the corporate-action complexity), never to relax the gate. Counterbalances SM-6.

---

## 8. Open Questions

1. **Investable filter criteria.** What is the exact rule for including a security in the ~5k–10k target universe? (minimum market cap, minimum ADV, exchange whitelist?) Deferred to universe module, but the pipeline needs a seed list to start.
2. ~~**Developed market exchange list.**~~ **Resolved:** All major developed market exchanges are in scope. Implementation defines the specific exchange list for FR-12.
3. **yfinance session management (dev-only per NFR-8).** At 4k–8k tickers, the backfill will hit Yahoo rate limits (~950/session). What retry and session strategy is acceptable for the development phase? (Affects FR-6 backfill design. No longer a commercial-path concern — EODHD migration before any commercial activity eliminates this constraint.)
4. **GICS refresh cadence.** GICS classifications change when companies are reclassified. Should the reference data be refreshed quarterly, or is a one-time load sufficient for v1?
5. **IPO base price source.** For the IPO\_ANN return window, yfinance provides first available close. For very recent IPOs with limited history, should IPO\_ANN be NULL until a minimum history threshold is met?

---

## 9. Assumptions Index

- **[A-1]** §4.1 FR-4: GICS-approximated classifications from financedatabase are sufficient for v1 factor research. Licensed GICS deferred.
- **[A-2]** §4.4 FR-12: A curated static list of ~30 major developed-market exchanges covers the full v1 scope.
- **[A-3]** §6.1: The investable universe filter (criteria for 5k–10k security selection) is defined at implementation time, not in this PRD. The pipeline requires a seed list to begin the initial load.
- **[A-4]** §7 SM-3: FactSet CSV sample (`Untitled 34_2026-05-19-2046.csv`) uses price return (FactSet default). Total return validation will require a separately pulled FactSet TR reference.
- **[A-5]** §4.3 FR-10: yfinance adjusted close is treated as sufficient to derive total return for v1. yfinance's adjusted close folds in split and dividend adjustments; however, accuracy for non-US securities is not guaranteed. If dividend accuracy proves insufficient during dev-phase validation, EODHD migration (Out of Scope v1) is the resolution path.
- **[A-6]** §4.3 FR-9/FR-10: yfinance provides 10-year daily history for most US equities. Coverage depth for non-US developed market securities may be shorter. Windows requiring history beyond available data are NULL — this is expected and correct behavior, not a pipeline failure.

---

## 10. Cross-Cutting NFRs

**Data Quality**
- NFR-1: A single-day price move exceeding ±50% must be flagged for review and must not contribute to published return values until the underlying price is reviewed (confirmed as a real event or corrected). Flagging must **not** halt ingestion: the suspect price is recorded and annotated, never silently dropped, and a legitimate large move (e.g. a biotech binary event) is confirmed rather than discarded. Once reviewed, the affected security's returns are (re)computed and published. *(Two-stage semantics — annotate the suspect price at ingestion, gate its returns at the point they would be published. Mechanism detail lives in the architecture's D2 decision.)*
- NFR-2: Internal consistency between any stored adjusted price series and its unadjusted source is validated — an adjusted value that exceeds its unadjusted close, or otherwise cannot be reproduced from the stored raw price plus explicit corporate-action factors, is flagged as a data error. `[NOTE: Under the three-layer returns model the system stores raw prices plus explicit factors and derives adjusted values, rather than storing a vendor adjusted_close; this NFR is the determinism/reproducibility check on that derivation.]`
- NFR-3: Missing data (no price for a trading day where the exchange was open) is logged per security; no silent forward-filling.

**Schema Stability**
- NFR-4: The `securities` table schema (column names, types, and CompositeFIGI primary key) is a public contract for downstream warehouse modules — specifically the universe module and the Quant Research Tool. Breaking changes invalidate reproducibility of any research output joined against sym and require a migration plan and versioned schema change.
- NFR-5: All tables include `created_at` and `updated_at` audit timestamps.

**Reliability**
- NFR-6: A failed pipeline run (any exception) does not leave partial writes committed. Either all records for a security's daily update are committed or none are (per-security transaction boundary).

**Observability**
- NFR-7: The pipeline log table (FR-8) is the primary operational monitoring surface. No external logging infrastructure required in v1.

**Data Source Risk**
- NFR-8: yfinance is the v1 data source for **personal-research use only**. Migration to a licensed source (EODHD or equivalent) is a hard precondition for **any commercial activity** — including (a) distribution of sym or its data to third parties, (b) paid analysis derived from sym, or (c) production use at a firm where research outputs inform investment decisions. Yahoo's ToS prohibits commercial automated access; yfinance must not be the active data source past that gate.

---

## 11. Integration and Dependencies

| Dependency | Role | Notes |
|---|---|---|
| OpenFIGI API | FIGI assignment (FR-1) | Free, no subscription. 25k mappings/min with API key. |
| yfinance | Price data source, v1 (FR-5) | Dev/proto only. Yahoo ToS risk; rate limits at ~950 tickers/session. |
| EODHD | Price data source, production target | ~$20/month EOD All World plan. Source adapter to be built but not activated in v1. |
| financedatabase (GitHub) | GICS-approximated metadata (FR-4) | Free, open source. Static load at setup. |
| PostgreSQL | Primary database | Local deployment. DBeaver as query/explore interface. |
| Universe module (future) | Queries sym via CompositeFIGI FK | sym is upstream; universe module is a downstream consumer. |
| Quant Research Tool (future) | Queries returns and price data | REST API layer (v2) is the planned integration surface. |
