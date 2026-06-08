---
type: sprint-change-proposal
project: QRP (Quant Research Platform)
date: 2026-06-08
author: Andre
trigger: DB-topology brainstorm (2026-06-08) chose Postgres-per-package + DuckDB federation
scope_classification: Moderate
source: _bmad-output/brainstorming/brainstorming-session-2026-06-08-123427.md
---

# Sprint Change Proposal — QRP DB Topology Reconciliation

## 1. Issue Summary

QRP's database layout emerged incrementally: sym existed first, so when QRP was built its six
schemas (`qrp`, `macro`, `signal`, `backtest`, `optimiser`, `altdata`) were created **inside the
`sym` database**. That was chronology, not design. A dedicated DB-topology brainstorm
(`brainstorming-session-2026-06-08-123427.md`, committed `a299fc5`) reconsidered it from first
principles and chose a deliberate topology — **database-per-package + DuckDB federation** — which
**supersedes architectural requirement AR-Q4** ("schema-per-module on shared Postgres").

Discovered during platform-architecture review, after the QRP schemas had been Sqitch-formalized
(commit `38074b0`, project `qrp`). The decision is recorded and committed; this proposal reconciles
the QRP planning artifacts to it.

## 2. Impact Analysis

**Epic impact:** none to epic *scope* — Q1–Q9 deliverables are unchanged. The change is to a
cross-cutting architectural given (AR-Q4), not to any epic's user-facing goal.

**Story impact:** no existing story is invalidated. The built v1 (Q1–Q5 + the 8 module areas)
continues to work as-is — the schemas remain co-resident today. A **new forward workstream** (DB
topology migration) is added to the backlog (post-v1; not blocking current work).

**Artifact conflicts:**
- `epics-qrp.md` — **AR-Q4** statement (the only conflicting requirement).
- `architecture-qrp.md` — Data Architecture ("shared PostgreSQL / QRP-owned `qrp` schema") and
  **ADR-3** (read contract = in-DB views) are reframed by the new topology.

**Unchanged (limits blast radius):** the consumer/actuator boundary (read sym via stable views,
mutate only via sym ops), **AR-Q3** (one FastAPI service, per-module routers), **AR-Q7** (monorepo
fold-in alongside), and the "numbers tie to the warehouse" principle. Reads-are-read-only is
*strengthened* (physical, via DuckDB `READ_ONLY` attach + a read-only role — closes the dual-cred
read-only item).

**Technical impact:** changes *deployment topology* (where schemas live + how cross-package reads
happen), not the application design. No code rollback. New design items introduced: a
**materialization tier** (regenerable Parquet snapshots for heavy analytical paths), a
**live-vs-materialized freshness contract** per read surface, and **meta-orchestration**
(deploy-all migrations / compose-up-all DBs / one DSN registry) as the accepted price of
N-database independence.

## 3. Recommended Approach

**Direct adjustment (no rollback).** Record the supersession in the two planning artifacts and
hand off a forward migration workstream. The existing v1 stands and keeps working while migration
proceeds lazily, package-by-package.

- **Effort:** doc reconciliation is small (this proposal + two edits). The migration workstream is
  moderate and incremental (one package at a time; the Sqitch projects already exist).
- **Risk:** low. Current state is preserved; migration is opt-in per package; the load-bearing
  invariant (no cross-DB FK, value-only `sym_id` keys) is already true in the built schemas, so
  splitting later is cheap.
- **Timeline impact:** none on current work; the migration is post-v1, force-triggered (split a
  package out when size/licence/host/engine actually demands it).

## 4. Detailed Change Proposals

### epics-qrp.md — AR-Q4 (annotate as superseded)
```
OLD:
- **AR-Q4 — Schema-per-module on shared Postgres:** sym keeps its schema; future modules
  get own schemas joined on sym_id; each owns its migrations (Sqitch).

NEW:
- **AR-Q4 — Schema-per-module on shared Postgres:** sym keeps its schema; future modules
  get own schemas joined on sym_id; each owns its migrations (Sqitch).
  **[SUPERSEDED 2026-06-08 → database-per-package + DuckDB federation. Each package (incl.
  sym) its own Postgres DB + Sqitch project; cross-package reads via a read-only DuckDB
  federation layer (ATTACH + Parquet) giving native cross-DB joins; value-only sym_id keys,
  no cross-DB FK. See architecture-qrp.md "Architecture Revision Log" +
  brainstorming-session-2026-06-08-123427.md. Direction, not yet implemented.]**
```

### architecture-qrp.md — new "Architecture Revision Log" section (near top)
Records: the new target topology; what is unchanged; what reframes (Data Architecture + ADR-3);
status = direction-not-yet-implemented (schemas still co-resident but Sqitch-formalized); and the
new design items (materialization tier, freshness contract, meta-orchestration). Full text applied
to the document.

## 5. Implementation Handoff

**Scope: Moderate** → Product Owner / Developer coordination (backlog adds a forward workstream;
no replan of existing work).

**Forward migration workstream (post-v1, incremental, force-triggered):**
1. Adopt the discipline (consumers read sym's stable views + `sym_id`; no cross-DB FK).
2. **First move — DuckDB federation spike:** embed DuckDB, `ATTACH READ_ONLY` to two of today's
   schemas, run the real heat-map cross-DB join, measure live-attach perf.
3. Carve packages into their own Postgres DBs one at a time (reuse the existing Sqitch projects;
   repoint each to its own DB). Start with the most independent (macro/altdata); end with sym
   (→ own DB + read replica, closing the read-only-role item).
4. Stand up the materialization tier (regenerable Parquet snapshots for heavy paths).
5. Build meta-orchestration (deploy-all migrations / compose-up-all DBs / one DSN registry).
6. Invariant guard (CI): no cross-DB FK; consumers read only stable views; cache regenerable.

**Success criteria:** AR-Q4 superseded in both artifacts; the migration workstream is on the
backlog with the DuckDB spike as its first, lowest-risk step; existing v1 remains green throughout.
