---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-06-05'
inputDocuments:
  - _bmad-output/planning-artifacts/briefs/brief-sym-2026-05-19/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-sym-2026-05-19/.decision-log.md
  - _bmad-output/planning-artifacts/prds/prd-sym-2026-05-19/prd.md
  - _bmad-output/planning-artifacts/prds/prd-sym-2026-05-19/addendum.md
  - _bmad-output/planning-artifacts/prds/prd-sym-2026-05-19/.decision-log.md
workflowType: 'architecture'
project_name: 'sym'
user_name: 'Andre'
date: '2026-05-20'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements (15 FRs across 4 capability groups):**

- *Identity & Security Master* (FR-1 to FR-4): CompositeFIGI is the permanent primary key, assigned via OpenFIGI and surviving ticker/SEDOL/vendor changes. ShareClassFIGI links multi-class equities (e.g. GOOG/GOOGL). Architecturally this mandates an identity-resolution layer that is **decoupled** from market-data ingestion — FIGI assignment and price updates are independent external dependencies.
- *Market Data Ingestion* (FR-5 to FR-8): adjusted OHLCV ingestion through a **source abstraction layer** (`fetch_ohlcv(figi, start_date, end_date) → DataFrame`), driving a three-phase pipeline (dev / resumable backfill / delta) with `pipeline_backfill_progress` tracking. The abstraction is the load-bearing seam for the yfinance→EODHD swap and for buyer-pluggable feeds.
- *Returns Computation* (FR-9 to FR-11): 18-window Price-Return and Total-Return matrices matching FactSet EXDATE_C methodology. **FR-11 (incremental recompute) is internally contradictory** and is resolved by Open Decision 0 below.
- *Data Quality* (FR-12 to FR-15): exchange/calendar scope, securities review queue, anomaly staging.

**Non-Functional Requirements:**

- NFR-8 (commercial gate) is load-bearing: yfinance is dev-only (Yahoo ToS prohibits commercial automated access); GICS redistribution needs MSCI/S&P licensing; EODHD redistribution terms apply. The architecture must keep personal-use and future-commercial paths separable without committing to ship commercially.
- Resumability, idempotency, and reproducibility (NFR-4, FR-6) shape the pipeline as restartable and data-reconcilable rather than stateful-process-dependent.

**Scale & Complexity:**

- ~4,000–8,000 securities × ~2,520 trading days ≈ 10–20M price rows; returns are the same magnitude. Total footprint ~12–15 GB.
- Primary domain: data-warehouse / ETL backend (no UI — DBeaver is the query surface).
- Complexity level: medium. The complexity is in correctness (identity permanence, return methodology, restatement semantics), not in volume — this scale sits comfortably within PostgreSQL.

### Technical Constraints & Dependencies

- **PostgreSQL** (chosen over DuckDB+Parquet): at ~12–15 GB, Postgres is simpler operationally, DBeaver-native, and view-capable. DuckDB's columnar advantage doesn't earn its complexity below ~100 GB.
- **External dependencies are independent and individually fallible**: OpenFIGI (identity) and the price source (yfinance/EODHD) must fail independently — an OpenFIGI outage cannot halt price updates for already-identified securities.
- **Trading-day calendar** is pinned, versioned reference data — a dependency for any returns-as-views approach, and a partially-unresolved item carried from the PRD review (calendar source was never tagged to an FR).

### Cross-Cutting Concerns Identified

1. **Identity permanence** — FIGI as the immutable join key across all future warehouse modules.
2. **Source abstraction** — single seam isolating vendor specifics; governs dev→prod swap and commercial pluggability.
3. **Restatement / immutability semantics** — how the store treats source-side retroactive corrections (PRD parked item Q2).
4. **Reproducibility & idempotency** — UPSERT on (figi, date); progress reconcilable from data, not process state.
5. **Data quality surfaces** — anomaly detection, review queues.
6. **Commercial-readiness separability** — licensing-gated paths kept distinct (NFR-8).
7. **Point-in-time correctness** — GICS is current-only via financedatabase (PRD parked item Q3); affects historical research validity.

### Decided Architectural Positions

1. PostgreSQL as the single store; DBeaver as the query/inspection surface.
2. Source abstraction layer (`fetch_ohlcv`) is the mandatory seam between pipeline and any vendor.
3. Three-phase pipeline (dev / resumable backfill / delta), resumable from data state via idempotent UPSERT on (figi, date).
4. CompositeFIGI is the permanent primary key; ShareClassFIGI links multi-class equities.
5. ~~Local currency only; no FX normalization in sym (downstream responsibility).~~ **Superseded 2026-06-08 (Epic FX):** prices are still stored in local currency, but **FX normalization and currency restatement now live in sym**, not downstream. Epic FX added a USD-centered `fx_rate` store (one observed rate per `(base,quote,as_of_date,source)`, inverses/crosses derived in `v_fx`/`v_fx_daily`, never stored) and a thin restatement primitive (`fx/restate.py` — `returns_in_currency`/`price_in_currency` — plus `fundamentals.market_cap_usd`). Rationale: the unhedged-restatement math `(1+r_local)·FX(asof)/FX(base)−1` is a pure function over `fx_rate` and belongs next to the data it reads; downstream consumers (QRP analytics/backtest/optimiser) call it rather than re-implement it (no FX/returns logic duplicated outside sym). See `epics-fx.md` (whose original scope listed restatement as OUT — a downstream consumer — a boundary deliberately moved into sym) and `implementation-artifacts/epic-fx-retro-2026-06-08.md` (action item A2).
6. Personal-use and commercial paths kept separable behind the source abstraction and NFR-8 gate; no commercial commitment in v1.
7. **FIGI assignment is decoupled from price ingestion** — independent external dependencies; an OpenFIGI outage must not block price updates for already-identified securities.

### Open Architectural Decisions (for Step 4+)

- **Decision 0 — Materialize vs. compute returns. (High-confidence lean: compute.)** Store adjusted prices + a pinned trading calendar; expose the 18 return windows as **views/computed queries** rather than materialized tables. Six independent elicitation approaches (Self-Consistency Validation) converged here. This dissolves returns-table partitioning, the nightly recompute, the FR-11 contradiction, and returns-anomaly staging. Must confirm view performance at ~20M rows and define NULL-base behavior (insufficient history).
- **Decision 1 — Restatement strategy (sharpened by FMEA).** Delta mode only fetches new dates, so source-side retroactive corrections to historical prices are silently missed. Choose explicitly between: (a) a periodic re-fetch-and-compare sweep that detects and ingests corrections, or (b) a documented stance that historical records are immutable and corrections are never re-ingested. This directly addresses PRD parked item Q2 ("'historical records are unaffected' claim is technically misleading").
- **Decision 2 — Anomaly detection placement (relocated by Decision 0).** With returns as views, FR-15's returns-anomaly staging has no home; detection moves upstream to a `prices_review` surface flagging >±50% single-day moves before prices land in the table.
- **Decision 3 — Trading-day calendar source.** Pin a concrete source (exchange-calendars library vs. derived-from-data); the PRD review left this untagged with no owning FR. Required as reference data before returns-as-views can compute.
- **Decision 4 — Point-in-time GICS.** financedatabase supplies current-only, GICS-approximated classification (PRD Q3). Decide whether v1 accepts current-only (documented limitation) or designs a slowly-changing-dimension shape for later point-in-time correctness.
- **Decision 5 — OpenFIGI rate-limit / batching strategy** for initial identity backfill of 4k–8k securities.

## Starter Template Evaluation

### Primary Technology Domain

Headless data-warehouse / ETL backend — a Python ingestion package over PostgreSQL, queried via DBeaver. No web/mobile/CLI-UI domain applies, so conventional feature scaffolds (create-next-app, T3, Expo) are out of scope. The "starter" decision is project structure + dependency/migration tooling, not a feature framework.

### Starter Options Considered

| Option | Verdict |
|---|---|
| **uv + `src` layout** (Astral, v0.11.19, 2026-06-03) | **Selected.** Rust-based, reproducible `uv.lock`, fast resolver, drop-in venv. `src` layout isolates the importable `sym` package from repo-root scripts — correct for a library-shaped pipeline. |
| Poetry | Mature but slower; uv has become the ecosystem default and supersedes pip/pip-tools/virtualenv in one tool. |
| Plain pip + requirements.txt | No lockfile reproducibility (conflicts with the reproducibility posture). |
| Cookiecutter data-science template | Over-scoped (notebooks, modeling dirs sym doesn't need). |

### Selected Starter: uv (v0.11.19) with `src` layout

**Rationale for Selection:**
sym is an importable package (source-abstraction layer, identity resolver, returns views, pipeline phases) — not an app with a single entrypoint. The `src` layout forces imports to resolve against the installed package, keeping distributed code cleanly separated. `uv.lock` provides the reproducible, cross-platform dependency pinning the pipeline's reproducibility requirement needs.

**Initialization Command:**

```bash
uv init --lib sym
cd sym
uv add psycopg[binary] pandas
uv add yfinance financedatabase openfigi   # dev-phase sources (NFR-8: yfinance dev-only)
uv add --dev pytest ruff
```

**Architectural Decisions Provided by Starter:**

- **Language & Runtime:** Python (pinned via `.python-version`); `pyproject.toml` as the single project manifest.
- **Dependency Management:** `uv.lock` universal lockfile — reproducible installs across machines.
- **Code Organization:** `src/sym/` package root; tests at `tests/`. Pipeline phases, source-abstraction adapters, and returns-view definitions live as submodules.
- **DB Driver:** `psycopg` (v3) for PostgreSQL.
- **DataFrame layer:** `pandas` — matches the FR-7 `fetch_ohlcv(...) → DataFrame` contract.
- **Tooling:** `ruff` (lint + format), `pytest` (tests).

**Deferred to architectural decisions (Step 4):** SQL migration tool choice (Alembic vs. plain versioned `.sql` runner) — ties to Decision 0 (returns-as-views) and Decision 3 (calendar reference data), so held rather than bundled into the starter. Standalone-repo vs. monorepo-for-warehouse structural question also carried to Step 4.

**Note:** Project initialization using this command should be the first implementation story.

## Core Architectural Decisions

_Resolved through dependency-graph, reversibility, pre-mortem analysis, and a multi-agent party-mode review (architect, senior engineer, PM, analyst). Each decision notes its rationale and what it affects._

### Decision Priority Analysis

**Critical (block implementation):** D0 returns engine (three-layer model), source-abstraction contract, D3 calendar, migration tooling, identity data model, universe seed.
**Important (shape architecture):** D1 restatement, D2 anomaly placement, EODHD fixture sequencing, operational model, durability/DR.
**Deferred (post-MVP):** D4 point-in-time GICS data, D5 OpenFIGI batching tuning, live EODHD ingestion, full 4–8k universe scale-out.

### D0 — Returns engine: three-layer model (raw → adjusted view → materialized fact table)

Returns are **not** pure query-time views. The settled shape:

1. **Raw inputs (source of truth):** `prices_raw` (unadjusted OHLCV) + an explicit corporate-action factor store (splits, dividends). Never store vendor pre-adjusted prices — they are retroactively rewritten by vendors on each corporate action, making any view over them non-deterministic over time.
2. **`v_prices_adjusted` — deterministic SQL view.** The single home of adjustment math. Unit-testable in isolation. NULL base period returns **NULL** (never 0, never error).
3. **`fact_returns` — loader-written table** (not a `MATERIALIZED VIEW`). 18 FactSet-style windows (PR + TR) precomputed off `v_prices_adjusted`. Schema `fact_returns(security_id, window_id, asof, pr, tr, input_hash)`, PK `(security_id, window_id, asof)`. Refreshed incrementally on the **dirty set only** (securities with new/revised raw rows or changed factors, dates ≥ ex-date), single transaction, gated behind the D2 review. Each row stamped with `input_hash = hash(raw_slice + factor_set + calendar_version)` so determinism is a *replayable test*, not an assumption.

**Why a table, not a materialized view:** `MATERIALIZED VIEW` forces all-or-nothing full recompute of ~20M rows per delta; a loader-written table allows per-security incremental refresh and carries provenance. Materializing a *pure function* of (raw + factors + calendar) is a cache, not vendor drift — it is deterministic and fully reproducible.

**HARD RULE (load-bearing):** corporate-action factors are derived **only from explicit action records**, never reverse-engineered from adjusted/raw price ratios. Reconstruction from `adj/raw` re-imports the exact vendor drift this design exists to escape. Enforced at the source-abstraction boundary.

**Survivorship-bias invariant:** `v_prices_adjusted` and `fact_returns` MUST include delisted securities. Silently filtering `status='delisted'` reintroduces survivorship bias — the cardinal quant-research sin. This is a tested correctness invariant, not an option.

**Affects:** schema, loader, all downstream research consumers.

### Source Abstraction Contract

`fetch_ohlcv(figi, start, end) -> OhlcvResult`:

```
OhlcvResult:
  prices: DataFrame[date, open, high, low, close, volume]   # RAW, unadjusted
  splits: list[Split(ex_date, ratio: Decimal)]              # ratio new/old; 2:1 -> 2
  dividends: list[Dividend(ex_date, amount: Decimal, currency: str)]  # gross cash
  source: str            # "yfinance" | "eodhd"
  retrieved_at: datetime
```

- Adapters return raw OHLCV + normalized corporate actions — **never** adjusted prices across the seam.
- Actions keyed by **ex-date**; amounts `Decimal`; currency ISO-4217 explicit (no implicit USD); missing actions = explicit `[]`, not null.
- **Adapter selection by config/registry**, not import. `source` stamped on every record (provenance is non-negotiable for auditing factors).
- **Cross-vendor contract test** compares *derived cumulative factors* (not prices): split factors exact (`Decimal`, tol 0), dividend amounts tol max(0.5% rel, $0.005 abs), ex-dates exact (tol 0 days).
- If a vendor exposes only adjusted prices with no actions series → adapter raises `UnsupportedSourceError`, never guesses. yfinance uses `auto_adjust=False` for raw OHLC + `Ticker.actions`.

### D3 — Trading calendar: `exchange_calendars` 4.13.2 → versioned reference table

Snapshot the library output into a versioned `trading_calendar` reference table in Postgres; views/loader read the DB table, not the library at query time. Prerequisite for D0's lookback anchoring. Calendar version participates in the `input_hash`.

### Migration tooling: Sqitch (plain SQL)

Plain-SQL migrations, not Alembic — there is no SQLAlchemy ORM (psycopg + pandas + SQL). Sqitch over a homegrown runner for dependency ordering and verify/revert. The recompute command that rebuilds derived layers must be **deterministic and version-controlled alongside the migrations** (required by the DR story below).

### D2 — Anomaly detection: `prices_review` surface that annotates, does not gate

A `prices_review` surface flags suspect rows: >±50% single-day moves **and** calendar-vs-data divergence (price on a non-calendar day; calendar trading day with no price). **Two-stage semantics — annotate at ingestion, gate at materialization:** the flagged price *does* land in `prices_raw` (the pipeline never halts on a human, and legitimate large moves like biotech binary events are never quarantined), but `fact_returns` recompute **excludes any row whose inputs reference an unreviewed `prices_review` flag**. This prevents a suspect price from producing an authoritative-looking, `input_hash`-stamped return row. Once a flag is reviewed (confirmed real or corrected), the affected security enters the dirty set and its returns materialize. Idempotent UPSERT on `(figi, date)`. *(Reconciles the prior "annotate, don't block" vs. "gate before recompute" wording — annotation and gating happen at different layers, not in conflict.)*

### D1 — Immutable history default + pinned re-fetch sweep

Delta mode never re-fetches old dates (immutable default). A **weekly trailing-90-day re-fetch-and-compare sweep** ships in v1 (cadence pinned, not "TBD") so source-side retroactive corrections are detected and recoverable. Addresses PRD parked item Q2.

### D4 — GICS: slowly-changing-dimension shape, current-only data

Store classification in an SCD-shaped table now; populate current-only (financedatabase is current-only). **This is the one genuine one-way door** — shipping a flat table loses point-in-time sector history forever; the SCD shape is cheap insurance. Data population is independent and deferrable. Addresses PRD parked item Q3.

### Identity / Security Master data model

- **`securities`** — PK `composite_figi`; `status`, `delist_date`, `share_class_figi` (nullable column, 1-to-many grouping). **Soft-delete always; never delete a security** (survivorship-bias constraint).
- **`security_symbology`** — effective-dated temporal table `(composite_figi, symbol_type, symbol_value, exchange, valid_from, valid_to)`. FIGI-as-PK is insufficient alone; ticker/exchange drift needs valid-time history. **Effective-dated, not bitemporal** (boring wins; full bitemporal deferred until audit-of-belief is actually needed).
- **`securities_review_queue`** — fed by ingestion seeing a ticker resolving to zero/multiple FIGIs, and by OpenFIGI ambiguous/no-match.
- Corporate-action factors are keyed on **CompositeFIGI** (a split/dividend hits one class, not the ShareClassFIGI cluster). ShareClassFIGI is for grouping/analytics only.
- FIGI assignment stays decoupled from price ingestion (OpenFIGI outage must not block price updates for identified securities).

### Universe seed (scope correction)

"Universe management is a separate module" was hiding a hard dependency — sym cannot be built or tested without real securities. Resolution:

- **MVP seed = the ~50 adversarially-chosen benchmark names** (splits, reverse splits, special/stock dividends, spinoffs, multi-currency, ADRs, at least one delisting). The *same set* serves three purposes: factor contract fixtures, the SM-6 accuracy metric, and the MVP universe.
- **4–8k is the warehouse's capacity ceiling, not a day-one requirement.** Prove end-to-end on the 50, add a few hundred liquid names for breadth, earn the rest. Volume is a scaling problem, not an MVP gate.

### EODHD fixture sequencing (minimum initial spend)

The thing worth money is **frozen ground-truth corporate-action data**, not a running subscription.

- **Now ($0):** source-abstraction contract as source-agnostic law; adapter registry; HARD RULE enforced at boundary; hand-built fixtures for 5–10 hand-verifiable events; build the EODHD adapter + its fixture-replay test (without running it live).
- **One month (~$20, then cancel):** subscribe to EODHD, pull raw `/div` + `/splits` for the ~50 benchmark names, commit the **raw dated JSON** as replay fixtures. Factor trust proven against production-grade data forever at zero ongoing cost.
- **Defer ($0 until needed):** live EODHD credentials, rate-limit handling, incremental sync — config flips, not architecture.
- Accepted trade-off: EODHD *API drift* uncaught until live (a re-subscribe-and-recapture event, not a rewrite). yfinance is a throwaway dev scaffold and never the correctness oracle (commercial buyer cannot legally use it).

### Operational model

- **No long-running service.** Every phase is an idempotent CLI command (`uv run sym backfill`, `uv run sym delta`).
- **Windows Task Scheduler**, daily trigger, "wake the computer to run" + "run ASAP if a scheduled start was missed."
- **`delta` computes the gap from DB state, never the clock** → gap-fill and backfill are the *same code path* (backfill = delta with an earlier floor). A machine off for days catches up automatically. Zero-gap `delta` is a no-op.
- **`pipeline_backfill_progress`** per-figi: `status` (pending/in_progress/done/error), `cursor_date` (last date committed), `attempt_count`, `last_error`, `updated_at`. Resume = select pending/in_progress.
- **Idempotency contract:** one transaction per figi per batch — write raw rows + advance `cursor_date` + set status atomically. *Never advance the cursor without the rows.* UPSERT `ON CONFLICT (figi, date) DO UPDATE`. 429 → backoff+jitter, cap retries, mark `error` and continue (don't abort run). Defining test: a second consecutive `delta` produces zero net mutations.

### Durability & Disaster Recovery

- **Native Windows PostgreSQL 18.4 install** (Windows service, NTFS data path) — not Docker Desktop or WSL2 (fewer moving parts, backable-up path).
- **Backup splits along the source-of-truth fault line:** `pg_dump` only raw OHLCV + factors + identity/FIGI + calendar; `--exclude-table` the recomputable `fact_returns`. Cheap, frequent. Recovery trades a minutes-long recompute for days of avoided refetch.
- **Recomputability is the DR asset:** derived layers are build artifacts. Recovery = fresh PG → run migration → `pg_restore` raw+factors+identity+calendar → run the deterministic recompute command. (This is why the recompute command must be version-controlled with the migrations.)
- **3-2-1:** external USB disk + client-side-encrypted cloud object storage (e.g. Backblaze B2 / S3). A private, encrypted personal backup is *storage, not redistribution* — stays clear of the licensing line provided it is never shared, published, or served.

### Flag back to PRD — SM-6 returns-accuracy metric (open item)

The PRD's success metrics (SM-1..SM-5) are all infrastructure pass/fail; none validate that returns are **correct**. A subtle total-return reinvestment-timing error would pass every existing metric. **Recommended SM-6:** compare sym PR/TR against an independent published series for the ~50 adversarial benchmark names, per-window tolerance (~5bps for clean names, stated-looser for corporate-action-heavy), as a **regression gate on every returns-engine change**. This is a PRD gap to route back to `bmad-prd`, not an architecture decision.

### Decision Impact Analysis

**Implementation sequence:**
1. Project init (`uv init --lib sym`)
2. Schema + Sqitch migrations (incl. deterministic recompute command)
3. Trading-calendar reference load (D3)
4. Source-abstraction contract + adapter registry + contract test; hand fixtures; EODHD adapter + fixture-replay (capture ~$20 golden fixtures)
5. Identity / FIGI resolution (`securities`, `security_symbology`, review queue) — seed the ~50 benchmark names
6. Price ingestion (`prices_raw`) + `prices_review` (D2) + `pipeline_backfill_progress`; idempotent `backfill`/`delta` CLI
7. `v_prices_adjusted` view + `fact_returns` loader (dirty-set, `input_hash`)
8. Returns-accuracy validation harness (SM-6) against benchmark names

**Cross-component dependencies:** D3 calendar precedes D0 views (lookback anchoring + `input_hash`); D2 review gates before `fact_returns` recompute (no garbage materialization); HARD RULE (explicit factors only) underpins D0's determinism; survivorship invariant constrains both `v_prices_adjusted` and `fact_returns`; the raw/derived split simultaneously enables incremental refresh AND the backup/DR strategy; the ~50 benchmark names unify factor fixtures + SM-6 + MVP seed.

## Implementation Patterns & Consistency Rules

### Critical Conflict Points Identified

Eight areas where independent implementers could diverge: SQL identifier naming, money/ratio types, date & timezone handling, the adapter contract shape, NULL semantics, idempotency/transaction discipline, Python module layout, and logging/error surfaces.

### Naming Patterns

**Database (PostgreSQL):**
- Tables: `snake_case`, singular for entity tables (`security`). The established names fixed by Step 4 override the singular rule: `prices_raw`, `fact_returns`, `prices_review`, `securities_review_queue`, `pipeline_backfill_progress`, `trading_calendar`, `security_symbology`. Views prefixed `v_` (`v_prices_adjusted`).
- Columns: `snake_case` (`composite_figi`, `ex_date`, `delist_date`, `input_hash`).
- FIGI columns always `composite_figi` / `share_class_figi` — never `figi` bare, never `cfigi`.
- PKs natural where stable (`composite_figi`); composite PKs ordered most-selective-first (`fact_returns` = `(security_id, window_id, asof)`).
- Indexes: `idx_<table>_<cols>`; FKs: `<table>_<reftable>_fk`.

**Python:**
- Package `sym` under `src/`; modules `snake_case.py`; functions `snake_case`; classes `PascalCase` (`OhlcvResult`, `Split`, `Dividend`); constants `UPPER_SNAKE`.
- Adapter modules: `sym.sources.<vendor>` (`sym.sources.yfinance`, `sym.sources.eodhd`); each exposes a class implementing the `fetch_ohlcv` contract, registered by config key.

### Data Type & Format Patterns

- **Money, prices, dividend amounts, split ratios → `Decimal`** end to end (Python `Decimal`, PG `NUMERIC`). **Never `float`** for any value feeding a return. Volume is `BIGINT`.
- **Currency:** ISO-4217 string, explicit on every monetary row. No implicit USD.
- **Dates:** corporate actions and prices keyed by **ex-date**, type `DATE` (calendar-day facts, not timestamps). Returns `asof` is `DATE`.
- **Timezones:** all stored dates are exchange-local trading dates; no UTC conversion in sym.
- **NULL semantics:** insufficient-history return windows are `NULL`, never `0`, never a sentinel. Missing corporate actions = empty list `[]` in the adapter layer, never `None`.
- **Booleans:** real `BOOLEAN`, not `0/1` or `'Y'/'N'`.

### Structural Patterns

- Tests at `tests/`, mirroring `src/sym/` package paths; SQL fixtures and committed vendor golden-fixtures under `tests/fixtures/`.
- SQL migrations under `migrations/` (Sqitch layout); the deterministic recompute command lives in-package, version-controlled alongside migrations.
- CLI entrypoints: `uv run sym <verb>` — `backfill`, `delta`, `recompute`, `sweep` (all idempotent).

### Process Patterns (mandatory disciplines)

- **Idempotency:** all writes UPSERT `ON CONFLICT (...) DO UPDATE`. One transaction per figi per batch: raw rows + `cursor_date` advance + status, atomically. Never advance a cursor without its rows.
- **Determinism:** every `fact_returns` row carries `input_hash = hash(raw_slice + factor_set + calendar_version)`. Derived layers are pure functions of raw inputs — no nondeterministic SQL (`now()`, random ordering) in `v_prices_adjusted` or the recompute path.
- **Factor derivation:** factors come only from explicit corporate-action records. Reverse-engineering from adjusted/raw price ratios is forbidden.
- **Survivorship:** delisted securities always flow through `v_prices_adjusted` and `fact_returns`. No silent `status='delisted'` filtering.
- **Anomaly handling:** `prices_review` annotates, never gates ingestion.
- **Retries:** 429 → exponential backoff + jitter, capped; on exhaustion mark `status='error'` and continue — never abort the run.

### Logging & Error Surfaces

- Structured logging (key=value or JSON): `INFO` per-figi progress, `WARNING` for `prices_review` flags and retries, `ERROR` for exhausted retries / contract violations.
- Adapter contract violations (e.g. adjusted-only source) raise typed exceptions (`UnsupportedSourceError`), never silent fallback.

### Enforcement

**Every implementer MUST:** use `Decimal` for all return-feeding numerics; key actions by ex-date; UPSERT for idempotency; preserve delisted names; derive factors only from explicit records; never write nondeterministic SQL into derived layers. **Verification gates:** the re-run-safety test (second `delta` = zero net mutations) and the `input_hash` replay test catch most violations mechanically.

## Project Structure & Boundaries

### Complete Project Directory Structure

```
sym/
├── README.md
├── pyproject.toml                 # uv-managed; deps: psycopg[binary], pandas, yfinance,
│                                  #   financedatabase, openfigi, exchange_calendars
├── uv.lock                        # reproducible lockfile
├── .python-version
├── .gitignore
├── .env.example                   # DB DSN, EODHD_API_KEY (commented; dev uses yfinance)
├── sqitch.conf                    # Sqitch project config
├── src/
│   └── sym/
│       ├── __init__.py
│       ├── config.py              # settings: DB DSN, active source key, paths
│       ├── cli.py                 # `uv run sym <verb>`: backfill | delta | recompute | sweep
│       ├── db.py                  # psycopg connection/transaction helpers
│       ├── models.py              # OhlcvResult, Split, Dividend dataclasses (the contract types)
│       ├── sources/               # ── SOURCE ABSTRACTION BOUNDARY ──
│       │   ├── __init__.py
│       │   ├── base.py            # Source protocol: fetch_ohlcv(figi, start, end) -> OhlcvResult
│       │   ├── registry.py        # config-keyed adapter selection (NOT import-based)
│       │   ├── errors.py          # UnsupportedSourceError, RateLimitError
│       │   ├── yfinance.py        # dev adapter (auto_adjust=False + Ticker.actions)
│       │   └── eodhd.py           # reference adapter (built now, runs later; /div, /splits)
│       ├── identity/              # ── SECURITY MASTER BOUNDARY ──
│       │   ├── __init__.py
│       │   ├── figi.py            # OpenFIGI resolution (decoupled from price ingestion)
│       │   ├── symbology.py       # effective-dated ticker/exchange history writes
│       │   └── review_queue.py    # securities_review_queue population
│       ├── ingest/                # ── MARKET DATA BOUNDARY ──
│       │   ├── __init__.py
│       │   ├── backfill.py        # resumable; per-figi cursor; transaction-per-figi-batch
│       │   ├── delta.py           # gap-from-state (shares core path with backfill)
│       │   ├── sweep.py           # weekly trailing-90-day re-fetch-and-compare
│       │   ├── progress.py        # pipeline_backfill_progress read/write
│       │   └── review.py          # prices_review anomaly annotation (±50%, calendar divergence)
│       ├── returns/               # ── RETURNS ENGINE BOUNDARY ──
│       │   ├── __init__.py
│       │   ├── factors.py         # derive cumulative factors from EXPLICIT actions only
│       │   ├── recompute.py       # deterministic; rebuilds fact_returns on dirty set; input_hash
│       │   └── windows.py         # the 18 FactSet window definitions
│       ├── calendar/
│       │   ├── __init__.py
│       │   └── snapshot.py        # exchange_calendars -> versioned trading_calendar table
│       └── classification/
│           ├── __init__.py
│           └── gics.py            # financedatabase -> SCD-shaped gics table (current-only data)
├── migrations/                    # Sqitch: plain-SQL, dependency-ordered
│   ├── sqitch.plan
│   ├── deploy/                    # securities, security_symbology, prices_raw, factors,
│   │                             #   trading_calendar, fact_returns, prices_review,
│   │                             #   securities_review_queue, pipeline_backfill_progress,
│   │                             #   gics_scd, v_prices_adjusted (view)
│   ├── revert/
│   └── verify/
├── benchmark/
│   └── seed_universe.toml         # the ~50 adversarial names (MVP seed = fixtures = SM-6 set)
└── tests/
    ├── conftest.py                # scratch-schema / testcontainers Postgres fixture
    ├── fixtures/
    │   ├── eodhd/                 # committed raw dated JSON golden fixtures (~$20 capture)
    │   └── manual/                # 5-10 hand-verified corporate-action cases
    ├── sources/
    │   └── test_source_contract.py # cross-vendor derived-factor equivalence (AC-5/6/7)
    ├── returns/
    │   ├── test_factors.py        # golden-vector vs FactSet EXDATE_C, tolerance-based
    │   ├── test_adjusted_view.py  # determinism + NULL-base semantics
    │   └── test_survivorship.py   # delisted names MUST appear in returns
    ├── ingest/
    │   └── test_idempotency.py    # second delta = zero net mutations
    └── test_accuracy.py           # SM-6: PR/TR vs published series on benchmark names
```

### Architectural Boundaries

- **Source abstraction (`sources/`):** the only place vendor specifics live. Everything upstream consumes `OhlcvResult`. Adapter chosen by config key via `registry.py` — swapping yfinance→EODHD is a settings change, not a code change. Adapters emit raw prices + explicit actions only; never adjusted prices.
- **Security master (`identity/`):** owns `securities` + `security_symbology` + review queue. Exposes `composite_figi` as the join key. Decoupled from `ingest/` — FIGI resolution failure does not block price updates for already-identified names.
- **Market data (`ingest/`):** writes `prices_raw` + `prices_review` + `pipeline_backfill_progress`. Owns the idempotency/transaction discipline. Never touches derived layers.
- **Returns engine (`returns/`):** reads raw + factors + calendar, writes `fact_returns`. `recompute.py` is the deterministic command the DR procedure depends on — version-controlled with migrations. Pure function; no nondeterministic SQL.
- **Data boundary:** raw inputs (`prices_raw`, factors, identity, `trading_calendar`) are source-of-truth and backed up; `v_prices_adjusted` + `fact_returns` are recomputable build artifacts excluded from backup.

### Requirements → Structure Mapping

- **FR-1..FR-3 (identity/FIGI/share-class)** → `src/sym/identity/`, migrations `securities` + `security_symbology`
- **FR-4 (GICS classification)** → `src/sym/classification/gics.py` + `gics_scd` (OI-4 correction: classification domain, not `identity/`)
- **FR-5..FR-8 (adjusted price ingestion, three-phase, source abstraction)** → `src/sym/ingest/` + `src/sym/sources/`
- **FR-9..FR-11 (18-window PR/TR, recompute)** → `src/sym/returns/` + `v_prices_adjusted` + `fact_returns`
- **FR-12 (exchange/calendar scope)** → `src/sym/calendar/` + `trading_calendar`
- **FR-14 (securities review queue)** → `identity/review_queue.py` + `securities_review_queue`
- **FR-15 (anomaly staging → relocated)** → `ingest/review.py` + `prices_review`
- **NFR-8 (commercial gate)** → `sources/` boundary (yfinance dev-only, EODHD reference); enforced by config, not code

### Data Flow

`registry → source adapter (raw + actions) → identity resolve (composite_figi) → ingest writes prices_raw + flags prices_review → factors derived from explicit actions → v_prices_adjusted (view) → recompute writes fact_returns (dirty set, input_hash) → DBeaver / research consumers query fact_returns`. Calendar snapshot feeds adjustment + window anchoring; sweep periodically re-fetches to detect source corrections.

## Architecture Validation Results

### Coherence Validation ✅ (one defect found and fixed)

**Decision Compatibility:** All technology choices reinforce one another. No ORM → Sqitch plain-SQL migrations (not Alembic) is a forced-correct consequence, not an arbitrary pick. `Decimal`/`NUMERIC` end-to-end serves returns correctness. PostgreSQL 18.4 at ~12–15 GB is right-sized (DuckDB deferred until ~100 GB). uv + `src` layout fits the importable-package shape. The FR-11 "incremental recompute" contradiction is dissolved by D0's three-layer model.

**Defect found during validation (now resolved in-doc):** The D2 anomaly section ("annotate, don't block") contradicted the Decision Impact Analysis ("D2 review gates before `fact_returns` recompute"). Because `fact_returns` is a persisted, `input_hash`-stamped table, an unreconciled stance would let a suspect ±50% price become an authoritative-looking return row. **Resolved to a two-stage rule:** annotate at ingestion (the flagged price lands in `prices_raw`, pipeline never halts), gate at materialization (`fact_returns` recompute excludes rows whose inputs reference an unreviewed `prices_review` flag; reviewed flags re-enter the dirty set). Coherence is ✅ as-fixed.

**Pattern Consistency:** Implementation patterns directly support the decisions — `Decimal` everywhere feeding returns, ex-date keying, UPSERT idempotency, NULL-base semantics, factors-from-explicit-records-only, no nondeterministic SQL in derived layers. Naming conventions are fixed and unambiguous. Mechanical verification gates exist (re-run-safety test, `input_hash` replay test).

**Structure Alignment:** The directory tree enforces the architectural boundaries — `sources/` is the only home for vendor specifics, `identity/` is decoupled from `ingest/`, `returns/recompute.py` is the version-controlled deterministic command the DR story depends on. The raw/derived split simultaneously enables incremental refresh and the backup fault line.

### Requirements Coverage Validation ⚠️ (complete except for reference-table gaps)

**Functional Requirements Coverage:** FR-1, FR-2, FR-3, FR-5, FR-6, FR-7, FR-9, FR-10, FR-11, FR-14 fully supported; FR-15 supported via documented relocation to `prices_review` (D2). Open items surfaced by an Active Recall coverage walk against the PRD:
- **FR-4 (GICS storage)** — correctly homed in `classification/gics.py` + `gics_scd` (D4), but the Requirements → Structure Mapping mislabels it under `identity/`. Mapping correction needed.
- **FR-8 (pipeline run logging)** — `pipeline_backfill_progress` is a *per-figi cursor*, not the per-run monitoring surface NFR-7 names. Decide whether it doubles as the FR-8 surface or a separate `pipeline_run_log` table is required.
- **FR-12 (exchange/market reference table)** — conflated with `trading_calendar`; an exchange reference table (MIC, name, scope) distinct from the calendar is missing.
- **FR-13 (currency reference table)** — ISO-4217 currency reference table is unaddressed in modules and migrations.

**Non-Functional Requirements Coverage:** Reproducibility (`input_hash` replay), idempotency (transaction-per-figi-batch, second-delta-zero-mutations test), durability/DR (recomputable derived layers + raw-only backup), per-security transaction boundary (NFR-6), and the NFR-8 commercial gate (config-enforced at the `sources/` boundary, yfinance dev-only) are architecturally supported. Reconciliations:
- **NFR-1** — PRD requires ±50% moves "not written to the returns tables until manually reviewed." The architecture's two-stage D2 rule now honors the *intent* (gate at materialization) while keeping ingestion unblocked. PRD wording should be reconciled to the two-stage semantics — route to `bmad-prd`.
- **NFR-5** — universal `created_at`/`updated_at` on all tables added to the patterns/enforcement rules.
- **NFR-2** — the `adjusted_close > close` check is **superseded** by the three-layer model (no vendor adjusted_close is stored); documented as obsolete rather than silently dropped.

### Implementation Readiness Validation ✅

**Decision Completeness:** All critical decisions documented with versions (PostgreSQL 18.4, uv 0.11.19, exchange_calendars 4.13.2). Each decision states rationale and what it affects.

**Structure Completeness:** File-level specific — named modules, migration layout, benchmark seed, mirrored test tree with named test files.

**Pattern Completeness:** Eight identified conflict points each have a ruling; enforcement names mandatory disciplines plus the mechanical gates that catch violations.

### Gap Analysis Results

**Critical — gating pre-implementation spike:**
- **View performance unconfirmed.** Decision 0 flagged "must confirm view performance at ~20M rows"; this is still open. Confirm `v_prices_adjusted` (and the `fact_returns` recompute) meet SM-4's <10s cross-sectional bound at full scale. If it fails, revisit the view/materialization boundary. Must run before the returns engine is certified.

**Important:**
- **Reference tables first.** Add `currency` (FR-13, ISO-4217) and `exchange` (FR-12, MIC/name/scope) reference tables, sequenced **before** `prices_raw`/`securities` so FKs (currency on monetary rows, exchange on securities/symbology) are clean from creation rather than retrofitted onto populated tables.
- **FR-4 mapping correction** — re-bucket to `classification/` in the Requirements → Structure Mapping.
- **FR-8 run-log decision** — declare `pipeline_backfill_progress` as the NFR-7 surface or add `pipeline_run_log`.
- **18-window return math specification** — EXDATE_C reinvestment timing, calendar anchoring (WTD/MTD/QTD boundaries, rolling same-calendar-date), CAGR annualization. This is the **#1 implementation-prep deliverable** for the returns epic — named explicitly, not assumed, since `windows.py` currently carries a label rather than a spec.
- **NFR-1 wording reconciliation** + **SM-6 returns-accuracy metric** — both routed to `bmad-prd`.

**Nice-to-Have:**
- D5 OpenFIGI rate-limit/batching tuning deferred (housed in `identity/figi.py`).
- EODHD API-drift uncaught-until-live is a documented, accepted trade-off.

### Validation Issues Addressed

The D2 annotate-vs-gate contradiction was resolved in-doc (two-stage semantics). The view-performance assumption is named as a gating Critical spike rather than absorbed. The return-math spec is named as the top returns-epic deliverable. Reference-table gaps (FR-12/13) and the FR-4 mapping correction are recorded with a sequencing instruction. NFR-1 reconciliation and SM-6 are routed to `bmad-prd`. No item requires architectural redesign.

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**Architectural Decisions**
- [x] Critical decisions documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Performance considerations addressed *(open: view-perf spike at ~20M rows — gating, see Gap Analysis)*

**Implementation Patterns**
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified
- [x] Process patterns documented

**Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [ ] Requirements to structure mapping complete — *open: FR-4 mis-bucket, FR-8 partial, FR-12/FR-13 reference tables missing (see Gap Analysis)*

### Architecture Readiness Assessment

**Overall Status:** READY WITH MINOR GAPS

**Confidence Level:** Medium-high, conditioned on two must-do-before-epics items: (1) the D2 annotate/gate contradiction — **resolved in-doc**; (2) the `v_prices_adjusted` view-performance spike at ~20M rows — **still open**. All remaining gaps are reference-table additions, a mapping correction, a return-math spec (returns-epic prep), or PRD-wording reconciliations — none require architectural redesign.

**Key Strengths:**
- Three-layer returns model (raw → deterministic view → loader-written fact table) resolves materialize-vs-compute while delivering correctness, incrementality, and DR from one decomposition.
- HARD RULE (factors only from explicit actions) and the survivorship-bias invariant are stated as tested, non-negotiable correctness constraints.
- Source abstraction as a config-keyed seam keeps the yfinance→EODHD swap and commercial pluggability as settings changes, not code changes.
- Recomputability-as-DR-asset shrinks the backup surface to source-of-truth only.
- The ~50 adversarial benchmark names unify factor fixtures, the SM-6 metric set, and the MVP universe.

**Areas for Future Enhancement:**
- Point-in-time GICS data (SCD shape ready, current-only data populated).
- Full 4–8k universe scale-out and the view-performance confirmation.
- Live EODHD ingestion + rate-limit handling (config flips, deferred).
- Full bitemporal symbology (effective-dated now; audit-of-belief deferred).

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented.
- Use implementation patterns consistently — `Decimal` for all return-feeding numerics, ex-date keying, UPSERT idempotency, factors from explicit records only, no nondeterministic SQL in derived layers, delisted names always preserved, `created_at`/`updated_at` on every table.
- Respect the four boundaries (`sources/`, `identity/`, `ingest/`, `returns/`) and the raw/derived data fault line.
- Honor the two-stage D2 rule: annotate at ingestion, gate `fact_returns` at materialization.
- Refer to this document for all architectural questions.

**First Implementation Priority:**

```bash
uv init --lib sym
cd sym
uv add psycopg[binary] pandas
uv add yfinance financedatabase openfigi exchange_calendars
uv add --dev pytest ruff
```

Then schema + Sqitch migrations — **reference tables (`currency`, `exchange`) first**, then `securities`/`security_symbology`/`prices_raw`/factors/`trading_calendar`/`fact_returns`/`prices_review`/queues/`gics_scd`/`v_prices_adjusted` — including the deterministic recompute command, per the Decision Impact Analysis sequence.
