---
title: "Product Brief: sym Universe Layer"
status: ready
created: 2026-06-06
updated: 2026-06-06
---

# Product Brief: sym Universe Layer

## Executive Summary

sym (Module 1) is a working global-equity Security Master + Market Data + Returns warehouse, but the *set of securities it tracks* is a hardcoded 50-name adversarial seed — chosen to stress-test the engine, not to be a real research universe. To use sym for research we need to point it at a real, definable, survivorship-safe universe, and to **change that definition** without re-plumbing the warehouse.

This brief proposes a **pluggable Universe Layer**: one abstraction behind which different *providers* slot in — **indexes**, **custom lists**, **rules-based criteria** — each yielding **point-in-time (PIT) membership** (who was in the universe, by date) that feeds the existing resolution → ingestion → returns pipeline unchanged. It mirrors sym's source-abstraction philosophy (AR-5). Membership is **maintained daily, not defined once**: a monitor detects joiners/leavers and records them, so the universe stays correct and accumulates history forward. Build sequence: **get index maintenance right first; only then pull prices for the names it tracks.**

The first universe is the **free S&P 1500 family, US**, then **European flagships** — scope is **US + Europe**. S&P 1500 has 20y of free point-in-time history (seed, then maintain forward); European indexes start current and build forward. Paid/global/other-region universes (Russell 3000, MSCI World, Brazil, India) are out of scope now but become drop-in providers later.

## The Problem

- **The universe is hardcoded and tiny.** No way to say "track the S&P 500", "track this list", or "track the top 1,000 by market cap" without editing source files.
- **No membership-over-time = survivorship bias at the universe level.** The returns engine is survivorship-safe *per security* (Story 3.7), but a universe that knows only *today's* members silently excludes the companies that left — reintroducing the exact bias sym exists to kill. Membership must be **point-in-time**.
- **Different research needs different universes** — a broad cap-weighted set, a custom list, a screen. None are expressible today.
- **Sourcing is uneven.** Free point-in-time membership exists only for the S&P/Dow-Jones family; the survivorship-critical *delisted leavers* are exactly where free identity/price resolution breaks (only 2 of sym's 5 seed delistings resolved even by ISIN). A member we can't yet resolve or price must be a **retained, flagged** state — never a silent drop.

## The Solution

A **Universe Layer** with four parts, all sym-idiomatic:

1. **Providers (the plug-in point).** A `UniverseProvider` Protocol + config-keyed registry (the AR-5 source pattern); providers are *event-producing* (index, list) or *function-evaluating* (criteria). Index providers are organized **by source archetype, not one-per-index** — open-finance-API/FMP (preferred US: dated current + historical constituents), ETF-holdings (preferred Europe + big/gated), Wikipedia (fallback/corroboration; the only free 20y S&P 500 PIT). Each index has a **configured source preference with automatic fallback on failure** (e.g. FMP→ETF→Wikipedia), so adding one is *config, not code* *(detail + scoring: addendum §A, ADR-2)*. **Yahoo is prices + corroboration, not a membership source.** A **custom-list** provider generalizes today's seed; a **criteria** provider (rules-based screen) is a fast-follow (needs market-cap data sym lacks).

2. **Membership store — event log as truth, interval table as projection.** Membership changes are discrete dated events, so truth is an **append-only change-event log** (immutable; corrections by appended events — sym's AR-6/AR-10 pattern); each event carries its **effective date + precision/provenance** (exact from a dated API; bounded-by-poll-interval from snapshot diffing — which is why *daily* polling matters: it caps that uncertainty at ≤1 day). The `universe_membership` interval table is its **read-model, projected at the CompositeFIGI level** so a ticker rename can't read as a leave+rejoin. Each universe carries a **`pit_valid_from`** boundary — a membership query before it refuses/flags, never silently back-projects today's members onto the past (the worst survivorship failure). Membership is **consumed via an as-of query API** — `members(universe, date)` joined to `fact_returns`, the research cross-section — across **multiple concurrent universes** (many-to-many; set operations like overlap/difference); a study can pin a **reproducible snapshot** (`universe @ log-version`) so reruns are identical even after later log corrections (sym's determinism ethos, extended to the universe) *(detail: addendum §B)*.

3. **Daily maintenance (event discovery) — the heart of v1.** A scheduled monitor discovers change-events (read from dated APIs, or derived by diffing snapshots) and appends them to the log; "daily" is safe over-sampling of infrequent changes. Hardened per the pre-mortem: a **freshness heartbeat** (empty/failed parse = error, never "no change"), **sanity-gating** (large churn flagged, not auto-applied), and **cross-source corroboration + a reversible audit trail** *(detail: addendum §B2, §H)*.

4. **Bridges to the existing pipeline.** *Resolution:* members resolve via the ISIN-first OpenFIGI resolver, **as-of membership dates, ISIN-preferred, FIGI frozen at first resolution** (recycled tickers can't re-point a historical member); unresolved members are **retained and flagged**, share-class ambiguity → review. *Ingestion:* reads "members active as-of the run" from the maintained membership; a **joiner triggers historical backfill** (forward-only would leave a hole); delisted leavers flow through unchanged (Story 3.7). Runs only after maintenance is trustworthy.

A universe is then a config entry + a command — `universe add sp500`, `universe add my-list --from picks.toml`, `universe refresh`, `universe monitor`, `universe review`.

## What Makes This Different

- **Consistent with sym, not bolted on:** provider abstraction = AR-5; membership = explicit-event log + projection, mirroring sym's corporate-action store (AR-6) and immutable-history-with-correction (AR-10); survivorship retention = Story 3.7. The model *lowers* conceptual surface.
- **Survivorship-safe at the universe level** — point-in-time membership; members never silently dropped for being hard to source; pre-tracking queries refused, not back-projected.
- **Structured-API-first, scrape-as-fallback** — prefers a dated API feed (FMP) where one exists (less brittle, dated events), with ETF-holdings/Wikipedia as fallback + corroboration.
- **Source-honest** — the free/paid boundary is explicit (a member can be "known, unresolved, unpriced"); paid providers (Norgate, EODHD, CRSP) slot in later with zero core change.

## Who This Serves

The only user is **Andre, doing personal quant research** on sym. Success: define a research universe in one command, trust it's survivorship-safe back 20 years, and swap or extend universes without touching warehouse internals.

## Success Criteria

- Reconstruct **S&P 1500 membership as-of any date** over ~20 years, and the active set drives ingestion.
- Define a **custom-list** and a **criteria** universe through the same abstraction; a **new provider adds without changing** the store, resolver, or ingestion (the plug-in test).
- The **survivorship invariant holds at the universe level**: a leaver keeps membership + returns through its exit date; unresolved/unpriced members are retained-and-flagged; pre-`pit_valid_from` queries are refused, never back-projected.
- **Membership is verifiably correct, not just fresh** — a periodic cross-check against an *independent* second source (API/derived vs ETF) alarms on divergence; a stale monitor alarms; each universe exposes **coverage** (% resolved/priced) so partial loads can't look complete.
- **Studies are reproducible** — pinning a `(universe, as-of, log-version)` snapshot yields identical membership on rerun, even after later log corrections; **cross-universe set queries** (overlap/difference) work across concurrently-tracked universes.
- The existing returns/SM-6 machinery runs over the universe-driven set with no regression.

## Scope

**In (US + Europe):**
- The `UniverseProvider` abstraction + registry; **index providers by archetype** (API/FMP for US, ETF-holdings for Europe + big/gated, Wikipedia fallback) + a **custom-list** provider (criteria is a fast-follow).
- The **membership event log + point-in-time projection** + resolution/ingestion bridges + a universe CLI (`add`/`list`/`refresh`/`monitor`); retain-and-flag for unresolved members.
- **Daily index maintenance** (event-discovery, freshness heartbeat, sanity-gating, corroboration).
- Indexes: **S&P 1500 first** (seed 20y PIT, maintain forward), then **European flagships** (DAX, FTSE 100/250, CAC 40, EURO STOXX 50, IBEX 35, FTSE MIB, AEX, SMI; STOXX 600 via ETF) — current now, PIT forward.

**Out (for now):**
- Non-US/non-Europe regions (Brazil/B3, India/NSE, Asia) — same archetypes, later.
- Licensed/paid indexes — Russell 3000 (Norgate), MSCI World/ACWI/EAFE and FTSE All-World (institutional; MSCI World PIT unavailable to individuals). *(The in-scope FTSE 100/250 are different, free indexes.)*
- The licensed **delisted-leaver backfill** (EODHD/Story-2.7) for names that left *before* daily monitoring began.

## Open Questions

- **Criteria provider — fast-follow (decided).** Needs market cap / shares outstanding sym doesn't store; v1 ships index + custom-list. Open: which free fundamentals source (FMP/yfinance, US-only).
- **Seed → custom-list universe.** [ASSUMPTION] the 50-name seed becomes the canonical custom-list example so fixtures/SM-6 keep working.
- **Membership granularity.** Is "best-effort daily-resolution, provenance-tagged" membership acceptable (free index data isn't audit-grade)?
- **Daily-monitor guard threshold** — how much churn auto-applies vs. flags (tunable; empty/failed parse always flags).
- **FMP free-tier dependency (US)** — verify the historical-constituent endpoint is still free; archetype fallback (Wikipedia/`yfiua`) is the mitigation.
- **No free European constituents API (named risk)** — free path is self-archived ETF holdings + Wikipedia; EODHD is the paid lever, out of scope now.

## Proposed Delivery Sequence (epics)

Maintenance-first, ingestion-second — to be formalized by the next workflow.

- **U1 — Universe foundation.** Provider abstraction + registry, membership event-log + projection, the **as-of query API + multi-universe/set-operations + reproducible snapshots**, CLI. The seed becomes the first custom-list universe.
- **U2 — Index providers (US + Europe).** API/FMP + ETF-holdings + Wikipedia archetypes; seed S&P 1500 (20y backfill) and European flagships (current).
- **U3 — Daily index maintenance.** Event-discovery + change log, freshness heartbeat, sanity-gating, corroboration + reversible audit, `pit_valid_from` guardrail, and the **`universe review` operator digest** (pending changes, stale monitors, aging-unresolved, accuracy alarms). *Must be correct before U4.*
- **U3.5 — Membership accuracy gate.** Independent cross-check (e.g. derived vs ETF) that alarms on a *wrong* (not just stale) universe.
- **U4 — Universe-driven ingestion.** Pull prices for all maintained names (joiners backfilled); survivorship-safe; holds at S&P 1500 + Europe scale (~2k × 20y) with **coverage** visibility.
- **U5 — Criteria provider (fast-follow).** Once a minimal fundamentals source lands.

U1–U3.5 are **index maintenance**; U4 is the **pull-prices** step that depends on them.

## Vision

One abstraction, many universes. Start free + US (S&P 1500), then — without re-architecting — add Norgate (Russell 3000), EODHD (global/delisted), or CRSP (if a university affiliation appears), and richer criteria screens once fundamentals land. sym becomes a warehouse you can point at *any* definable universe and trust the returns are survivorship-safe from membership all the way through.
