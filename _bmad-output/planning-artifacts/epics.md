---
stepsCompleted: [1, 2, 3, 4]
status: complete
completedAt: 2026-06-06
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-sym-2026-05-19/prd.md
  - _bmad-output/planning-artifacts/architecture.md
---

# sym - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for **sym** (Global Equity Security Master + Market Data + Returns warehouse, Module 1 of a personal quant research warehouse), decomposing the requirements from the PRD and Architecture into implementable stories. There is no UX Design input — sym is a headless data warehouse whose query surface is DBeaver.

## Requirements Inventory

### Functional Requirements

- **FR-1 — FIGI assignment via OpenFIGI:** Assign an immutable CompositeFIGI from one or more input identifiers (ticker+MIC, ISIN, SEDOL, CUSIP). No match → review queue (`no_figi_found`); multiple candidates → `ambiguous_figi` (no auto-assign); distinct share classes (GOOG/GOOGL, BRK.A/BRK.B) must receive distinct FIGIs, a shared FIGI → `share_class_conflict`. Never halts on failure.
- **FR-2 — Cross-reference identifier storage:** Store CompositeFIGI (PK), ShareClassFIGI, ticker, MIC, ISIN, CUSIP, SEDOL, local code, country ISO as queryable, indexed columns; a lookup on any identifier returns the CompositeFIGI.
- **FR-3 — Security record lifecycle:** Record lifecycle `status` (`active`/`delisted`/`suspended`) + `delist_date`; a delisted security retains its FIGI and full price/return history (status-only change); queries can filter active-only (`status='active'`) or include delisted.
- **FR-4 — GICS classification storage:** Store all four GICS levels (sector/industry-group/industry/sub-industry) codes + labels from financedatabase; ≥90% coverage of active securities at launch; queryable and indexed.
- **FR-5 — Adjusted price ingestion:** Per active security, ingest daily OHLCV + adjusted close in local currency, FK-bound to `securities`. *(Architecture reconciliation: store raw OHLCV + explicit corporate-action factors and derive adjusted via `v_prices_adjusted`; never store a vendor `adjusted_close` — see AR-7/AR-6.)*
- **FR-6 — Three-phase load support:** Runtime-selectable `dev` / `backfill` (resumable across sessions, per-security progress) / `delta` (only dates since last success); up-to-date securities skipped in delta; interrupted backfill resumes from last completed security.
- **FR-7 — Source abstraction layer:** A single config setting selects the source; all source-specific logic lives in an adapter implementing `fetch_ohlcv(figi, start, end)`; schema and downstream queries are source-agnostic; buyer-pluggable for any future distribution.
- **FR-8 — Pipeline run logging:** Each run writes a log record (timestamp, mode, attempted, succeeded, failed/skipped, anomalies); `status = success` (0 errors) or `partial` (with failure count); queryable in DBeaver.
- **FR-9 — Price return matrix:** PR for all 18 windows per (FIGI, date): 1D, WTD, MTD, QTD, YTD, 1M, 3M, 6M, 9M, 1Y, 2Y_ANN, 3Y_ANN, 5Y_ANN, 10Y_ANN, 20Y_ANN, 30Y_ANN, IPO_ANN. Calendar-anchored use prior period-end base; rolling use same-calendar-date N periods prior (weekend/holiday → last trading day on/before); 2Y+ as CAGR; IPO_ANN base = first available close; insufficient history → NULL; values stored as decimals.
- **FR-10 — Total return matrix:** TR (dividends reinvested on ex-date, gross) for the same 18 windows / same (FIGI, date) pairs; same schema and NULL rules; TR=PR when no dividends; TR>PR for a multi-year dividend payer.
- **FR-11 — Incremental return computation:** On delta, recompute only windows affected by new price data; multi-year CAGR endpoints recomputed daily (endpoint moves each day).
- **FR-12 — Exchange/market reference table:** Map MIC → exchange name, country, country ISO, market timezone, currency; FK from every security's MIC; timezone stored per exchange for business-day math.
- **FR-13 — Currency reference table:** ISO-4217 currency codes; FK from every price and return record's currency.
- **FR-14 — Securities review queue:** `securities_review_queue` holds FIGI-assignment issues (`no_figi_found`, `ambiguous_figi`, `share_class_conflict`) with source input, candidates, created/resolved timestamps; queryable; resolution gates inclusion on the next run; no auto-retry while queued.
- **FR-15 — Anomaly staging:** Suspect price-return outliers are staged for review before reaching published returns. *(Architecture evolution D2: relocated from a post-compute `returns_anomaly` table to a two-stage `prices_review` at the price layer — annotate at ingestion, gate `fact_returns` at materialization — see AR-9. Original PRD `returns_anomaly` promote/reject semantics are superseded by the two-stage gate.)*

### NonFunctional Requirements

- **NFR-1 — Anomaly gating (two-stage):** A single-day move > ±50% is flagged for review and must not contribute to published returns until reviewed; flagging never halts ingestion (suspect price is recorded + annotated, legitimate large moves confirmed not discarded); once reviewed, returns are (re)computed.
- **NFR-2 — Adjustment reproducibility:** Any derived adjusted value must be reproducible from stored raw price + explicit factors; a non-reproducible value (e.g. adjusted > unadjusted close) is flagged as a data error.
- **NFR-3 — No silent gap-fill:** Missing data (no price on an open trading day) is logged per security; never forward-filled silently.
- **NFR-4 — Schema as public contract:** The `securities` schema (names, types, CompositeFIGI PK) is a public contract for downstream warehouse modules; breaking changes require a migration plan + versioned schema change.
- **NFR-5 — Audit timestamps:** Every table includes `created_at` and `updated_at`.
- **NFR-6 — Transaction boundary:** A failed run leaves no partial writes — per-security (per-figi-batch) atomicity.
- **NFR-7 — Observability surface:** The pipeline log table is the primary operational monitoring surface; no external logging infra in v1.
- **NFR-8 — Data-source commercial gate:** yfinance is personal-research-only; migration to a licensed source (EODHD/equiv) is a hard precondition for any commercial activity (distribution, paid analysis, firm production use).

### Additional Requirements

_Technical requirements extracted from the Architecture that shape epics/stories. The Architecture is the implementation source of truth where it evolves a PRD FR (FR-5, FR-15 above)._

- **AR-1 — Starter/init (Epic 1, Story 1):** `uv init --lib sym`, `src` layout; `uv add psycopg[binary] pandas yfinance financedatabase openfigi exchange_calendars`; `uv add --dev pytest ruff`. PostgreSQL 18.4 native Windows install (not Docker/WSL2).
- **AR-2 — Migrations:** Sqitch plain-SQL, dependency-ordered (`deploy`/`revert`/`verify`); the deterministic `recompute` command is version-controlled alongside migrations (DR depends on it).
- **AR-3 — Reference tables FIRST:** `currency` (FR-13) and `exchange` (FR-12) reference tables are created **before** `prices_raw`/`securities` so FKs are clean from creation, not retrofitted.
- **AR-4 — Trading calendar:** `exchange_calendars` 4.13.2 snapshotted into a versioned `trading_calendar` reference table; the DB table (not the library) is read at compute time; calendar version participates in `input_hash`. Prerequisite for returns.
- **AR-5 — Source-abstraction contract:** `fetch_ohlcv(figi, start, end) -> OhlcvResult` returning RAW prices + normalized `splits`/`dividends` (Decimal, ex-date keyed, currency explicit, missing = `[]` not null, `source` + `retrieved_at` stamped); config-keyed adapter registry (not import); adjusted-only sources raise `UnsupportedSourceError`; cross-vendor contract test compares derived cumulative factors (split exact, dividend tol max(0.5%, $0.005), ex-date exact).
- **AR-6 — HARD RULE (factor provenance):** Corporate-action factors derive ONLY from explicit action records, never reverse-engineered from adjusted/raw price ratios. Enforced at the source-abstraction boundary.
- **AR-7 — Three-layer returns engine:** `prices_raw` + factor store → `v_prices_adjusted` (deterministic SQL view, NULL base → NULL) → `fact_returns` loader-written table (NOT a MATERIALIZED VIEW), PK `(security_id, window_id, asof)`, dirty-set incremental refresh, each row stamped `input_hash = hash(raw_slice + factor_set + calendar_version)`.
- **AR-8 — Survivorship invariant:** Delisted securities MUST flow through `v_prices_adjusted` and `fact_returns`; tested correctness invariant, never a silent `status='delisted'` filter.
- **AR-9 — D2 two-stage anomaly:** `prices_review` flags > ±50% single-day moves AND calendar-vs-data divergence; annotate at ingestion (row lands in `prices_raw`), gate at materialization (`fact_returns` recompute excludes rows referencing an unreviewed flag; reviewed flags re-enter the dirty set). Idempotent UPSERT on `(figi, date)`.
- **AR-10 — D1 immutability + sweep:** Immutable-history default; a weekly trailing-90-day re-fetch-and-compare sweep ships in v1 to detect source-side retroactive corrections.
- **AR-11 — D4 GICS SCD:** Slowly-changing-dimension table shape now; current-only data populated (financedatabase). The one genuine one-way door — shape is cheap insurance.
- **AR-12 — Identity model:** `securities` (PK `composite_figi`, soft-delete only), `security_symbology` (effective-dated `valid_from`/`valid_to`), `securities_review_queue`; factors keyed on CompositeFIGI (ShareClassFIGI for grouping only); FIGI resolution decoupled from price ingestion (OpenFIGI outage must not block price updates for identified names).
- **AR-13 — Operational model:** No long-running service; idempotent CLI `uv run sym backfill|delta|recompute|sweep`; Windows Task Scheduler wake-to-run + run-if-missed; `delta` computes the gap from DB state, not the clock (backfill = delta with an earlier floor); one transaction per figi per batch (rows + `cursor_date` + status atomic, never advance cursor without rows); 429 → backoff+jitter capped → mark `error` and continue; defining test: second consecutive `delta` = zero net mutations.
- **AR-14 — Durability/DR:** `pg_dump` raw OHLCV + factors + identity + calendar; `--exclude-table` the recomputable `fact_returns`; recovery = fresh PG → migrate → restore raw+factors+identity+calendar → run deterministic `recompute`; 3-2-1 with client-side-encrypted cloud copy.
- **AR-15 — Universe seed:** ~50 adversarially-chosen benchmark names (splits, reverse splits, special + stock dividends, spin-offs, multi-currency, ADRs, ≥1 delisting) in `benchmark/seed_universe.toml`; the SAME set triple-serves as factor fixtures, the SM-6 metric set, and the MVP universe. 4–8k is the capacity ceiling, not a day-one gate.
- **AR-16 — EODHD fixture sequencing:** Build the EODHD adapter + its fixture-replay test now ($0); in one paid month (~$20) pull raw `/div` + `/splits` for the ~50 names and commit the raw dated JSON as replay fixtures, then cancel; live EODHD credentials/rate-limit/sync deferred (config flips, not architecture).
- **AR-17 — SM-6 accuracy harness:** `tests/test_accuracy.py` compares sym PR/TR against an independent published series for the benchmark names across all 18 windows, per-window tolerance (~5 bps clean, looser for corporate-action-heavy); runs as a regression gate on every returns-engine change (SM-6 / SM-C2).

**Open items to fold into stories (from Architecture validation):**

- **OI-1 (GATING) — View-performance spike:** Confirm `v_prices_adjusted` + `fact_returns` recompute meet SM-4's <10s cross-sectional bound at ~20M rows; if it fails, revisit the view/materialization boundary. Must precede certifying the returns engine.
- **OI-2 — 18-window return-math spec:** EXDATE_C reinvestment timing, calendar anchoring (WTD/MTD/QTD boundaries + rolling same-calendar-date), CAGR annualization, IPO base = first close. The #1 returns-epic prep deliverable (`windows.py` currently a label, not a spec).
- **OI-3 — FR-8 run-log decision:** Decide whether `pipeline_backfill_progress` (per-figi cursor) doubles as the NFR-7 monitoring surface or a separate per-run `pipeline_run_log` (attempted/succeeded/failed counts, mode, status) is required. FR-8 wording implies the latter.
- **OI-4 — FR-4 mapping label:** GICS lives in `classification/`, not `identity/` — documentation/mapping correction in the architecture's Requirements→Structure map.

### UX Design Requirements

None. sym is a headless data warehouse; the query/inspection surface is DBeaver. No UI, no UX specification, no UX-DRs.

### Requirements Coverage Map

| Requirement | Epic | Notes |
|---|---|---|
| FR-1 — FIGI assignment | Epic 1 | OpenFIGI resolution, review-status branching |
| FR-2 — Cross-reference storage | Epic 1 | symbology columns, lookup-any → CompositeFIGI |
| FR-3 — Security lifecycle | Epic 1 | `status` / `delist_date`, history retained |
| FR-4 — GICS classification | Epic 1 | SCD shape (AR-11); mapping label fix (OI-4) |
| FR-5 — Price ingestion | Epic 2 | reconciled: raw OHLCV + factors, not vendor adjusted |
| FR-6 — Three-phase load | Epic 2 | dev / backfill (resumable) / delta |
| FR-7 — Source abstraction | Epic 2 | `fetch_ohlcv` contract (AR-5), buyer-pluggable |
| FR-8 — Pipeline run logging | Epic 2 | run-log decision (OI-3) |
| FR-9 — Price return matrix | Epic 3 | 18 windows; math spec (OI-2) |
| FR-10 — Total return matrix | Epic 3 | EXDATE_C TR, same 18 windows |
| FR-11 — Incremental returns | Epic 3 | dirty-set recompute |
| FR-12 — Exchange reference table | Epic 1 | created FIRST (AR-3) |
| FR-13 — Currency reference table | Epic 1 | created FIRST (AR-3) |
| FR-14 — Securities review queue | Epic 1 | gates next-run inclusion |
| FR-15 — Anomaly staging | Epic 2 | reconciled: two-stage `prices_review` (AR-9) |
| NFR-1 — Anomaly gating (two-stage) | Epic 2 (annotate) + Epic 3 (gate) | split across ingestion/materialization |
| NFR-2 — Adjustment reproducibility | Epic 2 | reproducible from raw + factors |
| NFR-3 — No silent gap-fill | Epic 2 | logged, never forward-filled |
| NFR-4 — Schema as public contract | Epic 1 | CompositeFIGI PK contract |
| NFR-5 — Audit timestamps | Epic 1 | `created_at`/`updated_at` on every table |
| NFR-6 — Transaction boundary | Epic 2 | per-figi-batch atomicity |
| NFR-7 — Observability surface | Epic 2 | pipeline log = monitoring surface |
| NFR-8 — Commercial gate | Epic 2 | yfinance personal-only; EODHD precondition |
| AR-1 — Starter/init | Epic 1, Story 1.1 | `uv init`, PG 18.4 |
| AR-2 — Migrations | Epic 1 | Sqitch; recompute version-controlled |
| AR-3 — Reference tables first | Epic 1 | currency/exchange before prices |
| AR-4 — Trading calendar | Epic 2 | versioned `trading_calendar`; returns prereq |
| AR-5 — Source contract | Epic 2 | `OhlcvResult`, registry, contract test |
| AR-6 — HARD RULE factor provenance | Epic 2 | factors from explicit actions only |
| AR-7 — Three-layer engine | Epic 3 | view + `fact_returns` loader |
| AR-8 — Survivorship invariant | Epic 3 | delisted flow through, tested |
| AR-9 — D2 two-stage anomaly | Epic 2 (annotate) + Epic 3 (gate) | `prices_review` |
| AR-10 — Immutability + sweep | Epic 2 | weekly 90-day re-fetch sweep |
| AR-11 — GICS SCD | Epic 1 | one-way-door shape |
| AR-12 — Identity model | Epic 1 | effective-dated symbology, decoupled resolution |
| AR-13 — Operational model | Epic 2 | idempotent CLI, Task Scheduler |
| AR-14 — Durability/DR | Epic 2 | pg_dump excl. fact_returns + recompute |
| AR-15 — Universe seed | Epic 1 | ~50 adversarial names, triple-serves |
| AR-16 — EODHD fixtures | Epic 2 | build adapter + replay fixtures now |
| AR-17 — SM-6 harness | Epic 3 | accuracy regression gate |
| OI-1 — View-perf spike (GATING) | Epic 3 | gates returns-engine certification |
| OI-2 — 18-window math spec | Epic 3, first story | `windows.py` spec |
| OI-3 — FR-8 run-log decision | Epic 2 | resolve run-log vs progress-cursor |
| OI-4 — FR-4 mapping label | Epic 1 | classification/ not identity/ |

All 15 FRs, 8 NFRs, 17 ARs, and 4 OIs are mapped. Dependencies are linear: Epic 2 consumes Epic 1's resolved FIGIs and reference tables; Epic 3 consumes Epic 1 identity + Epic 2 raw prices + factors + calendar.

## Epic List

### Epic 1 — Identified Security Master

**Goal:** Stand up the project and a queryable, FK-clean security master keyed on an immutable CompositeFIGI — the public-contract spine every downstream warehouse module joins against.

**Value:** Without trustworthy identity, every price and return is unjoinable. This epic delivers the identifiers, classification, lifecycle, and reference tables that make the rest of sym addressable.

**Requirements:** FR-1, FR-2, FR-3, FR-4, FR-12, FR-13, FR-14, NFR-4, NFR-5; AR-1, AR-2, AR-3, AR-11, AR-12, AR-15, OI-4.

**Scope highlights:**
- Project init (`uv init --lib`, PG 18.4, Sqitch) and the seed universe (~50 adversarial names).
- Reference tables (`currency`, `exchange`) created FIRST so all FKs are clean from creation.
- Identity model: `securities` (CompositeFIGI PK, soft-delete), effective-dated `security_symbology`, `securities_review_queue`, GICS as SCD.
- FIGI resolution decoupled from ingestion; review-status branching (no_figi_found / ambiguous / share_class_conflict).

### Epic 2 — Trustworthy Price History

**Goal:** Ingest raw daily OHLCV + explicit corporate-action factors for the universe through a source-agnostic adapter, with anomaly annotation, a trading calendar, and an idempotent operational pipeline.

**Value:** A returns engine is only as honest as its inputs. This epic delivers raw prices and factors that are reproducible, anomaly-annotated, gap-aware, and re-runnable without drift — the substrate returns are derived from.

**Requirements:** FR-5, FR-6, FR-7, FR-8, FR-15, NFR-1 (annotate half), NFR-2, NFR-3, NFR-6, NFR-7, NFR-8; AR-4, AR-5, AR-6, AR-9 (annotate half), AR-10, AR-13, AR-14, AR-16, OI-3.

**Scope highlights:**
- Trading calendar snapshotted to a versioned reference table (returns prerequisite).
- Source-abstraction contract (`fetch_ohlcv → OhlcvResult`), HARD RULE factor provenance, cross-vendor contract test, EODHD replay fixtures.
- Three-phase load (dev/backfill/delta), idempotent CLI + Task Scheduler, per-figi-batch atomicity, immutability + weekly sweep, DR.
- `prices_review` annotate-at-ingestion; pipeline run logging as the monitoring surface; commercial gate (yfinance personal-only).

### Epic 3 — Reproducible Returns

**Goal:** Derive adjusted prices in-view and compute the 18-window PR/TR matrices into `fact_returns`, gated by anomaly review and validated by an accuracy regression harness.

**Value:** This is the product's reason to exist — correct, reproducible, survivorship-clean total and price returns across all FactSet-equivalent windows, with a regression gate that proves they stay correct.

**Requirements:** FR-9, FR-10, FR-11, NFR-1 (gate half); AR-7, AR-8, AR-9 (gate half), AR-17, OI-1 (GATING), OI-2.

**Scope highlights:**
- 18-window return-math spec FIRST (`windows.py`): EXDATE_C timing, calendar anchoring, CAGR, IPO base.
- Three-layer engine: `v_prices_adjusted` view → `fact_returns` loader with `input_hash` dirty-set incremental recompute.
- Survivorship invariant (delisted flow through, tested); two-stage gate (exclude unreviewed-flag rows).
- View-performance spike at ~20M rows (gating SM-4); SM-6 accuracy harness vs independent published series.

## Epic 1 — Identified Security Master

**Goal:** Stand up the project and a queryable, FK-clean security master keyed on an immutable CompositeFIGI — the public-contract spine every downstream warehouse module joins against.

### Story 1.1: Project scaffold and migration harness

As a warehouse maintainer,
I want a uv-managed Python package and a Sqitch migration harness against PostgreSQL 18.4,
So that schema changes are version-controlled, deployable, and revertible from day one.

**Acceptance Criteria:**

**Given** a clean machine with PostgreSQL 18.4 (native Windows) and uv installed,
**When** I follow the documented init steps (`uv init --lib`, `uv add` the dependency set, configure the DB connection),
**Then** `uv run sym --help` succeeds and a connection to the `sym` database is established from config.
**And** the `src/sym/` package exists with `identity/`, `sources/`, `ingest/`, `calendar/`, `returns/`, `classification/` subpackage placeholders, and pytest + ruff are configured as dev dependencies.

**Given** the Sqitch harness,
**When** I run deploy then revert on an empty/no-op change,
**Then** the database returns to its prior state and verify passes.
**And** the deterministic `recompute` command is version-controlled alongside the migrations (AR-2).

### Story 1.2: Currency and exchange reference tables

As a downstream consumer,
I want ISO-4217 currency and MIC-keyed exchange reference tables created before any fact table,
So that every price, return, and security FK resolves cleanly from creation rather than being retrofitted.

**Acceptance Criteria:**

**Given** the migration set,
**When** the reference-table migrations deploy,
**Then** `currency` (ISO-4217 code PK, name) and `exchange` (MIC PK, name, country, country ISO, IANA timezone, currency FK) exist, each with `created_at`/`updated_at` (NFR-5).

**Given** the seed data,
**When** reference tables are populated,
**Then** `currency` holds active ISO-4217 codes and `exchange` covers every MIC used by the seed universe, each exchange carrying a valid IANA timezone for business-day math.

**Given** an exchange row,
**When** its currency is set,
**Then** it FK-references `currency`; an unknown currency is rejected.

### Story 1.3: Core identity schema (securities + effective-dated symbology)

As a downstream warehouse module,
I want a `securities` master keyed on CompositeFIGI with effective-dated symbology,
So that a lookup on any identifier resolves to a single stable FIGI.

**Acceptance Criteria:**

**Given** migrations,
**When** the identity schema deploys,
**Then** `securities` exists with `composite_figi` PK, `share_class_figi`, `status` (`active`/`delisted`/`suspended`), `delist_date`, FK to exchange (MIC) and currency, plus `created_at`/`updated_at`.
**And** `security_symbology` exists in the architecture's narrow effective-dated shape — `(composite_figi, symbol_type, symbol_value, mic, country_iso, valid_from, valid_to)` — where `symbol_type` enumerates `ticker`/`isin`/`cusip`/`sedol`/`local_code`; the `(symbol_type, symbol_value)` lookup is indexed and a `btree_gist` `EXCLUDE` constraint forbids overlapping validity for the same identifier.

**Given** a stored security with multiple historical symbols,
**When** I look up by any identifier (ticker+MIC, ISIN, SEDOL, or CUSIP) for an effective date,
**Then** the query returns exactly one CompositeFIGI.

**Given** the `securities` schema,
**Then** its column contract (names, types, CompositeFIGI PK) is documented as a public contract for downstream modules — breaking changes require a migration plan + versioned schema change (NFR-4).

### Story 1.4: Securities review queue

As a data steward,
I want a `securities_review_queue` capturing FIGI-assignment issues,
So that unresolved identities are visible and gate inclusion on the next run.

**Acceptance Criteria:**

**Given** migrations,
**When** the queue migration deploys,
**Then** `securities_review_queue` exists with source input, candidate list, status (`no_figi_found` / `ambiguous_figi` / `share_class_conflict`), and created/resolved timestamps.

**Given** a queued unresolved item,
**When** a run executes,
**Then** that input is excluded from assignment and not auto-retried while queued.

**Given** a resolved item,
**When** the next run executes,
**Then** the input becomes eligible for inclusion.

### Story 1.5: Seed universe definition

As a researcher,
I want a committed `benchmark/seed_universe.toml` of ~50 adversarially-chosen names,
So that the same set serves as factor fixtures, the SM-6 metric set, and the MVP universe.

**Acceptance Criteria:**

**Given** the repo,
**When** I inspect `benchmark/seed_universe.toml`,
**Then** it lists ~50 names spanning splits, reverse splits, special + stock dividends, spin-offs, multi-currency, ADRs, and ≥1 delisting — each with input identifiers (ticker+MIC and/or ISIN).

**Given** the file,
**When** it is parsed by the loader,
**Then** each entry yields a valid resolution input.

**Given** the categories,
**Then** the adversarial rationale per category is documented inline so the set stays meaningful as fixtures and metric set.

### Story 1.6: FIGI assignment via OpenFIGI

As the identity pipeline,
I want to resolve seed inputs to CompositeFIGIs via OpenFIGI, decoupled from price ingestion,
So that securities are identified without an OpenFIGI outage blocking price updates for already-identified names.

**Acceptance Criteria:**

**Given** a seed input with a unique OpenFIGI match,
**When** resolution runs,
**Then** `securities` + `security_symbology` rows are written with the CompositeFIGI, and a single failure never halts the run.

**Given** no match,
**Then** the input is written to the review queue as `no_figi_found`; multiple candidates → `ambiguous_figi` with candidates recorded and no auto-assign.

**Given** distinct share classes (e.g. GOOG/GOOGL, BRK.A/BRK.B),
**Then** each receives a distinct CompositeFIGI; a shared CompositeFIGI across classes → `share_class_conflict`.

**Given** an OpenFIGI outage,
**Then** price ingestion for already-identified names is unaffected (resolution is decoupled from ingestion).

### Story 1.7: Security lifecycle and active/delisted filtering

As a researcher,
I want delisting represented as a status-only change with full history retained,
So that I can run survivorship-clean queries that include or exclude delisted names.

**Acceptance Criteria:**

**Given** a security being delisted,
**When** the lifecycle flag is set,
**Then** `status = 'delisted'` and `delist_date` is populated while the CompositeFIGI and all symbology/price history are retained.

**Given** a query,
**When** I filter active-only,
**Then** delisted securities are excluded; **When** I include delisted, **Then** they appear.

**Given** the codebase,
**Then** no code path hard-deletes a security row (soft-delete only).

### Story 1.8: GICS classification (slowly-changing dimension)

As a researcher,
I want all four GICS levels stored in an SCD-shaped table populated from financedatabase,
So that ≥90% of active securities are classifiable and the shape tolerates future point-in-time history.

**Acceptance Criteria:**

**Given** migrations,
**When** the classification migration deploys,
**Then** a GICS table in the `classification/` domain stores sector / industry-group / industry / sub-industry codes + labels in SCD (effective-dated) shape, keyed to CompositeFIGI, with audit timestamps.

**Given** the financedatabase loader,
**When** it runs over identified securities,
**Then** ≥90% of active securities have all four GICS levels populated (current-only data).

**Given** the architecture Requirements→Structure map,
**Then** GICS is documented under `classification/`, not `identity/` (OI-4 correction).
**And** all four levels are queryable and indexed.

## Epic 2 — Trustworthy Price History

**Goal:** Ingest raw daily OHLCV + explicit corporate-action factors for the universe through a source-agnostic adapter, with anomaly annotation, a trading calendar, and an idempotent operational pipeline.

### Story 2.1: Trading calendar reference table

As the returns engine,
I want exchange_calendars snapshotted into a versioned `trading_calendar` table,
So that compute reads a stable, versioned calendar rather than a live library.

**Acceptance Criteria:**

**Given** exchange_calendars 4.13.2,
**When** the snapshot loader runs for the seed exchanges,
**Then** `trading_calendar` holds open trading days per exchange with a `calendar_version` stamp and audit timestamps.

**Given** compute,
**Then** the DB table (not the library) is the read source, and the calendar version is exposed for inclusion in the returns `input_hash`.

**Given** a re-snapshot that differs,
**When** it runs,
**Then** a new `calendar_version` is written without mutating prior versions.

### Story 2.2: Source-abstraction contract and yfinance adapter

As an ingestion pipeline,
I want a single `fetch_ohlcv(figi, start, end) -> OhlcvResult` contract with a config-keyed adapter registry,
So that the source is swappable and all source-specific logic is isolated behind one boundary.

**Acceptance Criteria:**

**Given** the contract,
**Then** `OhlcvResult` carries RAW prices + normalized `splits`/`dividends` (Decimal, ex-date keyed, currency explicit, missing = `[]` not null, stamped `source` + `retrieved_at`).

**Given** config,
**When** a source key is set,
**Then** the matching adapter is selected from a registry (not import-based); an adjusted-only source raises `UnsupportedSourceError`.

**Given** the HARD RULE,
**Then** corporate-action factors derive ONLY from explicit action records — never reverse-engineered from adjusted/raw price ratios — enforced at the adapter boundary (AR-6).

**Given** the cross-vendor contract test,
**When** two adapters cover the same name,
**Then** derived cumulative factors match (split exact; dividend tolerance max(0.5%, $0.005); ex-date exact).

### Story 2.3: Raw price and factor storage with atomic ingestion

As the warehouse,
I want raw OHLCV and explicit corporate-action factors persisted per security with per-batch atomicity,
So that prices are reproducible and never silently filled.

**Acceptance Criteria:**

**Given** migrations,
**Then** `prices_raw` (FK to securities and currency) and a factor store exist with audit timestamps; no vendor `adjusted_close` column is stored.

**Given** an ingestion batch,
**When** it writes,
**Then** all rows + cursor + status commit in one transaction per figi-batch; a failure leaves no partial writes (NFR-6).

**Given** a missing price on an open trading day,
**Then** it is logged per security and never forward-filled (NFR-3).

**Given** stored raw + factors,
**Then** a derived adjusted value is reproducible from them; a non-reproducible value (e.g. adjusted > unadjusted close) is flagged as a data error (NFR-2).

### Story 2.4: Anomaly annotation at ingestion (prices_review)

As a data steward,
I want suspect prices annotated at ingestion without halting the pipeline,
So that legitimate large moves are preserved and suspect ones are queued for review.

**Acceptance Criteria:**

**Given** an ingested price,
**When** a single-day move exceeds ±50%,
**Then** a `prices_review` flag is written (idempotent UPSERT on (figi, date)) while the price still lands in `prices_raw` and ingestion continues (NFR-1 annotate half).

**Given** a data point that diverges from the trading calendar (a price on a non-trading day, or missing on a trading day),
**Then** a `prices_review` flag records the divergence (AR-9).

**Given** a flagged price,
**Then** it is recorded and annotated, never discarded; confirming a legitimate large move is a review action, not an ingestion-time drop.

### Story 2.5: Three-phase load orchestration and idempotent CLI

As an operator,
I want `uv run sym backfill|delta|recompute|sweep` driven by Windows Task Scheduler,
So that loads are resumable, gap-computed, and safely re-runnable.

**Acceptance Criteria:**

**Given** a mode flag,
**Then** `dev` / `backfill` (resumable, per-security progress) / `delta` (dates since last success) select at runtime; up-to-date securities are skipped in delta; an interrupted backfill resumes from the last completed security.

**Given** `delta`,
**Then** the gap is computed from DB state, not the clock (backfill = delta with an earlier floor).

**Given** a 429 response,
**Then** backoff + jitter (capped) is applied, then the security is marked `error` and the run continues; the cursor never advances without rows.

**Given** two consecutive `delta` runs,
**Then** the second produces zero net mutations (idempotency invariant).

### Story 2.6: Pipeline run logging and monitoring surface

As an operator,
I want each run to write a queryable log record,
So that the pipeline log is the primary operational monitoring surface in v1.

**Acceptance Criteria:**

**Given** a run,
**Then** a `pipeline_run_log` record captures timestamp, mode, attempted, succeeded, failed/skipped, and anomaly counts; `status = success` (0 errors) or `partial` (with failure count).

**Given** OI-3,
**Then** a deliberate decision is recorded: `pipeline_run_log` (run-level counts) is separate from the per-figi `pipeline_backfill_progress` cursor.

**Given** DBeaver,
**Then** the log is queryable with no external logging infra in v1 (NFR-7).

### Story 2.7: EODHD adapter, replay fixtures, and commercial gate

As a maintainer,
I want an EODHD adapter with committed replay fixtures and a documented commercial gate,
So that a licensed source is one config flip away without ongoing cost.

**Acceptance Criteria:**

**Given** the EODHD adapter,
**When** tested,
**Then** it passes the same contract test as yfinance using committed raw dated `/div` + `/splits` JSON replay fixtures for the ~50 names.

**Given** the fixtures,
**Then** they are built from one paid month (~$20) and committed; live credentials, rate-limit, and sync are deferred (config flips, not architecture changes).

**Given** NFR-8,
**Then** it is documented that yfinance is personal-research-only and migration to EODHD/equivalent is a hard precondition for any commercial activity (distribution, paid analysis, firm production use).

### Story 2.8: Immutability default and weekly re-fetch sweep

As a maintainer,
I want immutable history with a weekly trailing-90-day re-fetch-and-compare sweep,
So that source-side retroactive corrections are detected without mutating history by default.

**Acceptance Criteria:**

**Given** default operation,
**Then** stored history is immutable — no in-place overwrite path runs in normal backfill/delta.

**Given** `uv run sym sweep`,
**When** it runs (weekly),
**Then** it re-fetches the trailing 90 days, compares to stored raw, and reports divergences for review.

**Given** a detected source correction,
**Then** it surfaces as a reviewable signal rather than a silent overwrite.

### Story 2.9: Durability and disaster recovery

As a maintainer,
I want a backup/restore procedure that excludes recomputable data,
So that recovery is a deterministic rebuild rather than a full snapshot restore.

**Acceptance Criteria:**

**Given** `pg_dump`,
**Then** it captures raw OHLCV + factors + identity + calendar and `--exclude-table` the recomputable `fact_returns`.

**Given** a recovery on a fresh PostgreSQL instance,
**When** run,
**Then** the sequence migrate → restore raw+factors+identity+calendar → `uv run sym recompute` reproduces `fact_returns` deterministically.

**Given** the 3-2-1 rule,
**Then** a client-side-encrypted cloud copy is part of the documented procedure.

## Epic 3 — Reproducible Returns

**Goal:** Derive adjusted prices in-view and compute the 18-window PR/TR matrices into `fact_returns`, gated by anomaly review and validated by an accuracy regression harness.

### Story 3.1: 18-window return-math specification

As the returns engine,
I want a precise specification for all 18 windows in `windows.py`,
So that calendar anchoring, reinvestment timing, and annualization are unambiguous before any computation.

**Acceptance Criteria:**

**Given** the spec,
**Then** each window is defined: calendar-anchored (1D, WTD, MTD, QTD, YTD) use the prior period-end base; rolling (1M, 3M, 6M, 9M, 1Y) use the same-calendar-date N periods prior, with weekend/holiday → last trading day on/before.

**Given** multi-year windows (2Y, 3Y, 5Y, 10Y, 20Y, 30Y),
**Then** returns annualize as CAGR; IPO_ANN base = first available close.

**Given** total return,
**Then** EXDATE_C reinvestment timing (dividend reinvested on ex-date, gross) is specified.

**Given** insufficient history for a window,
**Then** the value is NULL (documented rule).

### Story 3.2: Adjusted-price view (v_prices_adjusted)

As the returns engine,
I want `v_prices_adjusted` to derive adjusted prices in-view from raw + factors,
So that adjustment is deterministic and reproducible with no stored adjusted column.

**Acceptance Criteria:**

**Given** raw prices + explicit factors,
**When** the view is queried,
**Then** it computes adjusted values deterministically; a NULL base yields NULL (no fabricated value).

**Given** identical inputs,
**When** queried across runs,
**Then** the view returns identical output (determinism, supports NFR-2).

**Given** factors derived only from explicit actions,
**Then** the view never reverse-engineers factors from price ratios (AR-6 upheld downstream).

### Story 3.3: View-performance spike at scale (GATING)

As an architect,
I want to confirm `v_prices_adjusted` + `fact_returns` recompute meet the SM-4 <10s cross-sectional bound at ~20M rows,
So that the view/materialization boundary is validated before certifying the returns engine.

**Acceptance Criteria:**

**Given** ~20M price rows (synthetic or loaded),
**When** a cross-sectional returns query runs,
**Then** it completes within SM-4's <10s bound.

**Given** a failure to meet the bound,
**Then** the view/materialization boundary is revisited and the decision recorded before proceeding.

**Given** the workflow,
**Then** this spike is a documented gate that must pass before the returns engine is certified (OI-1).

### Story 3.4: fact_returns loader and price-return matrix

As a researcher,
I want PR for all 18 windows materialized into `fact_returns`,
So that cross-sectional price-return queries are fast and reproducible.

**Acceptance Criteria:**

**Given** migrations,
**Then** `fact_returns` exists as a loader-written table (NOT a materialized view) with PK `(security_id, window_id, asof)` and an `input_hash` column.

**Given** `v_prices_adjusted`,
**When** the loader runs,
**Then** PR is computed for all 18 windows per (FIGI, date) per the spec, stored as decimals, with insufficient history → NULL.

**Given** each written row,
**Then** `input_hash = hash(raw_slice + factor_set + calendar_version)` is stamped.

### Story 3.5: Total-return matrix

As a researcher,
I want TR (dividends reinvested on ex-date, gross) for the same 18 windows,
So that total return is available alongside price return.

**Acceptance Criteria:**

**Given** dividends,
**When** TR computes,
**Then** it follows EXDATE_C reinvestment for all 18 windows / the same (FIGI, date) pairs, with the same schema and NULL rules as PR.

**Given** a name with no dividends,
**Then** TR = PR.

**Given** a multi-year dividend payer,
**Then** TR > PR.

### Story 3.6: Incremental recompute with anomaly gate

As the pipeline,
I want dirty-set incremental recompute that excludes unreviewed anomalies,
So that only affected windows recompute and suspect prices never reach published returns.

**Acceptance Criteria:**

**Given** new price data on a delta run,
**When** recompute runs,
**Then** only windows affected by changed inputs recompute; multi-year CAGR endpoints recompute daily (the endpoint moves each day).

**Given** a row whose inputs reference an unreviewed `prices_review` flag,
**Then** `fact_returns` recompute excludes it (NFR-1 / AR-9 gate half); a reviewed flag re-enters the dirty set and its returns materialize.

**Given** `input_hash`,
**Then** rows whose inputs are unchanged are skipped (dirty-set efficiency).

### Story 3.7: Survivorship invariant

As a researcher,
I want delisted securities to flow through the returns engine,
So that backtests built on sym are survivorship-bias-free.

**Acceptance Criteria:**

**Given** a delisted security with history,
**Then** it appears in `v_prices_adjusted` and `fact_returns` for its active dates.

**Given** the engine,
**Then** no code path silently filters `status = 'delisted'` out of returns.

**Given** a known delisted name,
**Then** a test asserts it has computed returns through its delisting date.

### Story 3.8: SM-6 returns-accuracy harness

As a maintainer,
I want `tests/test_accuracy.py` comparing sym PR/TR to an independent published series across all 18 windows,
So that returns correctness is a regression gate on every returns-engine change.

**Acceptance Criteria:**

**Given** the ~50 benchmark names,
**When** the harness runs,
**Then** sym PR/TR is compared to an independent published reference series across all 18 windows within a per-window tolerance (~5 bps for clean names, explicitly looser for corporate-action-heavy names).

**Given** any change to the returns engine (`v_prices_adjusted`, factor derivation, `fact_returns` recompute, or window definitions),
**Then** the harness runs as a regression gate (SM-6).

**Given** SM-C2,
**Then** tolerances are not widened to force a pass (documented constraint).
