# sym Cross-Layer Validation & Reconciliation — Epic Breakdown

## Overview

Module 1 (identity, prices, returns) and the Universe Layer (U1–U5) are built and
populated. The layers are joined by **deliberate, FK-less seams** — universe
membership resolves to a `composite_figi` with no FK; the bridge creates
`securities` lazily; prices/returns key on `composite_figi`. These seams are
flexible but **un-guarded**: nothing continuously asserts the layers stay
consistent, so a future ingestion/universe/identity change could silently
reintroduce orphans, ticker collisions, projection drift, or coverage holes.

A read-only diagnostic on the live warehouse (2026-06-07) found it *mostly*
consistent (0 orphans, 0 missing names, 0 true ticker collisions, 0 post-delist
prices) — but also **160 unpriced active securities** (backfill-in-progress +
genuinely-dead leavers, undistinguished) and **1 security whose MIC has no current
calendar** (XNSE). The point of this epic is to turn those one-off checks into a
**standing invariant suite** — a `sym validate` gate that runs across all layers,
itemizes pass/warn/fail (counts + samples, not booleans), and routes actionable
items into `universe review`. It mirrors sym's existing gate philosophy: SM-6
(returns accuracy), AR-9 (two-stage anomaly), U3.3 (membership accuracy).

## Requirements Inventory

### Functional Requirements

- **VR0 (keystone) Universe-member completeness contract.** Every security that is
  a *current member of any universe* must have **complete metadata** (current name,
  current symbology, MIC + currency, GICS classification), **prices**, and
  **fundamentals** (shares outstanding). Any member missing any dimension is
  **flagged and logged** (persisted, not just printed) with *which* dimension is
  missing — surfaced in `universe review` and re-checked each `validate` run. This
  is the contract VR1–VR5 enforce in detail.
- **VR1** Referential-integrity invariants across the FK-less seams (resolutions,
  membership, symbology, names, prices, fundamentals, fact_returns all reference a
  real `securities` row; resolved members are present-or-flagged).
- **VR2** Symbology & name completeness/uniqueness (every active security has a
  current symbology + exactly one current name; no `(ticker, mic)` maps to >1
  current `composite_figi`; no symbology overlap/gap).
- **VR3** Price ↔ calendar ↔ lifecycle consistency (no price on a non-session day;
  no price after `delist_date`; every priced MIC has a current calendar; unpriced
  active securities *classified* into expected vs unexpected).
- **VR4** Membership projection reconciliation (`universe_membership` equals a
  fresh re-projection of the event log; no overlaps; `pit_valid_from` consistent
  with the earliest dated leave).
- **VR5** Universe→returns research-readiness gate (% of a universe's current
  resolved members that join `fact_returns` ≥ threshold, else itemized).
- **VR6** A `sym validate` orchestration + structured report + `universe review`
  integration, with a non-zero exit on hard failures (CI/operator gate).

### Non-Functional

- **VNF1** Each check is a **pure function** over fetched rows (DB-free unit-tested)
  plus a thin live query — same shape as the rest of sym.
- **VNF2** Findings are **itemized and classified** (pass / warn / fail with counts
  + bounded samples), never a silent boolean; expected gaps (dead leavers, XNSE
  no-calendar) are *warnings with a reason*, not failures.
- **VNF3** Read-only and idempotent — `validate` never mutates source data; it may
  write a validation-run log (like `pipeline_run_log`).
- **VNF4** Reuses existing engineering patterns (Sqitch, psycopg3, ruff, the U1.4
  projection property test, coverage, the AR-9/U3.x gate idioms).

## Epic V: Cross-layer validation & reconciliation

A standing suite of integrity invariants spanning identity ↔ symbology ↔ prices ↔
calendar ↔ universe ↔ returns, surfaced via `sym validate` and fed into
`universe review`.

### Story V1: Universe-member completeness contract (keystone)

As Andre,
I want every current universe member proven to have full metadata, prices, and fundamentals,
so that a tracked security is never silently incomplete — and if it is, I see exactly what's missing.

**Acceptance Criteria:**
- For every security that is a **current member of any universe** (resolved,
  interval open as-of today), assert all dimensions present:
  - **metadata** — current name, current ticker symbology, MIC + currency
    (schema-guaranteed), **GICS** classification;
  - **prices** — ≥1 `prices_raw` bar (and, stricter, coverage over its membership
    window);
  - **fundamentals** — ≥1 shares-outstanding observation (market cap derivable).
- Each incomplete member is **persisted** to a `universe_member_completeness`
  log (one row per `(universe_id, composite_figi)`: per-dimension booleans, an
  `is_complete` flag, a `missing[]` list, `checked_at`) — refreshed each run, so
  it's a durable record, not just console output.
- Incomplete members surface in `universe review` (an "incomplete members"
  section, with counts by missing dimension); **expected** gaps (delisted leaver
  with no vendor data, XNSE-type no-calendar) are classified as **warn-with-reason**,
  genuine omissions (e.g. GICS never run, fundamentals never loaded) as **fail**.
- The per-dimension completeness function is pure (over the fetched presence
  flags) and DB-free tested; the live sweep is verified against the populated
  warehouse and the counts reconcile with V2–V5.

### Story V2: Referential-integrity invariants (no orphans)

As the operator,
I want the FK-less seams between layers continuously asserted,
so that an orphaned resolution/membership/price can never accumulate unseen.

**Acceptance Criteria:**
- Checks: every `universe_member_resolution.composite_figi` (status=resolved) and
  `universe_membership.composite_figi` exists in `securities`; every
  `security_symbology` / `security_names` / `prices_raw` / `fundamentals` /
  `fact_returns` `composite_figi` exists in `securities`.
- A *resolved* universe member with no `securities` row is reported as
  **fail** (the bridge should have created it); an *unresolved* member is **info**.
- Pure check functions over `(child_figis, security_figis)` sets are DB-free
  tested; the live sweep is verified against the populated DB.

### Story V3: Symbology & name completeness/uniqueness

As the operator,
I want identity columns proven complete and unambiguous,
so that resolution, naming, and the SM-6 harness can't be silently shadowed.

**Acceptance Criteria:**
- Every `active` security has ≥1 current (`valid_to IS NULL`) symbology row and
  **exactly one** current name (zero or many → fail).
- No `(symbol_type, symbol_value, mic)` maps to **>1** current `composite_figi`
  (a true collision); cross-exchange same-ticker (different MIC) is **not** a
  collision (e.g. LVMH `MC@XPAR` vs Moelis `MC@XNYS`).
- Symbology validity has no overlap or gap per `(composite_figi, symbol_type, mic)`
  beyond the `btree_gist` guarantee (cross-check), and a closed-without-successor
  current-gap is flagged.
- DB-free tests on the pure detectors; live-verified.

### Story V4: Price ↔ calendar ↔ lifecycle consistency

As the operator,
I want prices reconciled against the trading calendar and security lifecycle,
so that off-calendar, post-delisting, or silently-unpriced names are caught.

**Acceptance Criteria:**
- No `prices_raw.session_date` falls on a non-session day for the security's MIC
  (per the current `trading_calendar`); violations itemized.
- No price after `delist_date` (fail); every security holding prices has a current
  calendar for its MIC (XNSE-type absence → warn with reason).
- **Unpriced active securities are classified**: *expected* (delisted leaver with
  no vendor data / no-calendar MIC) → warn; *unexpected* (priceable, in a current
  universe, still zero) → fail. Reconciles against `price_gaps`.
- Pure classifiers DB-free tested; live-verified (the 160 current unpriced are
  triaged).

### Story V5: Membership projection reconciliation

As the operator,
I want `universe_membership` proven to match the event log,
so that a stale or hand-edited projection can never drift from the truth.

**Acceptance Criteria:**
- For each universe, a fresh `project_membership(events)` equals the stored
  `universe_membership` intervals (drift → fail, naming the diverging FIGIs).
- No interval overlap (cross-check the EXCLUDE constraint); `pit_valid_from`
  equals/precedes the earliest dated `leave` (honesty-boundary consistency).
- Reuses the U1.4 projector + property test; DB-free on synthetic logs,
  live-verified on a populated universe.

### Story V6: Universe → returns research-readiness gate

As Andre,
I want a gate that a universe is actually usable for research,
so that a partially-loaded universe can't masquerade as ready.

**Acceptance Criteria:**
- For each universe as-of today, compute the % of current resolved members that
  join `fact_returns`; below a (per-universe configurable) threshold → fail with
  the missing members itemized; the EODHD-reachable gap is named, not hidden.
- Distinguishes "no returns because unpriced" from "no returns because no calendar"
  vs "priced but recompute stale."
- Pure coverage math DB-free tested (extends U4.4 `coverage`); live-verified per
  universe.

### Story V7: `sym validate` orchestration, report & review integration

As the operator,
I want one command that runs every invariant and tells me what's wrong,
so that cross-layer health is a single, CI-able check.

**Acceptance Criteria:**
- `sym validate [--universe <id>]` runs V1–V6, prints a structured report
  (per-check pass/warn/fail + counts + bounded samples), and exits non-zero on any
  **fail** (warnings exit 0) — usable as a pre-ship/CI gate.
- A `validation_run_log` row records each run (akin to `pipeline_run_log`);
  actionable items (unexpected unpriced, orphans, drift) surface in
  `universe review`.
- DB-free tests for the report assembly + exit-code logic; live end-to-end run.

## Notes / sequencing

- V1 is the keystone completeness contract; V2–V6 are the detailed invariant
  modules; V7 wires them together. Natural order: V1 → V2 → V3 → V4 → V5 → V6 → V7.
- Most checks are **read-only**; the only new schema is the optional
  `validation_run_log` (V6). Expected gaps (dead leavers, XNSE) are **warnings**,
  so the gate stays green once the full price backfill completes.
- This epic is the standing version of the ad-hoc 2026-06-07 diagnostic; running
  it after the in-progress backfill should reduce "160 unpriced" to just the
  classified dead-leaver/EODHD set.
