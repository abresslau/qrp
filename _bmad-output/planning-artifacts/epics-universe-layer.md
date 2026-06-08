---
stepsCompleted: ["step-01", "step-02", "step-03", "step-04"]
inputDocuments:
  - "_bmad-output/planning-artifacts/briefs/brief-sym-2026-06-06/brief.md"
  - "_bmad-output/planning-artifacts/briefs/brief-sym-2026-06-06/addendum.md"
  - "_bmad-output/planning-artifacts/architecture.md"
  - "_bmad-output/planning-artifacts/epics.md"
---

# sym Universe Layer - Epic Breakdown

## Overview

This document decomposes the **sym Universe Layer** (a new, additive capability on the existing sym warehouse — Module 1 / Epics 1–3 complete) into implementable epics and stories. Requirements are synthesized from the finalized product brief (`brief-sym-2026-06-06/brief.md`) and its addendum (ADR-1…8, FMEA §H, source matrices), with `architecture.md` and the existing `epics.md` as cross-reference context so the new work reuses established patterns (AR-5 source abstraction, AR-6 explicit events, AR-9 two-stage anomaly, AR-10 immutability, Story-3.7 survivorship, SCD + btree_gist, Sqitch migrations, OpenFIGI ISIN-first resolver) rather than duplicating them.

## Requirements Inventory

### Functional Requirements

FR1: A `UniverseProvider` abstraction (Protocol + config-keyed registry, mirroring the AR-5 OHLCV-source pattern) — universes are defined by config, and a new provider registers without changing the membership store, resolver, or ingestion.
FR2: Three provider types — **index**, **custom list**, **criteria** — modelled as two kinds: *event-producing* (index, list → emit dated membership-change events) and *function-evaluating* (criteria → compute `members(date)`, optionally snapshot).
FR3: Index providers organized **by source archetype, not one-per-index** — open-finance-API (FMP/OpenBB), ETF-holdings, Wikipedia (+ revision-diff) — with a **configured per-index source preference and automatic fallback on failure** (e.g. FMP→ETF→Wikipedia).
FR4: Membership stored as an **append-only change-event log** — `(universe, raw_identifier, change: join|leave|correct, effective_date, effective_date_precision, source, provenance, recorded_at)`; immutable, corrections by appended events.
FR5: A **point-in-time `universe_membership` interval read-model projected from the log at the CompositeFIGI level**, so a mid-membership ticker rename cannot read as a leave+rejoin.
FR6: Each universe carries a **`pit_valid_from`** boundary; a membership query for a date before it **refuses or flags**, never silently back-projects today's members onto the past.
FR7: Members **resolve to CompositeFIGI via the ISIN-first OpenFIGI resolver**, as-of their membership dates, ISIN-preferred, with the FIGI **frozen at first resolution**; unresolved members are **retained and flagged** (never dropped); share-class ambiguity routes to review.
FR8: A **daily maintenance monitor** that discovers membership-change events (read from dated APIs, or derived by diffing consecutive snapshots) and appends them to the log; idempotent and per-index.
FR9: A **`universe review` operator digest** surfacing pending sanity-gated changes, stale monitors, aging-unresolved members, and accuracy-gate alarms in one place.
FR10: **Universe-driven ingestion** — `run_load` reads members active as-of the run from the maintained membership; a **joiner triggers historical backfill** over its membership window; leavers stop forward fetches; delisted members flow through survivorship-safe (Story 3.7).
FR11: An **as-of membership query API** — `members(universe, date)` joinable to `fact_returns` (the research cross-section).
FR12: **Multiple concurrent universes + set operations** (overlap/difference); membership is many-to-many across universes.
FR13: **Reproducible study snapshots** — pinning `(universe, as-of, log-version)` yields identical membership on rerun, even after later log corrections.
FR14: A **membership accuracy gate** — periodic cross-check of the maintained list against an *independent* second source, alarming on divergence beyond a threshold (SM-6-style, for membership).
FR15: A **universe CLI** — `add` / `list` / `refresh` / `monitor` / `review`.
FR16: The existing 50-name adversarial seed becomes the **first custom-list universe** (fixtures/SM-6 keep working).
FR17: Seed **S&P 1500 with ~20y point-in-time backfill** (Wikipedia archetype / community repos); **European flagships** seeded current, building PIT forward.
FR18: A **criteria provider** (rules-based screen, e.g. top-N by month-end market cap) — fast-follow, computed against a fundamentals source.

### NonFunctional Requirements

NFR1: **Survivorship-safe at the universe level** — leavers keep membership + returns through their exit date; unresolved/unpriced members are retained-and-flagged, never dropped; pre-`pit_valid_from` queries are refused, never back-projected.
NFR2: **Liveness/freshness** — per-index `last_successful_monitor`; a stale monitor alarms; an empty or failed parse is an **error, never "no change."**
NFR3: **Sanity-gating + corroboration** — churn beyond a (tunable) guard threshold is flagged for review, not auto-applied; a change must persist N days or be confirmed by a second source before recording; the change log is an appended, **reversible** audit trail (AR-9 two-stage philosophy).
NFR4: **Structured-API-first** — prefer a dated API feed (FMP) where one exists to reduce brittleness; scraping (Wikipedia) and ETF-holdings are fallback/corroboration.
NFR5: **Scale + coverage visibility** — ingestion holds at S&P 1500 + Europe (~2,000 names × 20y); each universe exposes **coverage** (% members resolved/priced) so partial loads can't masquerade as complete.
NFR6: **Consistency with sym engineering patterns** — effective-dated SCD with btree_gist EXCLUDE; Sqitch plain-SQL migrations (deploy/revert/verify) via Docker; psycopg3; DB-free unit tests + live verification; ruff (line-length 100); one durable transaction per unit of work.
NFR7: **Source honesty** — explicit free/paid boundary; events carry provenance + `effective_date_precision` (exact vs poll-bounded); index-name trademarks/ToS respected (sourced from public web/Wikipedia/ETF filings, personal research; not marketed as official feeds).
NFR8: **Reproducibility/determinism** — event-log-as-truth enables deterministic projection, extending sym's existing determinism ethos (input_hash, calendar_version).
NFR9: **No regression** — the existing returns + SM-6 machinery runs over the universe-driven security set unchanged.

### Additional Requirements

- **Architecture decisions (addendum §G, ADR-1…8)** govern the design: provider abstraction (ADR-1); archetype priority API-US/ETF-Europe/Wikipedia-fallback (ADR-2, scored); PIT SCD + `pit_valid_from` (ADR-3); daily-poll CDC corroborated+gated (ADR-4); frozen as-of ISIN-preferred resolution (ADR-5); retain-and-flag (ADR-6); maintenance-first delivery (ADR-7); **event-log-as-truth, interval table = projection (ADR-8)**.
- **Component robustness (FMEA §H)** — dedupe key `(universe,id,change,effective_date)`; source-precedence for conflicting effective dates; project from the **full ordered log** (handles late/out-of-order corrections); ETF: drop non-equity rows + diff the identifier **set** not weights + proxy provenance; Wikipedia: normalize tickers before diffing + N-day persistence; per-index freshness; aging-unresolved metric; accuracy gate must use genuinely independent sources.
- **New schema (Sqitch migrations):** `membership_event` log, `universe_membership` interval projection (btree_gist no-overlap per (universe, member)), a `universe` registry/config table, and a monitor run-log (akin to `pipeline_run_log`).
- **Scope boundary:** **free sources + US + Europe only.** OUT for now — paid indexes (Russell 3000/Norgate, MSCI World/ACWI/EAFE/FTSE All-World), the licensed delisted-leaver backfill (EODHD/Story-2.7), and non-US/non-Europe regions (Brazil/B3, India/NSE, Asia) — all supported later by the same archetypes.
- **Named dependencies/risks:** FMP free-tier is US-only and may paywall its historical-constituent endpoint (mitigated by the archetype fallback); the **criteria provider needs a fundamentals source** (market cap / shares outstanding) sym does not yet store; Europe has **no free structured constituents API** (self-archived ETF holdings + Wikipedia only).

### UX Design Requirements

N/A — the Universe Layer is a backend + CLI capability with no UI. Operator-facing surfaces (the `universe review` digest, coverage reporting) are specified as functional requirements (FR9, FR15, NFR5), not UX-design work.

### FR Coverage Map

FR1: Epic U1 — `UniverseProvider` Protocol + config-keyed registry (AR-5 pattern)
FR2: Epic U1 — three provider types; event-producing vs function-evaluating kinds
FR3: Epic U2 — index source archetypes + per-index preference & automatic fallback
FR4: Epic U1 — append-only membership change-event log (immutable, corrections-by-append)
FR5: Epic U1 — point-in-time `universe_membership` projection at CompositeFIGI level
FR6: Epic U1 — `pit_valid_from` honesty boundary on membership queries
FR7: Epic U1 — ISIN-first as-of frozen resolution; retain-and-flag unresolved
FR8: Epic U3 — daily maintenance monitor (event discovery → append to log)
FR9: Epic U3 — `universe review` operator digest
FR10: Epic U4 — universe-driven ingestion; joiner historical backfill; survivorship-safe
FR11: Epic U1 — as-of membership query API (`members(universe,date)` ⋈ fact_returns)
FR12: Epic U1 — multiple concurrent universes + set operations
FR13: Epic U1 — reproducible study snapshots (`universe @ log-version`)
FR14: Epic U3 — membership accuracy gate (independent cross-check)
FR15: Epic U1 — universe CLI (`add`/`list`/`refresh`/`monitor`/`review`)
FR16: Epic U1 — existing 50-name seed becomes the first custom-list universe
FR17: Epic U2 — seed S&P 1500 (20y PIT) + European flagships (current)
FR18: Epic U5 — criteria provider (rules-based screen; fast-follow)

NFRs (cross-cutting, realized per epic): NFR1 survivorship → U1/U4; NFR2 liveness, NFR3 sanity/corroboration → U3; NFR4 structured-API-first, NFR7 source-honesty → U2/U3; NFR5 scale/coverage → U4; NFR6 engineering patterns → all; NFR8 determinism → U1; NFR9 no-regression → U4.

## Epic List

### Epic U1: Universe foundation & membership model
Define a universe (starting with the existing 50-name seed as the first custom-list universe), backed by an append-only event log projected to point-in-time membership at the CompositeFIGI level, and query who was a member as-of any date — across multiple concurrent universes, with reproducible snapshots — all from a CLI. Standalone: a custom-list universe works end-to-end and is queryable.
**FRs covered:** FR1, FR2, FR4, FR5, FR6, FR7, FR11, FR12, FR13, FR15, FR16 (NFR1, NFR6, NFR8)

### Epic U2: Index providers (US + Europe)
Track real indexes as universes — S&P 1500 with ~20y point-in-time history, European flagships current — via archetype providers (open-finance-API/FMP, ETF-holdings, Wikipedia) with a configured per-index source preference and automatic fallback. Builds on U1.
**FRs covered:** FR3, FR17 (NFR4, NFR7)

### Epic U3: Daily maintenance & membership quality
Index universes stay correct automatically — a daily monitor discovers joiners/leavers safely (freshness heartbeat, sanity-gating, cross-source corroboration + reversible audit), an operator `universe review` digest surfaces pending changes/alarms, and an accuracy gate alarms when a universe is wrong, not just stale. Builds on U1/U2.
**FRs covered:** FR8, FR9, FR14 (NFR2, NFR3, NFR7)

### Epic U4: Universe-driven ingestion
Maintained universes drive price ingestion — every tracked name is priced, joiners backfilled over their membership window, delisted leavers survivorship-safe (Story 3.7), with coverage visibility, at S&P 1500 + Europe scale (~2,000 names × 20y). Builds on U1–U3.
**FRs covered:** FR10 (NFR1, NFR5, NFR9)

### Epic U5: Criteria universes (fast-follow)
Define a rules-based universe (e.g. top-N by month-end market cap), once a minimal fundamentals source (market cap / shares outstanding) lands. Builds on U1.
**FRs covered:** FR18

## Epic U1: Universe foundation & membership model

Define a universe (starting with the existing 50-name seed as the first custom-list universe), backed by an append-only event log projected to point-in-time membership at the CompositeFIGI level, queryable as-of any date across multiple universes, with reproducible snapshots — all from a CLI. Mirrors sym's AR-5 source abstraction, AR-6 explicit events, and AR-10 immutability.

### Story U1.1: Universe registry & UniverseProvider abstraction

As the pipeline,
I want a universe registry and a config-keyed `UniverseProvider` abstraction (mirroring AR-5),
So that universes are declared by config and new sources plug in without changing downstream code.

**Acceptance Criteria:**

**Given** a Sqitch migration, **When** deployed, **Then** a `universe` table exists (`universe_id`, `name`, `kind` ∈ {custom_list, index, criteria}, `config` jsonb, `pit_valid_from` date NULL, `source_pref` jsonb NULL, `created_at`, `updated_at`) wired to the shared `set_updated_at()` trigger (NFR6).
**Given** a `UniverseProvider` Protocol + `register_provider` registry (parallel to `src/sym/sources/registry.py`), **When** a provider registers under a kind/key, **Then** it is resolvable by config; **And** an unknown kind raises rather than silently passing.
**Given** the CLI, **When** I run `universe add <name> --kind custom_list` then `universe list`, **Then** the universe is persisted and listed.
**And** DB-free unit tests cover the registry; the migration + CLI are verified live.

### Story U1.2: Append-only membership event log

As the pipeline,
I want membership changes recorded in an append-only event log,
So that history is immutable and corrections never mutate the past (AR-6/AR-10).

**Acceptance Criteria:**

**Given** a migration, **Then** `membership_event` exists (`event_id`, `universe_id` FK, `raw_identifier`, `change` ∈ {join, leave, correct}, `effective_date`, `effective_date_precision` ∈ {exact, poll_bounded}, `source`, `provenance` jsonb, `recorded_at`).
**Given** an append API, **When** the same `(universe_id, raw_identifier, change, effective_date)` is appended twice, **Then** it is idempotent (dedupe key); **And** the table is insert-only (no update/delete path).
**Given** two sources reporting the same change with conflicting effective dates, **Then** both are recorded with provenance, and a documented source-precedence rule selects the authoritative date at projection time.
**And** DB-free unit tests cover append + dedupe.

### Story U1.3: Membership resolution bridge (ISIN-first, as-of, frozen)

As the pipeline,
I want each member resolved to a CompositeFIGI via the ISIN-first OpenFIGI resolver, as-of its membership date and frozen at first resolution,
So that identity is stable, recycled tickers can't corrupt history, and unresolved members are retained, not dropped.

**Acceptance Criteria:**

**Given** a migration, **Then** `universe_member_resolution` exists (`universe_id`, `raw_identifier`, `composite_figi` NULL, `resolution_status` ∈ {resolved, unresolved, unpriced}, `resolved_at`, `detail`).
**Given** a resolvable member, **When** resolved, **Then** it gets a `composite_figi` + status `resolved`, frozen — re-resolution is a no-op unless an explicit correction.
**Given** an unresolvable member, **Then** it is retained with status `unresolved` (never dropped); **And** share-class ambiguity routes to review (reuse Story 1.6 `share_class_conflict`).
**Given** a recycled ticker, **Then** an already-frozen member keeps its original FIGI (NFR1).
**And** the existing `src/sym/identity/figi.py` ISIN-first/fallback resolver is reused; DB-free tests use a fake resolver.

### Story U1.4: Point-in-time membership projection

As a researcher,
I want the event log projected to a point-in-time `universe_membership` interval table at the CompositeFIGI level,
So that I can ask who was a member on any date, survivorship-safe.

**Acceptance Criteria:**

**Given** a migration, **Then** `universe_membership` exists (`universe_id`, `composite_figi`, `raw_identifier`, `valid_from`, `valid_to` NULL, `source`) with a btree_gist EXCLUDE no-overlap constraint per `(universe_id, composite_figi)` and a `valid_to > valid_from` CHECK.
**Given** a log of join/leave/correct events + resolutions, **When** projected, **Then** intervals are correct at the FIGI level; **And** a mid-membership ticker rename stays ONE continuous interval (not leave+rejoin).
**Given** a late/out-of-order corrective event, **Then** projection rebuilds deterministically from the full ordered log.
**And** a property test asserts `invert(project(log)) == log`; overlapping intervals are rejected by the EXCLUDE constraint; live-verified on a small universe (NFR8).

### Story U1.5: As-of query API, multi-universe set ops, and pit_valid_from guardrail

As a researcher,
I want to query members as-of any date and across universes, with a `pit_valid_from` honesty boundary,
So that I get a correct cross-section and never a silently back-projected one.

**Acceptance Criteria:**

**Given** `members(universe, as_of)`, **Then** it returns the CompositeFIGI set valid on that date, joinable to `fact_returns`.
**Given** `as_of < universe.pit_valid_from`, **When** queried, **Then** it refuses or loudly flags — never back-projects today's members onto the past (FR6).
**Given** two universes, **Then** set operations (overlap, difference, "in A not B") work; **And** a security may be a member of multiple universes simultaneously (FR12).
**And** DB-free tests cover the date logic + guardrail; the `fact_returns` join is verified live.

### Story U1.6: Reproducible universe snapshots

As a researcher,
I want to pin a study to a `(universe, as_of, log-version)` snapshot,
So that reruns give identical membership even after later log corrections.

**Acceptance Criteria:**

**Given** a snapshot pin `(universe, as_of, log-version)` (e.g. a max `event_id`/`recorded_at` watermark), **When** membership is queried via the pin, **Then** it reflects the log state at that version, ignoring later-appended events.
**Given** later corrective events, **When** the same pin is re-queried, **Then** it returns identical membership; **And** an unpinned query reflects the latest log.
**And** the log-version mechanism is documented; DB-free tests cover pinned vs latest.

### Story U1.7: Seed the existing 50-name universe as the first custom-list universe

As Andre,
I want the existing 50-name seed loaded as a custom-list universe end-to-end,
So that I have a real universe and fixtures/SM-6 keep working.

**Acceptance Criteria:**

**Given** a custom-list provider (the first concrete `UniverseProvider`, emitting join events from a list of tickers+MIC and/or ISINs), **When** I run `universe add seed --kind custom_list --from benchmark/seed_universe.toml` then `universe refresh seed`, **Then** join events are appended, members resolved (reusing existing `securities`), and `universe_membership` projects the 44 resolved names plus the retained-flagged unresolved delistings.
**Given** `members('seed', today)`, **Then** it returns the seed's current members joinable to `fact_returns`; **And** the existing returns/SM-6 machinery runs unchanged over the universe-driven set (NFR9).
**And** `pit_valid_from('seed')` is set appropriately; verified live against the populated DB.

## Epic U2: Index providers (US + Europe)

Track real indexes as universes — S&P 1500 with ~20y point-in-time history, European flagships current — via archetype providers (open-finance-API/FMP, ETF-holdings, Wikipedia) with a configured per-index source preference and automatic fallback. Builds on U1; structured-API-first (NFR4), provenance-tagged (NFR7).

### Story U2.1: Open-finance-API index provider (FMP)

As the universe layer,
I want an open-finance-API index provider that reads FMP's current and historical constituents,
So that US flagship indexes are sourced from a dated, structured feed rather than scraping (the preferred US archetype).

**Acceptance Criteria:**

**Given** the provider, **When** it fetches S&P 500 / Nasdaq-100 / Dow Jones, **Then** it emits current-membership join events **and** historical add/remove events from the historical endpoint, each with `effective_date_precision = exact`.
**Given** FMP's bare US tickers, **Then** they are normalized to ticker+MIC = US for resolution.
**Given** an orphan leave event (a removal with no prior add in-window), **Then** it is tolerated/flagged, never crashing projection.
**Given** the free-tier rate limit, **Then** the provider budgets calls and verifies expected-vs-returned counts (no silent partial fetch).
**And** DB-free tests use a fake FMP client; the FMP free-tier historical endpoint availability is verified live before relying on it.

### Story U2.2: ETF-holdings index provider

As the universe layer,
I want an ETF-holdings index provider that derives membership from issuer daily-holdings files,
So that European flagships and big/gated US indexes have a least-brittle, self-archivable source (the preferred Europe archetype).

**Acceptance Criteria:**

**Given** an issuer daily-holdings CSV (iShares/Amundi/Xtrackers), **When** parsed, **Then** non-equity rows (cash, futures, FX hedges) are dropped and only equity constituents become members.
**Given** two consecutive holdings files, **When** diffed, **Then** the diff is on the **identifier set only, not weights** (a weight change is not a membership change).
**Given** membership derived from an ETF, **Then** events are tagged `proxy` provenance with `effective_date_precision = poll_bounded`.
**And** a parse returning empty/garbled output is flagged (sanity-gate hook), never applied as "all members left"; DB-free tests cover row-filtering + set-diff.

### Story U2.3: Wikipedia index provider + revision-diff engine

As the universe layer,
I want a Wikipedia index provider with a reusable revision-diff engine,
So that I have a fallback/corroboration source and the only free ~20-year point-in-time history for the S&P 500.

**Acceptance Criteria:**

**Given** an index's Wikipedia component table, **When** parsed, **Then** current members are emitted.
**Given** the page's revision history, **When** the revision-diff engine runs, **Then** it derives dated change-events (S&P 500 back to ~2006) with `effective_date_precision = poll_bounded`.
**Given** ticker-format drift (BRK.B vs BRK-B), **Then** identifiers are normalized before diffing so the same name cannot fake a leave+rejoin.
**And** an empty/garbled parse triggers the sanity-gate (never wipes a universe); DB-free tests cover table parse + revision-diff on fixtures.

### Story U2.4: Per-index source preference and automatic fallback

As the universe layer,
I want each index to declare an ordered source preference with automatic fallback,
So that the layer always uses the best available source and degrades rather than breaks.

**Acceptance Criteria:**

**Given** an index config naming an ordered preference (e.g. FMP→ETF→Wikipedia), **When** the orchestrator fetches, **Then** it tries the preferred archetype and **falls back to the next on failure**.
**Given** a successful fetch, **Then** the event provenance records which source produced it.
**Given** all configured sources fail, **Then** the orchestrator raises loudly (per-index), never silently records "no members."
**And** DB-free tests cover preference ordering + fallback-on-failure with fake providers.

### Story U2.5: Seed S&P 1500 with ~20-year point-in-time backfill

As Andre,
I want S&P 500/400/600 registered and backfilled with ~20 years of point-in-time membership,
So that I have a survivorship-correct US large/mid/small-cap universe to research over.

**Acceptance Criteria:**

**Given** the FMP-historical + Wikipedia-repo sources, **When** I seed `sp500`/`sp400`/`sp600`, **Then** ~20y of join/leave events are backfilled into the log and projected, with `pit_valid_from` set to the backfill floor.
**Given** the backfilled members, **Then** each is resolved (retain-and-flag for the unresolvable), and `members('sp500', <a past date>)` returns a survivorship-correct set (leavers present through their exit dates).
**And** verified live: a spot-check date's membership matches the source; the projection has no overlap violations.

### Story U2.6: Seed European flagship index universes (current)

As Andre,
I want the European flagship indexes registered and seeded current,
So that I can track them now and build their point-in-time history forward honestly.

**Acceptance Criteria:**

**Given** the per-index preferred archetype (ETF-holdings + Wikipedia fallback), **When** I seed DAX, FTSE 100/250, CAC 40, EURO STOXX 50, IBEX 35, FTSE MIB, AEX, SMI (+ STOXX Europe 600 via ETF), **Then** current membership is captured with `pit_valid_from = today` (build-forward boundary).
**Given** the non-US listings, **Then** members resolve against the existing exchanges/calendars (reusing the ISIN-first resolver and MIC mappings).
**And** a pre-`pit_valid_from` query on a European universe is refused/flagged (no false history); verified live for at least DAX + CAC 40.

## Epic U3: Daily maintenance & membership quality

Index universes stay correct automatically — a daily monitor discovers joiners/leavers safely (freshness heartbeat, sanity-gating, cross-source corroboration + reversible audit), an operator `universe review` digest surfaces pending changes/alarms, and an accuracy gate alarms when a universe is wrong, not just stale. Builds on U1/U2; AR-9 two-stage (NFR2, NFR3).

### Story U3.1: Daily maintenance monitor (event discovery + liveness)

As the pipeline,
I want a scheduled per-index monitor that discovers membership-change events and appends them to the log,
So that universes stay current automatically and a frozen universe is never mistaken for a stable one.

**Acceptance Criteria:**

**Given** a scheduled, idempotent, per-index monitor, **When** it runs, **Then** it re-runs each index's preferred provider, discovers change-events (dated from APIs, or derived by diffing snapshots), and appends them to the log; re-running the same day is a no-op.
**Given** each run, **Then** it records `last_successful_monitor` **per index** and writes a monitor run-log row (akin to `pipeline_run_log`) of {index, date, joiners, leavers, action}.
**Given** an empty or failed parse, **Then** it is recorded as an **error, never "no change."**
**Given** a change effective on a non-trading day or with TZ skew, **Then** the effective date is aligned to the exchange calendar.
**And** DB-free tests cover discovery + idempotency with fake providers; live-verified on at least one index.

### Story U3.2: Sanity-gating, corroboration, and reversible audit

As the pipeline,
I want surprising membership changes gated and corroborated before they are recorded,
So that a bad parse or vandalized source can't silently corrupt a universe (AR-9 two-stage).

**Acceptance Criteria:**

**Given** a monitor diff that churns more than a tunable guard threshold, **Then** it is flagged for review, **not** auto-applied.
**Given** a detected change, **Then** it must **persist N days or be confirmed by a second source** before it is recorded as a membership event.
**Given** a recorded change later found wrong, **Then** it is reversed by an appended corrective event — the change log is an appended, reversible audit trail, never a destructive edit.
**And** DB-free tests cover threshold gating + corroboration + reversal.

### Story U3.3: Membership accuracy gate

As Andre,
I want a periodic cross-check of each universe against an independent second source,
So that I am alarmed when membership is wrong, not merely stale.

**Acceptance Criteria:**

**Given** a universe's maintained membership and an **independent** second source (e.g. FMP/derived vs ETF holdings — not two derivatives of the same upstream), **When** the gate runs, **Then** it alarms on divergence beyond a threshold.
**Given** an ETF proxy that legitimately differs from the index, **Then** a proxy-aware tolerance avoids alert fatigue.
**And** the gate catches a *wrong* universe (not just a stale one); DB-free tests cover the divergence comparison.

### Story U3.4: `universe review` operator digest

As Andre,
I want a single `universe review` surface for everything needing my attention,
So that gated changes, stale monitors, and quality alarms never pile up unseen.

**Acceptance Criteria:**

**Given** `universe review`, **Then** it lists in one place: pending sanity-gated changes (with confirm/reject actions), stale monitors, aging-unresolved members, and accuracy-gate alarms.
**Given** I confirm a gated change, **Then** it is appended to the log (un-gating it); **Given** I reject it, **Then** a rejection is recorded — both as appended events, never a mutation.
**And** DB-free tests cover the digest assembly + confirm/reject actions; live-verified end-to-end with a synthetic gated change.

## Epic U4: Universe-driven ingestion

Maintained universes drive price ingestion — every tracked name is priced, joiners backfilled over their membership window, delisted leavers survivorship-safe (Story 3.7), with coverage visibility, at S&P 1500 + Europe scale. Builds on U1–U3 (NFR1, NFR5, NFR9).

### Story U4.1: Drive ingestion from maintained membership

As the pipeline,
I want `run_load` to read its security set from the maintained universe membership,
So that ingestion tracks whatever universes are defined, not a hardcoded seed.

**Acceptance Criteria:**

**Given** `run_load`, **When** invoked with a `--universe` selector, **Then** it reads "members active as-of the run" (resolution_status = resolved) from `universe_membership` instead of the static seed.
**Given** a universe-driven run, **Then** the existing returns + SM-6 machinery runs unchanged over the resulting security set (NFR9 — no regression).
**And** DB-free tests cover the member-selection query; live-verified by running against the `seed` universe and matching prior behavior.

### Story U4.2: Historical backfill on join

As the pipeline,
I want a new joiner's prior price history backfilled over its membership window,
So that a name added today does not leave a hole for the dates it was already a member.

**Acceptance Criteria:**

**Given** a member that joins a universe with a `valid_from` in the past, **When** ingestion runs, **Then** it backfills that member's price history over its membership window (not just go-forward).
**Given** a re-run, **Then** backfill is idempotent and respects the existing per-figi cursor + immutability (AR-10).
**And** DB-free tests cover the backfill-window computation; live-verified for a member with prior history (NFR1).

### Story U4.3: Leaver handling (survivorship-safe)

As the pipeline,
I want members that leave a universe to stop forward fetches while retaining their history,
So that delisted/removed names remain survivorship-safe and don't waste daily retries.

**Acceptance Criteria:**

**Given** a member that left a universe (delisted/removed), **When** ingestion runs, **Then** it stops forward fetches for that member without daily re-try.
**Given** that member's history, **Then** it is retained and flows through returns through its exit date (Story 3.7); the member is never dropped from ingestion outputs.
**And** DB-free tests cover the stop-fetch / retain logic; live-verified with a simulated leaver.

### Story U4.4: Coverage visibility and scale validation

As Andre,
I want per-universe coverage and validated scale,
So that a partial load can't masquerade as complete and the engine holds at the real universe size.

**Acceptance Criteria:**

**Given** a universe, **Then** it exposes **coverage** (% of members resolved / priced) so an incomplete ingestion is visible, not hidden.
**Given** the S&P 1500 + Europe scale (~2,000 names × 20y), **When** ingestion runs, **Then** it completes within the free-source ceiling (rate-limit aware) and reports coverage; the EODHD lever is named for what free sources can't reach (NFR5).
**And** coverage reporting has DB-free tests; scale is validated live (or on a representative subset with documented extrapolation).

## Epic U5: Criteria universes (fast-follow)

Define a rules-based universe (e.g. top-N by month-end market cap), once a minimal fundamentals source lands. Builds on U1; explicitly the fast-follow because U5.2 is only buildable once U5.1's fundamentals input exists.

### Story U5.1: Minimal fundamentals input (market cap / shares outstanding)

As the universe layer,
I want a minimal fundamentals input populating market cap and shares outstanding,
So that rules-based screens have the reference data sym does not yet store.

**Acceptance Criteria:**

**Given** a small fundamentals source (FMP / yfinance, US-first, throttled), **When** it runs for the securities a screen needs, **Then** it populates a fundamentals table with market cap + shares outstanding (ADV computed from stored EOD volume×price), provenance-tagged.
**Given** a name with missing fundamentals, **Then** the gap is flagged, never faked.
**And** DB-free tests cover parsing/normalization with a fake client; the free-tier coverage limits (US-first) are documented.

### Story U5.2: Criteria provider (rules-based screen)

As Andre,
I want a function-evaluating criteria provider that computes membership from a rule,
So that I can define a universe like "top-N US common stocks by month-end market cap" and query it like any other.

**Acceptance Criteria:**

**Given** a criteria provider registered with a rule, **When** evaluated for a date, **Then** it computes `members(date) = {s : rule(s, date)}` against the fundamentals input.
**Given** a computed membership, **Then** it is **snapshotted into the event log**, so the criteria universe is point-in-time queryable and reproducible like any other universe (FR11/FR13 apply).
**Given** the universe CLI, **When** I `universe add us-top1000 --kind criteria --rule "mktcap top 1000"` then `refresh`, **Then** the universe materializes and `members('us-top1000', date)` returns the screened set.
**And** DB-free tests cover the rule evaluation + snapshotting; live-verified for a small top-N screen.
