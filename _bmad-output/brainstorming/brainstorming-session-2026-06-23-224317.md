---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'Storing daily commodities data in QRP — research the main commodities and design a data-pull/ingest mechanism modeled on the existing equities & indices pipelines'
session_goals: 'Map the commodity universe (energy/metals/agri/softs/livestock), pick reachable EOD sources, design the storage schema + as_of_date/PIT conventions, and a pull mechanism reusing QRP peer-package patterns (source adapters, load/audit verbs, Dagster scheduling, validate checks)'
selected_approach: 'ai-recommended'
techniques_used: ['First Principles Thinking', 'Analogical Thinking / Trait Transfer', 'Reverse Brainstorming']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Andre
**Date:** 2026-06-23

## Session Overview

**Topic:** Storing daily commodities data in QRP — research the main commodities and design a data-pull/ingest mechanism modeled on the existing equities & indices pipelines.

**Goals:**
- Identify the main commodities to cover and how to bucket them (energy, precious/base metals, agriculture, softs, livestock).
- Choose reachable EOD data sources (env-probed; FRED + live quotes are blocked, B3/yfinance-EOD/WorldBank/ECB reachable).
- Design the storage schema + canonical `as_of_date`/PIT conventions, mirroring `sym` (equities/indices) and the `rates` peer package.
- Design the pull mechanism reusing QRP patterns: standalone peer package, source-adapter registry, `load`/`audit` vocabulary, Dagster scheduling with explicit timezone, `validate` checks.

### Session Setup

_Fresh session. Topic supplied at invocation; facilitator reflected it back into the parameters above._

## Technique Selection

**Approach:** AI-Recommended Techniques

**Recommended sequence:**
- **First Principles Thinking** (deep) — strip commodities to fundamentals; define the canonical datum, identity key, unit, currency, and how `as_of_date` applies. Foundation for the schema.
- **Analogical Thinking / Trait Transfer** (creative/structured) — map the equities (`sym`), indices, and `rates` pipelines onto commodities; decide what transfers vs. what's new. Produces the pull-mechanism design.
- **Reverse Brainstorming** (creative) — "how would we corrupt/break commodities data?" — roll/expiry, continuous-contract stitching, negative prices, unit/FX traps — turning failure modes into design requirements + `validate` checks.

**AI Rationale:** Concrete, structured engineering topic with proven in-house pipelines to model on — so deep→analogical→adversarial fits better than blue-sky/theatrical methods.

## Idea Log

### First Principles Thinking

**[Foundations #1]**: Two-tier hybrid atomic model
_Concept_: Store the granular real observation, derive the rest (the `rates` philosophy). Tier A = **continuous/generic series for every commodity** (front-month ± 2nd/3rd), deep history — the backtesting backbone. Tier B = **full dated-futures curve (all maturities)** for a watchlist of majors (WTI, Brent, Gold, Copper, NatGas…) — for curve/carry research. Spot/fixing proxies and any custom continuous roll are derived on read.
_Novelty_: Avoids the lossy trap of storing only a pre-rolled series; lets backtests change the roll rule after the fact. Primary use confirmed: **research & backtesting** (so PIT-correctness and roll methodology are first-class, not afterthoughts).

**[Foundations #2]**: Canonical `commodity_code` spine + explicit unit/currency/exchange
_Concept_: Internal controlled vocabulary (`WTI`, `BRENT`, `GOLD`, `COPPER`, `NATGAS`, `CORN`…) tagged with `sector`; dated contract = code + delivery_year + delivery_month; continuous = code + generic_rank + roll_rule. `unit`, `currency`, `exchange` are mandatory explicit columns — never inferred. **One canonical (most-liquid) venue per commodity**, but stored self-describing so a second venue can be added later.
_Novelty_: Treats the unit/venue ambiguity (Copper USD/tonne LME vs USc/lb COMEX — a ~2200× gap) as a first-class corruption guard, not a footnote. Mirrors the in-house `sym_id` identity decision rather than chasing a non-existent free universal symbology.

**[Foundations #3]**: Raw-only storage, PIT-safe continuity derived on read
_Concept_: Never store a back-adjusted continuous series (back-adjustment mutates all prior history at every new roll → look-ahead). Store only raw immutable observations; derive the continuous series + back-adjustment (Panama/ratio) on read. Atomic record = **settlement + volume + open_interest** (vol/OI required for realistic liquidity rolls). v1 roll rule = **calendar** (N business days pre-expiry); liquidity (vol/OI crossover) roll added later.
_Novelty_: Names the subtle PIT trap most commodity datasets fall into — a stored back-adjusted series silently rewrites the past. Forces the store to hold raw dated contracts (+vol/OI) and treat the roll rule as a read-time parameter, so backtests can change roll method without re-ingesting.

### Canonical model — synthesis (First Principles output)

A stored row is one of:
- **Dated futures observation** — `(commodity_code, exchange, delivery_year, delivery_month, as_of_date) → {settlement, volume, open_interest}`, with `unit`/`currency`. Tier B majors.
- **Vendor continuous observation** — `(commodity_code, generic_rank, roll_rule_tag, as_of_date) → {settlement, volume?, open_interest?}`. Tier A long tail (when only a vendor continuous is freely available).

Derived-on-read: our own continuous series + back-adjustment (from Tier-B matrices), spot/fixing proxies, term-structure/carry, calendar/seasonal spreads.

### Analogical Thinking / Trait Transfer

**[Scope #4]**: v1 = Tier A only (continuous series), Tier B deferred
_Concept_: v1 stores **vendor continuous series per commodity** (front-month OHLCV + vol/OI where available), deep history, free sources. The dated-futures matrix + our own roll/back-adjustment (Tier B) is deferred to a later phase. Collapses v1 complexity: no contract identity, no expiry, no roll logic in storage — the vendor's continuous already embeds the roll.
_Novelty_: Ships the backtesting backbone first (one clean series per commodity across all sectors) and defers the expensive, source-constrained matrix. The canonical model still holds; Tier B slots in later without reshaping the store.

**[Sources #5]**: yfinance continuous front-month as the v1 primary (probe-confirmed)
_Concept_: Probed 2026-06-23 — yfinance returns daily continuous front-month **OHLCV + Volume** for all 14 sampled commodities across every sector (CL=F, BZ=F, NG=F, GC=F, SI=F, HG=F, ZC=F, ZW=F, ZS=F, SB=F, KC=F, CT=F, LE=F, CC=F). History from ~2000 (Brent 2007). **No Open Interest** via yfinance. The `=F` series are raw non-back-adjusted front-month — matches the "store raw" principle. Mirrors how `sym` already uses yfinance for equity EOD.
_Novelty_: A single reachable, free, all-sector source covers the entire Tier-A universe daily — and its rawness aligns with the PIT principle instead of fighting it. Known gaps to fill later: no OI, ~2000 start (pre-2000 + OI = a Tier-B/secondary-source job).
_Probe caveats_: confirm yfinance roll/settlement semantics per ticker; `Close` ≈ settlement (store Close + Volume; `Adj Close` is redundant for futures).

---

## v1 Build Spec (decided — handoff to implementation)

Session paused here (Andre → build the monitor page autonomously). Decided v1 scope:

- **New peer package** `packages/commodities/` modeled on `rates` (standalone, library-first, own DB schema).
- **Tier A only:** vendor continuous front-month series per commodity. No dated-contract matrix / roll logic in storage (deferred Tier B).
- **Source:** yfinance continuous `=F` tickers (probe-confirmed reachable; daily OHLCV+Volume; ~2000+; no OI).
- **Canonical model:** `commodity_code` (controlled vocab) + `sector`; explicit `unit`/`currency`/`exchange`; `as_of_date` canonical; raw-only storage; PIT (`first_settle` immutable + restated `settle`); derive change/returns/vol on read.
- **Universe:** energy / precious metals / base metals / grains / softs / livestock (~25–30 codes).
- **Pipeline pattern:** source-adapter registry, `load`/`audit` verbs, Dagster schedule (explicit timezone), `validate` checks — all mirroring `rates`.
- **Console:** `/commodities` monitor page — Bloomberg-style (CMDTY/GLCO reference): sector-grouped grid with last / Δ / %Δ / sparkline, a sector heatmap, and a click-through history chart (using `lib/date-axis`).

### Deferred / follow-ups
- Tier B (full futures curve + vol/OI; needs a paid or alternative source) — term structure, carry, calendar spreads, our own roll + back-adjustment.
- Pre-2000 deep history + Open Interest (secondary source).
- Liquidity-based roll (vol/OI crossover) once Tier B lands.

