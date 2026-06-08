---
title: QRP — Repo / Package Structure (target architecture + migration plan)
status: proposed
created: 2026-06-08
author: Andre
supersedes: the "Project Structure & Boundaries" section of architecture-qrp.md (monolithic qrp_api tree)
relates_to:
  - architecture-qrp.md (Architecture Revision Log — DB-per-package topology)
  - epics-qrp-roadmap.md (the modules being restructured)
  - brainstorming-session-2026-06-07-195212.md (Mirantia: standalone/sellable packages)
---

# QRP — Repo / Package Structure

A high-level mental model for how QRP's code, data, and packages fit together — and a plan to
get from today's structure to it. **No code in this doc; it is the durable map + the staged plan.**

## 1. The problem (why this doc exists)

The DB-per-package migration made the **data** independent (each module owns its Postgres database
+ Sqitch project), but the **code** did not follow. Today:

- **Data layer — per package ✅** (`db/<pkg>/` Sqitch projects → per-package databases).
- **Code layer — monolithic ❌** — `macro`, `signal`, `backtest`, `optimiser`, `altdata`,
  `portfolios`, `analytics` are *subfolders* of one FastAPI app (`services/api/src/qrp_api/modules/`).
  A `macro` change and a `signal` change edit the same package; there is no real boundary.
- **sym — external, reached by guesswork** — qrp reads sym's tables over a DSN and runs Operations
  via **`subprocess: uv run sym <op>`** with `cwd = sym_project_dir()`, which guesses a sibling
  `../sym` or hardcodes `C:/Projects/sym`. The reserved `packages/sym/` slot is an empty stub.

**Flimsy path constructions (the symptom):** `config._repo_root()` (walks parents for
`platform.toml`), `sym_project_dir()` (guesses/hardcodes sym's path), `_load_dotenv()` (walks up),
`package_dsn()` (string-builds DSNs). A package should never have to *find* the monorepo root or
*guess where its dependency lives on disk.*

**The key realization:** `sym` is already a standalone package **done right** — own `src/sym/`, own
migrations, own CLI, own deps, own database. It is the **template**. The QRP modules should each
become sym-shaped packages, and `qrp` should be *only the composer*.

## 2. Principles

- **P1 — A package is a vertical slice.** Each module owns its full stack: code (ingest/compute/
  gateway/router), migrations, database, deps, version, tests — and later, its console UI slice.
  "Standalone-shaped": extractable to its own repo with zero code change.
- **P2 — qrp composes; it does not contain.** `qrp` is the shell (console) + the gateway (mounts
  each enabled package's router) + `platform.toml`. Business logic lives in the packages.
- **P3 — Dependencies point inward to the hub.** `qrp → {sym, macro, signal, …}`; packages never
  depend on `qrp`. Everything reads the **sym hub** through the *discipline* (`sym_id` + sym's
  stable published views; no cross-DB FK) — not a path hack, not an SDK (solo right-sizing).
- **P4 — Reversible by default.** Monorepo now; a clean polyrepo split (or a per-package service)
  is a later, mechanical move when a real driver appears (selling a package, separate cadence/team).

## 3. Decisions (recommended defaults)

| # | Decision | Default | Why |
|---|----------|---------|-----|
| D1 | Monorepo vs polyrepo | **Monorepo of standalone-shaped packages** (uv workspace members) | Solo: one clone/PR/atomic change; boundaries (not physical repos) satisfy the sellable-module goal; polyrepo split stays mechanical. |
| D2 | Fold sym in vs keep external | **Fold sym in as `packages/sym`** (interim: clean path-dependency) | Removes the subprocess + `cwd`-guess coupling; sym becomes a normal workspace member; the slot already exists; reversible. |
| D3 | sym Operations: library vs subprocess | **Library-first** (honor ADR-1; the import-probe passed) | `import sym`; drop the `cwd`-guess; subprocess only as a fallback for any CLI-only op. |
| D4 | One service vs service-per-package | **One gateway mounts each enabled package's router** (AR-Q3 + FR-1 toggle) | One process to run; packages own their routers; per-package services deferred to a real scaling need. |

Connective tissue (already decided): the **contract is a discipline** — `sym_id` + sym's stable
views + no cross-DB FK + app-side cross-package assembly. No SDK package until/if selling.

**D5 — Credentials are instance-level, named neutrally (decided 2026-06-08).** The shared Postgres
instance creds use the **libpq-standard `PG*`** env (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`), NOT a
`SYM_DB_*` (or any per-package) prefix — "sym" is not the base for everything; it is just a package
whose database is named `sym`. Each package only names its own database (`dbname = <package>`);
override a package's whole DSN with `<PKG>_DATABASE_URL`. (Replaced the old `SYM_DB_*` base in `.env`
+ `qrp_api.config` + `macro.config`.)

## 4. Target structure

```
qrp/                                   the platform monorepo (one repo; uv + npm workspaces)
├─ platform.toml                       brand + enabled packages (feature toggles)
├─ pyproject.toml                      uv workspace: members = packages/* + apps/gateway
├─ package.json                        npm workspaces: apps/* + the per-package console slices
│
├─ packages/                           the standalone-SHAPED packages (each extractable to its own repo)
│  ├─ sym/                             THE TEMPLATE — folded in, history preserved
│  │   ├─ pyproject.toml · src/sym/ · migrations/ (sqitch) · cli · tests/   (its own database)
│  ├─ macro/
│  │   ├─ pyproject.toml
│  │   ├─ src/macro/  (ingest.py · gateway.py · router.py · db.py · config.py)
│  │   ├─ db/  (sqitch → the `macro` database)
│  │   └─ tests/
│  ├─ signal/ · backtest/ · optimiser/ · altdata/ · portfolios/ · analytics/   (all sym-shaped)
│  └─ contract/  (OPTIONAL, later) — only if selling: published sym_id + view types + an SDK
│
├─ apps/
│  ├─ gateway/                         the API composer: imports each enabled package's router and
│  │                                   mounts it; hosts the app-side cross-package assembly; the
│  │                                   only place that knows about "all packages". (was services/api)
│  └─ console/                         the shell: nav · theme · command palette; mounts each
│                                      package's console slice; reads the gateway.
│
└─ scripts/                            dev (run gateway + console), deploy-all-migrations, gen-types
```

**Anatomy of a package (`macro` shown; sym is the working exemplar):**
- `src/macro/router.py` — its FastAPI router (qrp *mounts* it; doesn't own it).
- `src/macro/gateway.py` — its reads (own DB) + app-side enrichment from the sym hub.
- `src/macro/ingest.py / compute.py` — its logic; reads the sym hub via a *contract* connection.
- `src/macro/config.py` — its own connection config (a DSN it is *given*, not one it walks the
  filesystem to discover).
- `db/` — its Sqitch project → its database. `pyproject.toml` — its own deps + version.

**qrp's job, precisely:** read `platform.toml` → for each enabled package, mount its router
(gateway) and its UI slice (console). That's all. Adding a package = add a workspace member + flip
a toggle (NFR-10, finally real).

## 5. How this fixes the flimsiness

| Flimsy thing today | Replaced by |
|---|---|
| `sym_project_dir()` guess/hardcode `C:/Projects/sym` | sym is a workspace member → `import sym`; no path on disk to guess |
| Operate `subprocess: uv run sym` + `cwd`-guess | library-first call into sym (D3); subprocess only for CLI-only ops |
| `_repo_root()` walking for `platform.toml` | config injected into the gateway; packages get their config, don't hunt for root |
| `_load_dotenv()` walking up | gateway loads env once and injects DSNs into packages |
| `package_dsn()` string-building in one shared config | each package owns its connection config (a given DSN) |
| `qrp_api/modules/<m>/` (no boundary) | each module is its own `packages/<m>/` package (own pyproject) |

## 6. Migration plan (current → target) — staged, incremental, reversible

Each step is independently shippable and leaves a working system. **Not executed by this doc.**

1. **Carve one module out as the pilot package** ✅ **DONE 2026-06-08** — `macro` is now
   `packages/macro/`: own `pyproject` (uv workspace member), `src/macro/` (router/gateway/ingest/
   sources + its OWN `config.py`/`db.py` — no `qrp_api` import, no path-walking), and its Sqitch
   project moved to `packages/macro/db/`. The gateway (`services/api`) declares `macro` as a
   workspace dep and mounts `macro.router`; `qrp_api/modules/macro/` is gone. Verified: macro served
   from the package; sym/signal/portfolios/operate unaffected. **Also fixed here: credential
   naming** — see the PG* convention below.
2. **Repeat for the rest** ✅ **DONE 2026-06-08** — `portfolios`, `signals`, `optimiser`,
   `backtest`, `altdata`, `analytics`, and `operate` (the `qrp_core`/job ledger) are all
   standalone packages now; `qrp_api/modules/` holds only `sym`. Each package has a minimal
   `db.py` (names its database; libpq fills the rest from `PG*`). Note: `signal` was renamed
   to **`signals`** everywhere (package + database + schema + `/api/signals` + key + route) —
   a top-level package named `signal` collides with the stdlib `signal` module, so one
   consistent name was the fix (no dual convention).
3. **Rename `services/api` → `apps/gateway`** — strip it to *only* mounting routers + the
   cross-package assembly; delete the per-module business logic now living in the packages.
4. **Fold sym in (D2)** ✅ **DONE 2026-06-08 (operationally)** — sym's `src/`, migrations,
   `sqitch.conf`, pyproject (console script `sym`), README + tests are now `packages/sym/`
   (a workspace member). `uv run sym` and `import sym` resolve from the qrp env; Operate runs
   the installed `sym` script (no path-guess); `sym_project_dir()` deleted. sym's config layers
   `PG*` ahead of legacy `SYM_DB_*`. qrp no longer needs `C:\Projects\sym` to exist to run.
   **Remaining to fully retire the old repo:** relocate the planning/tooling artifacts
   (`_bmad-output`, `docs`, `.claude` skills, the agent memory) into qrp, then delete the old
   path. Deferred deliberately — that substrate hosts the live session/memory; do it from a
   fresh session rooted in qrp. The old repo stays as the history/planning archive until then.
   (Library-first Operate per D3 is a later refinement; subprocess isolation is kept for now.)
5. **Kill the path hacks (§5)** ◑ **PARTIAL** — `package_dsn()` is gone (per-package `db.py` +
   libpq `PG*`); `sym_project_dir()` is gone (sym folded in). Still in `qrp_api.config`:
   `_repo_root()`/`_load_dotenv()` for `platform.toml` — to be injected when services/api → apps/gateway (step 3).
6. **Move each package's `db/<pkg>/` Sqitch project into its own `packages/<pkg>/db/`** ✅ **DONE** —
   done as part of each carve; analytics has no database; operate owns the `qrp` job ledger;
   the `signals` project + database + schema were renamed and the registry rebaselined.

**Guardrails during the migration:** no behavior change per step (the API surface + DB stay
identical — verified by the same endpoint checks + replay tests already in use); each step is its
own commit; the typed contract (gen-types) re-runs each step.

## 7. Deferred (later, when a driver appears)
- **Polyrepo split** — extract a `packages/<pkg>` to its own repo (mechanical once boundaries hold).
- **Per-package service** — run a package's router as its own service/port (independent scaling).
- **`contract` package + SDK** — only if selling a package or pointing one at a *remote* sym.
- **Generic module-registry / bundle loader + command palette (FR-2)** — the NFR-10 framework,
  now justified (8 modules exist).

## 8. The one-sentence mental model
> **sym is the template; every module becomes a sym-shaped standalone package owning its own
> code+DB+migrations+router; `qrp` is only the shell+gateway that mounts the enabled ones — and
> "standalone repos" means each package is extractable, not that they must be split today.**
