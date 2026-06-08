# Multi-module architecture

`sym` is **Module 1** — the data platform / **system of record**: identity
(`sym_id`), market data (prices + index levels), returns, universes, benchmarks.
Other modules are planned to build *on* it, not fork it. This doc fixes the
integration backbone so they compose cleanly.

## The backbone: `sym_id` + the published contract

- **Identity:** every instrument (equity, index, and future kinds) has a stable
  internal **`sym_id`**; vendor ids (CompositeFIGI, Yahoo, MSCI, ISIN, FIGI) hang
  off it in `instrument_xref`. **No module re-mints identity** — they resolve
  through sym (`instrument`/`instrument_xref`). This is the universal join key
  across the whole stack.
- **Contract:** `docs/schema-contract.md` is the stable surface other modules
  depend on. Breaking changes are new Sqitch migrations + a versioned change,
  never in-place edits (see `docs/data-conventions.md`, runbook §0).
- **System of record:** sym owns the immutable source data + deterministic
  derivations. Other modules **read** via the contract and write into **their own**
  schemas/tables — they never mutate sym's.

## Sharing pattern

- **Data:** one shared PostgreSQL database. sym's tables are the system-of-record
  schema; each module gets its own schema and reads sym via the contract (or a
  thin view layer). No data copying / no reconciliation.
- **Code:** sym is an **installable library** (its `identity`/`returns`/`benchmarks`
  helpers are importable) *and* a CLI. Modules import the identity resolver rather
  than reimplement it.
- **Repo:** start as a **monorepo of packages** (`sym`, `sym-live`, `sym-backtest`,
  `sym-analytics`) sharing an identity/contract package; split to polyrepo (sym
  published + pinned) only if teams/release cadences diverge.
- **Orchestration:** scheduler-agnostic (see `docs/orchestration/`). Each module
  exposes idempotent steps; Airflow/Prefect compose them.

## Planned modules (not built yet)

| Module | Consumes from sym | Adds | New stores (keyed on `sym_id`) |
|---|---|---|---|
| **Live / intraday pricing** | `instrument`/`sym_id` resolver, symbology, calendars | real-time quote ingestion + last-price cache | `intraday_quotes`, `last_price` |
| **Paper portfolios + backtests** | `universe_membership` (PIT, survivorship-safe), `fact_returns`, benchmarks | positions, trades, NAV, backtest runs | `portfolio`, `position`, `backtest_run`, `nav` |
| **Portfolio analytics** | `fact_returns`, `fact_index_returns`, `universe_benchmark` | risk, exposures, attribution, alpha/beta vs benchmark | `analytics_*` result tables |

### Why this works
- The **PIT + survivorship guarantees** sym already enforces (membership
  `pit_valid_from`, returns over all securities) are exactly what a *correct*
  backtest needs — no look-ahead, no survivorship bias.
- **Alpha/attribution** uses the benchmark series + links built in the Benchmark
  epic (`fact_index_returns`, `universe_benchmark`): excess return = portfolio − benchmark.
- **Live pricing** reuses the identity spine, so an intraday tick and an EOD bar
  for the same name share one `sym_id` — joinable everywhere.

## Boundaries (what sym does NOT do)
No orchestration engine, no portfolio/position state, no intraday store, no
strategy logic. sym stays the clean, deterministic, reconstructable data platform;
everything stateful/strategic lives in the modules above.
