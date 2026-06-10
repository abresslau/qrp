---
stepsCompleted: ["step-01", "step-02", "step-03"]
inputDocuments:
  - "_bmad-output/brainstorming/brainstorming-session-2026-06-07-151227.md"
  - "_bmad-output/planning-artifacts/architecture.md"
  - "_bmad-output/planning-artifacts/epics-universe-layer.md"
  - "docs/data-conventions.md"
---

# sym FX Layer - Epic Breakdown

## Overview

This document decomposes the **sym FX-rate layer** (a new, additive capability on the
existing sym warehouse) into implementable epics and stories. The requirements source is
the FX-storage + data-source brainstorm (`brainstorming-session-2026-06-07-151227.md`),
with `architecture.md` and the existing `epics-*.md` as pattern cross-reference so the FX
layer reuses established conventions (AR-5 source abstraction, AR-6 explicit/immutable
inputs, AR-7 derive-don't-store, Sqitch plain-SQL migrations, psycopg3, DB-free unit tests
+ live verification, the `as_of_date` date-naming convention) rather than duplicating them.

**Why now:** the universe is multi-currency (IBOV→BRL, FTSE→GBP, EURO STOXX→EUR,
Nikkei→JPY, S&P→USD). To compare prices / market caps / returns across markets — and to
feed the planned analytics/backtest modules — everything must fold to a common currency.
FX is the missing converter. The design is a **USD-centered star**: store one observed
rate per currency against USD, derive every inverse and cross.

## Requirements Inventory

### Functional Requirements

FR1: **USD-centered star storage** — store one *observed* rate per `(base_currency, quote_currency, as_of_date, source)`; **USD-base preferred**; inverses and crosses are derived, never stored.
FR2: **Canonical direction** — a currency priority rank (USD highest, else alphabetical); enforce `rank(base) < rank(quote)` + `UNIQUE(base, quote, as_of_date, source)` so exactly one row exists per unordered pair (no redundant inverse, no both-direction cross).
FR3: **General `(base, quote)` schema** that admits a future *purchased direct cross* (e.g. a EURGBP fix) as a first-class row with zero schema change; the derivation layer prefers a direct row when present, else triangulates through USD.
FR4a: **Source-tagged, multi-source-ready** — every rate carries its `source`; a canonical rate per `(pair, date)` is chosen by **source precedence (trust tier)**, Frankfurter top for now.
FR4b *(deferred → **DELIVERED** 2026-06-08, see "ECB reconcile" below)*: **Cross-source divergence flag** — meaningless with a single source; lands with the ECB-reconcile second source. Not satisfiable by single-source FX2, so explicitly deferred (not claimed). Now delivered: `sym.fx.reconcile` + `sym fx divergence`.
FR5: **Frankfurter primary ingest** (ECB-backed, `base=USD`) — historical backfill (to 1999) + daily delta; rates **direction-normalized** to USD-base on ingest.
FR6: **Derivation layer** (`v_fx` view / functions) — inverse `= 1/rate`; cross `XXXYYY = rate(YYY)/rate(XXX)` triangulated through USD; `USD/USD = 1` injected (never stored).
FR7: **As-of resolution + dense weekday view** — the rate for date D is the most recent observed rate with `date ≤ D`; a **weekend span of 3 calendar days** carries Friday over the weekend / a Monday holiday, and a separate **outage cap of 7 days** from the last *observed* rate bounds forward-fill (beyond it → NULL + flag). The dense weekday series (`v_fx_daily`) is a **view-only** forward-fill (flagged `is_filled`); **no synthetic rows are ever stored** (same derive-don't-store principle as the returns engine). Stale lookups **return value + flag** (the resolver), never raise; the threshold is single-sourced and shared with `sym validate`.
FR8: **Conversion API** — `fx_rate(ccy, as_of)` and `convert(amount, from_ccy, to_ccy, as_of)` to express prices / market caps / returns across the multi-currency universe in a common currency.
FR9: **CLI + EOD** — `sym fx load` (tail by default; `--start_date` for full history) + coverage, wired as a step in the daily `sym eod` pipeline.
FR10: **Validation integration** — `sym validate` FX checks: missing pivot leg, staleness beyond the bound, and currency coverage vs the currencies actually needed by priced instruments.

### NonFunctional Requirements

NFR1: **Reconstructability** — observed rates are immutable + source-tagged; everything derived (inverse, cross, USD identity, staleness fills) is computed in views/functions, never stored. (Later: store raw EUR-base ECB + the EUR/USD leg so USD-base is independently re-derivable.)
NFR2: **Precision** — full-precision `NUMERIC`; never pre-round; round on display only (triangulation exactness).
NFR3: **Direction integrity (F1)** — a per-source direction map normalizes/inverts to USD-base on ingest (e.g. Yahoo's `EURUSD=X` is EUR-base while `USDBRL=X` is USD-base); a plausibility band catches a mis-mapped source.
NFR4: **Sanity guards** — `CHECK rate > 0` (F3); a day-over-day jump flag (akin to `prices_review`); two-leg *compounding* staleness for crosses (F4); no USD-as-a-currency row (F6).
NFR5: **Calendar-agnostic** — FX trades ~24/5 on its own calendar, distinct from equity calendars; as-of resolution bridges holiday mismatches; the base table is never forward-filled (fills, if any, live in a view + are flagged).
NFR6: **sym engineering patterns** — Sqitch plain-SQL migrations (deploy/revert/verify via Docker + `host.docker.internal`); psycopg3; DB-free unit tests + live verification; ruff (line-length 100); the `as_of_date` / `valid_from`-`valid_to` date-naming convention (Snowflake-portable); one durable transaction per unit of work.
NFR7: **Source honesty** — Frankfurter primary (ECB reference rates, free, no key) → ECB SDMX reconcile (later) → yfinance `=X` spot-check only; every rate carries provenance + a precedence tier; personal-research use.

### Additional Requirements

- **Design decisions (from the brainstorm)** govern the layer: USD pivot for ALL currencies (pure star graph, no per-currency anchors for now); daily EOD grain (evolve to named fixings/intraday later); store general `(base,quote)` USD-preferred (purchased direct crosses fit later); as-of resolution with a 4-day staleness bound; the canonical-direction rank rule.
- **Failure modes → guards (pre-mortem):** F1 wrong-direction ingest → per-source direction map + plausibility band; F2 triangulation rounding → full-precision NUMERIC; F3 zero/negative/garbage tick → `CHECK rate>0` + jump flag; F4 two-leg staleness for crosses → both legs within bound else NULL+flag; F6 accidental USD row → injected identity only. (F5 source disagreement, F7 redenomination/peg — deferred.)
- **New schema (Sqitch migrations):** an `fx_rate` table (immutable, source-tagged) with the rank-direction CHECK + UNIQUE, a `currency` priority/rank reference (or a rank function), and a `v_fx` derivation view; plus FX-gap fields surfaced to `sym validate`.
- **Source reality (deep-researched):** Frankfurter (`api.frankfurter.dev`, `?base=USD`) — free, no key/quota, ~31 ccys incl. BRL, daily to 1999, server-side USD-base. ECB SDMX (`ecbdata`) is EUR-base (invert) — the reconcile/ground-truth source. fawazahmed0 currency-api (CC0, 200+ ccys) is the breadth fallback. yfinance `=X` is spot-check only (stale/flat-print quality issues, ToS).
- **Scope boundary:** **daily EOD USD-base rates only** for now. OUT — intraday/named fixings (London 4pm WM/R, ECB, NY close), purchased direct-cross feeds, the ECB raw-EUR-base reconcile, peg/redenomination handling, and applying FX to restate prices/returns in USD (a downstream consumer, likely the analytics module).
- **Named dependencies/risks:** Frankfurter is a single volunteer-run service (no SLA) → keep the fallback wired; FX-vs-equity calendar misalignment is the main correctness risk (mitigated by as-of + staleness); the conversion *consumers* (USD-restated prices/market-caps) are out of this epic's scope but are its reason to exist.

### UX Design Requirements

N/A — the FX layer is a backend + CLI capability with no UI. Operator surfaces (`sym fx`, `sym validate` FX checks) are specified as functional requirements (FR9, FR10).

## Epic List

### Epic FX: FX-rate layer (USD-centered, derive crosses)

Store daily USD-base FX rates from a free authoritative source and expose as-of currency
conversion, so the multi-currency universe folds to a common currency for cross-market
comparison and the downstream analytics/backtest modules. **One epic, four ordered stories**
(single cohesive component, fully pre-designed, no inter-story feedback loop → the
consolidation rule). Linear dependency: FX1 → FX2 → FX3 → FX4.

Design decisions recorded from the brainstorm + the step-02 elicitation pass:
- Derivation is **cohesive in FX3** (FX1 is pure storage+integrity; FX1 holds no derivation view).
- The currency **rank** hangs off the existing `currency` reference table (FR-13), not a new one.
- Schema uses **`as_of_date DATE`** so a future intraday/named-fixings grain is *additive*.
- `convert()` is **Python** (sym lib); a thin `v_fx` SQL view serves ad-hoc DBeaver use.
- FX4's **coverage-vs-priced-instruments** check is the live consumer hook (anti-dead-code).

**FX1 — Storage + integrity.** Sqitch migration: immutable, source-tagged `fx_rate(base_currency,
quote_currency, as_of_date, rate, source)`; a currency priority rank on the `currency` table
(USD highest, else alphabetical); `CHECK rank(base) < rank(quote)` + `UNIQUE(base, quote,
as_of_date, source)` (one row per unordered pair); `CHECK rate > 0` (F3); guard against a
USD-self / USD-as-quote degenerate row (F6); full-precision NUMERIC (F2). DB-free tests for the
rank/direction rule. **FRs:** FR1, FR2, FR3. **NFRs:** NFR1, NFR2, NFR4, NFR6.

**FX2 — Frankfurter ingest.** An `fx` source adapter (Frankfurter `?base=USD`) + registry entry
mirroring the OHLCV source pattern; **direction-normalize to USD-base on ingest** (per-source
direction map, F1) + a tight plausibility band, with an explicit wrong-direction unit test (the
Yahoo `EURUSD=X` vs `USDBRL=X` case); source-tagged immutable write (`ON CONFLICT DO NOTHING`);
historical backfill (→1999) + daily delta, resumable + fail-graceful (no partial corruption).
DB-free parse/normalize tests + a live smoke. **FRs:** FR4, FR5. **NFRs:** NFR3, NFR7.

**FX3a — Derivation view + as-of resolver.** `v_fx` view (inverse `1/rate`, USD/USD=1 injected,
**no triangulation here**) + a dense weekday view `v_fx_daily` (carries last observed rate ≤ each
weekday, flagged `is_filled`/`observed_date`/`days_stale`, computed on read — no synthetic rows) +
`fx_rate(conn, ccy, as_of)` (weekend span 3 days; **outage cap 7 days** → None + flag). DB-free tests.
**FRs:** FR6 (inverse/identity), FR7. **NFRs:** NFR1, NFR2, NFR5.

**FX3b — Conversion API.** `convert(amount, from_ccy, to_ccy, as_of)` → `Decimal`; USD-leg / cross
**triangulation through USD**; same-currency identity; two-leg compounding staleness (each leg passes
AND leg-dates agree within the bound) → None + flag; direct-cross branch deferred (schema stays
general per FR3). DB-free pure-function tests. **FRs:** FR6 (cross), FR8. **NFRs:** NFR2, NFR5.

**FX4 — CLI + EOD + validation.** `sym fx load | coverage | convert` (the last is the
human-facing consumer smoke); an `fx` step wired into `sym eod` (idempotent/order-independent);
`sym validate` FX checks — missing pivot leg, staleness beyond the outage cap, and **currency
coverage vs the currencies needed by priced instruments** (the operational SLA). **FRs:** FR9, FR10.
**NFRs:** NFR6.

## FR Coverage Map

- FR1 → FX1 — USD-centered star storage (one observed rate per (base,quote,date,source))
- FR2 → FX1 — canonical direction (inlined CHECK + UNIQUE per unordered pair)
- FR3 → FX1 — general (base,quote) schema admitting a future direct cross
- FR4a → FX2 — source-tagged, multi-source-ready ingest + source precedence
- FR4b → *deferred* — cross-source divergence flag (needs a 2nd source; with the ECB reconcile)
- FR5 → FX2 — Frankfurter USD-base ingest, backfill + delta, direction-normalized
- FR6 → FX3a (inverse, USD identity) + FX3b (triangulated cross)
- FR7 → FX3a — as-of resolution; weekend span 3d + outage cap 7d; dense `v_fx_daily` (view-only fill)
- FR8 → FX3b — conversion API (`convert`); `fx_rate` resolver in FX3a
- FR9 → FX4 — CLI (incl. `convert`) + EOD step
- FR10 → FX4 — `sym validate` FX checks (missing leg / staleness / coverage SLA)

## Design refinements (party-mode + advanced-elicitation pass, 2026-06-07)

A roundtable (Winston/Architect, Amelia/Dev, John/PM, Mary/Analyst) + an elicitation pass
pressure-tested the decomposition. Resulting decisions, folded into the stories below:

- **FX3 split into FX3a + FX3b** (two independent votes) — derivation view + as-of resolver vs. convert/triangulation.
- **Inline the direction CHECK** — `CHECK (base_currency='USD' OR (quote_currency<>'USD' AND base_currency < quote_currency))`; a CHECK can't call a table-lookup rank function. The USD-as-quote and self-pair cases fall out of this one rule (no separate CHECKs). Locking canonical direction into a constraint makes a future EUR-pivot a deliberate migration — accepted.
- **Source precedence is required** — `UNIQUE(...,source)` admits multiple sources per (pair,date); the resolver MUST pick deterministically by a precedence order (Frankfurter top for now).
- **Plausibility band is RELATIVE** — reject on day-over-day |Δ| > N% vs the last observed rate for that currency (a static band is useless across JPY~150 / BRL~5 / GBP~0.8).
- **No synthetic rows, ever** — the base `fx_rate` table holds ONLY observed rates. The dense weekday series + forward-fill is a **pure view** (`v_fx_daily`), flagged `is_filled` + `observed_date`, computed on read — the same derive-don't-store reconstructability principle as the returns engine (`v_prices_adjusted` is a view; `fact_returns` is materialized-but-deterministic; neither inserts unobserved source data).
- **Spans:** normal **weekend span = 3 calendar days** (Fri to Mon); a separate **outage cap = 7 days** from the last *observed* rate, beyond which the view yields NULL + an FX-gap flag (so a vendor outage can't silently carry a stale rate). Two-leg cross staleness: each leg passes AND the two resolved leg dates agree within the bound.
- **Frankfurter provenance asterisk** — Frankfurter rebases ECB EUR-base to USD on request, so stored USD-base rates are *rebased*, not primary observations; noted, ECB raw-EUR reconcile deferred.
- **FR4 split** — FR4a (source-tagged ingest, delivered by FX2) vs FR4b (cross-source divergence flag, *deferred*; meaningless with a single source).
- **convert() owns triangulation; `v_fx` does NOT triangulate** (inverse + identity only) — one implementation of the cross math (no view/Python drift). `convert()` returns `Decimal` (explicit precision contract).
- **Defer the direct-cross branch in convert()** — keep the `(base,quote)` schema general (FR3) for a future purchased cross, but build no `convert()` branch a source does not yet feed.
- **A real consumer smoke:** `sym fx convert <amt> <from> <to> --as-of` (human-facing) so the loop is *watched* working, not only asserted by validation.
- **Corrections out of scope (v1)** — rates strictly immutable + source-tagged; a wrong-rate supersede path is explicitly deferred.

## Epic FX — Stories

### Story FX1: FX storage + canonical-direction integrity

As the operator, I want an immutable, source-tagged FX-rate table whose constraints make a
wrong-direction, redundant, or degenerate row impossible, so stored rates are trustworthy by
construction.

**Acceptance Criteria:**
- **Given** the Sqitch migration, **When** deployed, **Then** `fx_rate(base_currency, quote_currency, as_of_date, rate, source, inserted_at)` exists: `rate NUMERIC` (full precision), FKs `base_currency`/`quote_currency` to `currency`, `UNIQUE(base_currency, quote_currency, as_of_date, source)`, and an `inserted_at TIMESTAMPTZ` audit column.
- **Given** the inlined direction CHECK `(base_currency='USD' OR (quote_currency<>'USD' AND base_currency < quote_currency))`, **Then** `USD->BRL` and `EUR->GBP` are accepted while `BRL->USD`, `GBP->EUR`, USD-as-quote, and self-pairs are all rejected (FR2; F6 falls out for free).
- **Given** an insert with `rate <= 0`, **Then** it is rejected by `CHECK rate > 0` (F3).
- **Given** two sources for the same pair+date, **Then** both rows coexist (source in UNIQUE) and a documented **source-precedence order** (Frankfurter top) lets the FX3a resolver pick deterministically (FR4a).
- **Given** the immutability rule, **Then** corrections are out of scope (v1), documented; the loader has no UPDATE/DELETE path (append-only by convention).
- **And** DB-free unit tests cover the direction rule across representative pairs.

### Story FX2: Frankfurter USD-base ingest (backfill + delta)

As the operator, I want to ingest daily USD-base rates from Frankfurter, normalized + source-tagged,
so the table holds authoritative observed rates I can re-pull deterministically.

**Acceptance Criteria:**
- **Given** an `fx` source adapter registered like the OHLCV source (AR-5), **When** `fetch(currencies, start, end)` runs, **Then** it returns daily USD-base rates from Frankfurter `?base=USD`, tagged `source='frankfurter'`; a code comment records that these are ECB-rebased, not primary observations.
- **Given** a per-source **direction map**, **When** a source reports a non-USD-base quote, **Then** it is inverted to USD-base before write — covered by a DB-free unit test against **synthetic payloads** (a USD-base source and an inverted-quote source); the Yahoo `=X` adapter is out of scope, so the test uses synthetic inputs, not Yahoo tickers.
- **Given** the **relative plausibility band**, **When** a fetched rate moves more than N% vs the last observed for that currency, **Then** it is rejected/flagged, not stored.
- **Given** `sym fx load --start_date <floor>`, **Then** it loads history (to 1999 where available), **resumable** (re-running inserts only missing `(ccy, as_of_date)` rows via `ON CONFLICT DO NOTHING`) and **fail-graceful** (a vendor outage aborts cleanly, no partial corruption).
- **Given** `sym fx load` (no `--start_date`), **Then** only sessions after the latest stored `as_of_date` per currency are fetched.
- **And** a live smoke confirms `USDBRL`, `USDGBP`, `USDEUR` land with sane values.

### Story FX3a: Derivation view + as-of resolver (dense weekday series)

As a researcher, I want any currency's USD rate as-of any date, with holiday gaps transparently
carried forward, so I have a dense, honestly-flagged weekday series — with no synthetic rows in the
base table.

**Acceptance Criteria:**
- **Given** `v_fx`, **Then** it exposes the inverse (`1/rate`) and injects `USD/USD=1` — neither stored, no triangulation here (FR6 inverse/identity; NFR1).
- **Given** `v_fx_daily`, **Then** for each weekday it carries the **last observed rate <= that weekday** with `rate`, `observed_date`, `is_filled`, `days_stale` — computed on read; **weekends are not generated**; **nothing is inserted into `fx_rate`**.
- **Given** `fx_rate(conn, ccy, as_of)`, **When** an observed rate exists within the **weekend span (3 calendar days)**, **Then** it returns the carried rate; **When** the gap from the last *observed* rate exceeds the **outage cap (7 days)**, **Then** it returns `None` + a staleness flag; **And** `fx_rate(USD, ...)` returns 1; unknown-currency and known-but-stale are distinguishable.
- **And** DB-free tests cover: inverse, USD identity, weekday forward-fill across a normal weekend and a Monday holiday, the outage cap (NULL past 7 days), unknown-vs-stale.

### Story FX3b: Conversion API (triangulation through USD)

As a researcher, I want `convert(amount, from_ccy, to_ccy, as_of)` so I can fold any amount to any
currency as-of a date, with cross rates triangulated through USD.

**Acceptance Criteria:**
- **Given** `convert(amount, from_ccy, to_ccy, as_of)` returning `Decimal`, **When** one side is USD, **Then** it applies the single leg; **When** both are non-USD, **Then** it triangulates through USD (`amount * rate(to)/rate(from)`).
- **Given** `convert(x, EUR, EUR, ...)`, **Then** it returns `x` (identity, no rate lookup, never stale).
- **Given** a triangulated cross, **When** either leg is missing/stale beyond the bound **OR** the two resolved leg dates differ by more than the weekend span, **Then** it returns `None` + flag (two-leg compounding staleness, F4).
- **Given** the deferred direct-cross branch, **Then** triangulation is the only path in v1 (the `(base,quote)` schema stays general for a future purchased cross, but no `convert()` direct-cross branch is built yet).
- **And** DB-free pure-function tests cover: USD-leg, triangulated cross, same-currency identity, single-leg stale, two-leg stale, leg-date-spread exceeded, zero/negative amount.

### Story FX4: CLI + EOD wiring + validation

As the operator, I want `sym fx` commands (incl. a human-facing `convert`), an EOD step, and
`sym validate` FX checks, so FX stays current, gaps are caught, and the loop is *watched* working.

**Acceptance Criteria:**
- **Given** `sym fx load | coverage | convert`, **Then** they drive FX2 ingest, report coverage, and `convert <amt> <from> <to> --as-of` prints a human-readable conversion (the real consumer smoke); output is ASCII.
- **Given** `sym eod`, **Then** an `fx` (fill) step is included, error-isolated, and **idempotent / order-independent** so a future USD-restatement consumer can slot in after it.
- **Given** `sym validate`, **Then** FX checks report (classified pass/warn/fail, Epic-V style): **coverage** — for every instrument priced on day D in currency C, a non-stale C->USD rate resolves for D (denominator = currencies of currently-priced instruments); **staleness** beyond the outage cap; **missing pivot leg**.
- **And** the coverage check is the operational SLA, defined against priced-instrument currencies, not a static list.

## Build status (2026-06-08)

Epic FX **built + committed** — all five stories, 377 tests pass, migrations deployed:
- FX1 `fx_rate` + canonical-direction CHECK (commit `2ec9f07`)
- FX2 Frankfurter USD-base ingest (`9b75116`)
- FX3a `v_fx`/`v_fx_daily` views + as-of resolver (`3e94616`)
- FX3b `convert()` triangulation (`0463540`)
- FX4 `sym fx` CLI + EOD step + `check_fx_coverage` (`2ee7f6a`)

**Operational follow-ups (not blockers):**
- **Populate**: `sym fx load --start_date 1999-01-04` loads all `currency`-table currencies from 1999 (the smoke
  data was cleaned, so `fx_rate` is currently empty → `sym validate` fx_coverage WARNs
  "not populated", does not fail).
- **Known coverage gap**: Frankfurter (ECB) does **not** cover every traded currency — e.g.
  **TWD** (Taiwan) and a few exotics are outside its ~31-currency set. Those will show as
  `fx_coverage` failures until the **fawazahmed0 currency-api fallback** (deferred, FR4b-adjacent)
  or another source is wired. This is the documented reason the source layer is multi-source-ready.

## Autonomous session additions (2026-06-08, operator away)

Two items the operator requested then stepped away for; built with the decisions noted:
- **fawazahmed0 fallback** (commit `86b9bad`): `FawazahmedSource` (CC0 currency-api, breadth
  fallback). Scoped to **gap currencies only** (TWD) → no Frankfurter overlap, resolver stays
  unambiguous. Backfilled TWD 2024-06→now (524 rows; dated files only reach ~mid-2024, so the
  2020→2024 TWD deep gap remains a free-source limit). `fx_coverage` now **PASS**. DB: 194,341
  fx rows (193,817 frankfurter + 524 fawazahmed0), 28 currencies.
- **Currency restatement consumer** (was "deferred to analytics") — built thin per the PM voice:
  `fx/restate.py` `returns_in_currency` (any target ccy, dynamic) + `price_in_currency`; CLI
  `sym fx px` / `sym fx returns`. **Correct unhedged method** `(1+r_local)·FX_X(asof)/FX_X(base)−1`
  (not spot×return), with de-annualize→restate→re-annualize for annualized windows; TR restated by
  the endpoint FX ratio (standard approximation). On-demand, not materialized (thin primitive).

`sym validate`: **fx_coverage PASS**; FX introduced no new failures. The overall-FAIL is
pre-existing + unrelated (GICS completeness gap; EODHD-deferred unpriced delisted leavers).

## ECB reconcile — 2nd source + FR4b (2026-06-08, FX retro action A1)

The deferred FR4b cross-source divergence flag is now **delivered** by adding ECB SDMX as
the reconcile source (commit `d8eeeaf`):
- **`EcbSdmxSource`** (`source='ecb'`): ECB Data Portal EXR `csvdata` (EUR-base reference
  rates), **rebased to USD-base client-side** through the EUR/USD pivot
  (`CCY_per_USD = EUR→CCY / EUR→USD`; `EUR = 1/EUR→USD`); a date with no USD pivot leg is
  skipped (fail-graceful). `sym fx load --source ecb`.
- **Deterministic source precedence** — ECB *overlaps* Frankfurter (unlike the TWD-only
  fawazahmed0), so the read-side pick is pinned by a new `fx_source_rank()` SQL function
  (`frankfurter` 10 < `ecb` 20 < `fawazahmed0` 30), applied in the resolver + `v_fx_daily`;
  `SOURCE_PRECEDENCE` in `sym.fx.source` mirrors it. The resolver prefers Frankfurter.
- **`sym.fx.reconcile` + `sym fx divergence`** — compares two sources on overlapping
  `(ccy, date)`, flags relative divergence > threshold (default 0.5%). On-demand, not an
  always-on gate (needs both sources populated). Verified: Frankfurter vs ECB compared=75,
  diverged=0 (they share ECB fixings; ECB-rebased BRL 5.024472 ties Frankfurter's 5.0245).
- **Honest scope:** ECB's ~31-currency set **excludes TWD** (and a few exotics), so the
  2020→2024 TWD deep-history gap is **not** closed by ECB — it stays on the fawazahmed0
  fallback (a free-source floor). A1's reconcile/divergence half is fully delivered; the
  TWD-deep-history half is not achievable from ECB.
- **Populated (full backfill done):** `sym fx load --start_date 1999-01-04 --source ecb` loaded **193,437 ECB
  rows, 28 currencies, 1999-01-04→2026-06-05** (≈ Frankfurter's 193,817). 383 day-over-day
  jumps >50% were rejected by the plausibility band (early-2000s EM crisis/redenomination
  windows, e.g. TRY Feb-2001, BRL Jan-2000) — surfaced, not stored. **Full-history reconcile:
  `sym fx divergence` compared all 193,437 overlapping obs, diverged=0, max 0.000%** —
  Frankfurter and ECB agree to within rounding across 27 years, confirming the client-side
  EUR/USD rebase reproduces the server-side rebase at scale.
