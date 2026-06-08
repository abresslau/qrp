---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'EOD price-retrieval orchestration for sym (scheduler-agnostic: Airflow or Prefect, TBD) + the multi-module architecture where sym is Module 1 and future modules (live pricing, paper portfolios + backtests, portfolio analytics) leverage sym''s shared symbology/identity (sym_id)'
session_goals: 'Design sym''s EOD process as a schedulable idempotent pipeline exposed to an external orchestrator; and the cross-module architecture (identity/data sharing, repo strategy, contract). Then apply the buildable part.'
selected_approach: 'user-selected -> run-all + apply'
techniques_used: ['mind-mapping', 'morphological-analysis', 'reversal-inversion', 'what-if-scenarios', 'five-whys', 'analogical-thinking', 'resource-constraints', 'provocation']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Andre
**Date:** 2026-06-07

## Session Overview

**Topic:** (1) an **EOD process** to retrieve prices + refresh everything, run by an external scheduler (Airflow **or** Prefect, TBD); (2) the **multi-module architecture** — `sym` is Module 1; future modules: **live pricing**, **paper portfolios + backtests**, **portfolio analytics** — all reusing sym's identity (`sym_id`).

## Technique Sweep (divergent)

### Mind Mapping — territory
EOD: which steps · order · cadence (daily vs weekly) · idempotency · failure isolation · observability · alerting · scheduler boundary. Modules: identity sharing (`sym_id`) · data sharing (lib vs service vs shared DB) · repo strategy · contract/versioning · who-writes-what (sym = system of record).

### Morphological Analysis — dimensions × options
- **Scheduler coupling:** sym imports Airflow/Prefect · **sym is scheduler-agnostic (idempotent CLI steps + a `sym eod` runner); orchestrator is a thin wrapper that shells out** · embed a scheduler in sym. → **agnostic** (don't marry Airflow/Prefect; you haven't chosen).
- **EOD granularity:** one monolith command · **discrete idempotent steps the orchestrator composes (+ a coarse `sym eod` for cron/manual)** · per-figi tasks. → discrete steps + coarse runner (best of both: fine-grained retries in Airflow/Prefect; one-liner for cron).
- **EOD cadence:** all daily · **daily core (delta→recompute→monitor→benchmarks→validate) + periodic (fundamentals weekly, calendar snapshot occasional)**. → tiered cadence.
- **Module data sharing:** copy data · **shared Postgres, sym = system-of-record schema, modules read via the published contract** · sym as a service/API · sym as a pip library. → **shared DB + sym as an installable library** (read the contract; heavy compute as a lib import).
- **Repo strategy:** one giant repo · **monorepo of packages (sym, live, backtest, analytics) sharing the identity/contract package** · polyrepo with sym published + pinned. → monorepo-of-packages now (simplest sharing), polyrepo later if teams diverge.
- **Identity across modules:** each module re-resolves · **`sym_id` is THE shared key; instrument_xref the vendor bridge; modules never re-mint identity**. → `sym_id` spine (already built in B1).

### Reversal/Inversion — guarantee failure
Couple sym to Airflow → can't switch to Prefect; one monolith EOD → a vendor hiccup fails the whole night with no partial progress; modules each re-resolve tickers → identity drift across the stack; copy sym's data into each module → reconciliation hell. ⇒ agnostic + discrete idempotent steps + one shared `sym_id` + one system-of-record DB.

### What-If
- *Airflow vs Prefect undecided?* → both become ~20-line wrappers calling `sym <step>`; sym carries zero orchestration deps. Switching is a wrapper swap.
- *A step fails at 2am?* → each step idempotent + error-isolated + run-logged; the orchestrator retries just that task; `sym validate` is the morning gate; `universe review` is the digest.
- *Live-pricing module needs identity intraday?* → it imports sym's `instrument`/`sym_id` resolver; writes its own intraday store keyed by `sym_id`; never re-mints ids.
- *Backtest module needs point-in-time data?* → it reads `universe_membership` (PIT, survivorship-safe), `fact_returns`, `fact_index_returns`/benchmarks — exactly what Module 1 already guarantees.

### Five Whys — why scheduler-agnostic?
Want a daily refresh → need a scheduler → don't know which (Airflow/Prefect) → don't want to rewrite sym when choosing/switching → keep orchestration OUT of sym → **sym exposes idempotent steps; the scheduler composes them.**

### Analogical Thinking
Mature quant stacks split a **data platform** (system of record: identity, prices, returns — *sym*) from **strategy/research** (backtests, analytics) and **execution/live** layers, all keyed on a stable internal id (CRSP PERMNO / Bloomberg / an internal sym_id). dbt-style: tools (sym CLI/library) are orchestrator-agnostic; Airflow/dbt just *call* them.

### Resource Constraints — smallest valuable now
A `sym eod` command that runs the daily sequence idempotently with per-step status + a non-zero exit on critical failure → cron-able TODAY, and Airflow/Prefect wrappers are thin. Future modules are a documented contract, not code yet.

### Provocation — "embed the scheduler in sym"
Rejected: it marries sym to one tool, bloats deps, and re-implements what Airflow/Prefect do better. sym's job is correct idempotent steps; scheduling is someone else's.

## Convergence — design

**EOD (build now):**
- sym exposes **discrete idempotent steps** (already: `delta`, `recompute`, `fundamentals`, `universe monitor`, `benchmarks`, `validate`) **+ a coarse `sym eod` runner** that sequences the daily core, error-isolated, per-step status, non-zero exit on a critical failure, `--dry-run` to print the plan, `--only/--skip` to scope.
- **Tiered cadence:** daily = monitor → delta → benchmarks → recompute → validate; periodic = fundamentals (weekly), snapshot-calendar (occasional).
- **Scheduler-agnostic:** sym imports **no** Airflow/Prefect. Ship **thin example wrappers** (Airflow DAG, Prefect flow) under `docs/orchestration/` that shell out to `sym <step>` for fine-grained tasks; cron can call `sym eod`.
- **Observability/alerting:** each step's existing run-log (`pipeline_run_log`, `universe_monitor_log`, `validation_run_log`) + `sym validate` exit code + `universe review` digest.

**Modules (document now, build later):** `sym` = Module 1 / system of record. Shared **`sym_id` + published schema-contract** = the integration backbone. Modules: **live pricing** (reuse identity, own intraday store keyed by sym_id), **paper portfolios + backtests** (consume PIT membership + fact_returns + benchmarks), **portfolio analytics** (risk/attribution/alpha vs the benchmark series). Repo: **monorepo of packages** sharing an identity/contract package; data via **shared Postgres (sym = system of record) + sym as an installable library**.

## Apply plan
E1 `sym eod` scheduler-agnostic runner (steps registry, ordering, dry-run, per-step status, exit code) + tests. · E2 thin Airflow + Prefect wrapper templates under `docs/orchestration/` + runbook section. · E3 module-architecture planning doc (`docs/architecture-modules.md`): the `sym_id`+contract backbone, the 3 future modules, data-sharing + repo strategy. (Future modules themselves are out of scope here.)
