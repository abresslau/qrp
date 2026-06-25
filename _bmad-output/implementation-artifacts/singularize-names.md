# Story: Singularize all package + database names

Status: in-progress

<!-- DECISIONS (Andre, 2026-06-25): (1) `rates` STAYS PLURAL for now — deferred, out of this story.
(2) `analytics` STAYS (mass noun). (3) Route URLs (/api/portfolios etc.) KEPT PLURAL — scope is
"database and package names" only; the router prefix is a decoupled string, so zero frontend churn
(singularize routes later if wanted). Rename set this story: commodities→commodity, portfolios→
portfolio, signals→signal (package + DB + schema + sqitch project + all code refs). Branched off
feat/equity-package (heavy file overlap with equity in signals/portfolios) → merges AFTER equity. -->>

<!-- Created via bmad-create-story 2026-06-25 (Andre: "make all database and package names singular").
A cross-cutting naming-consistency normalization: four packages/DBs are plural and should be singular,
matching the already-singular peers (sym, macro, fx, universe, equity, altdata, backtest, operate,
optimiser, lineage). Pure rename — ZERO behavior change; the whole suite + live behavior must stay
green. Not in an epic decomposition (a standalone cross-cutting story, like fx-package / equity-package). -->

## Story

As the QRP maintainer,
I want every package and database name to be singular,
so that the package/DB vocabulary is internally consistent (no plural outliers among the singular peers)
— a pure rename with no behavior change.

## Scope — what is plural (the rename set)

| Current | → Singular | Package dir + pyproject + `[project.scripts]` + `src/<pkg>/` | Database (datname) | Schema | Sqitch `%project` |
|---|---|---|---|---|---|
| `rates` | `rate` | ✓ | `rates` → `rate` | `rates` → `rate` | `rates` → `rate` |
| `commodities` | `commodity` | ✓ | `commodities` → `commodity` | `commodities` → `commodity` | `commodities` → `commodity` |
| `portfolios` | `portfolio` | ✓ | `portfolios` → `portfolio` | `portfolios` → `portfolio` | `portfolios` → `portfolio` |
| `signals` | `signal` | ✓ | `signals` → `signal` | `signals` → `signal` | `signals` → `signal` |

**Already singular (no change):** sym, macro, fx, universe, equity, altdata, backtest, operate,
optimiser, lineage. `operate` owns the `qrp` database (unchanged).

### ⚠️ Decisions to confirm BEFORE implementing (the two genuine judgment calls)

1. **`analytics` — IN or OUT?** `analytics` is a mass-noun domain term (like "macro"); the singular
   "analytic" reads wrong. **Recommendation: leave `analytics` as-is** (it is not a count-plural the
   way rates/signals are). Andre to confirm. (This story EXCLUDES it by default.)
2. **User-facing API route URLs + console pages.** The package routers expose `/api/portfolios`,
   `/api/signals`, `/api/rates`, `/api/commodities` (+ the console pages/links that hit them). These
   are user-facing URLs, not strictly "package/DB names." **Recommendation: rename the routes to match
   (`/api/portfolio`, …) for consistency**, since the package owns its router — but this is a
   coupled frontend change (api client + regenerated `api-types` + any hard-coded console links). If
   Andre wants the URLs left plural for now, the packages can keep their existing route `prefix=` string
   while the package/DB go singular (decoupled — call it out in the dev record). Default here: **rename
   the routes too** (full consistency).

## Acceptance criteria

1. The four package directories are renamed (`packages/rate`, `packages/commodity`,
   `packages/portfolio`, `packages/signal`); each `pyproject.toml` `name`, `[project.scripts]` entry,
   and `src/<pkg>/` directory is singular; `uv sync --all-packages` succeeds.
2. Every `import`/`from` of the renamed packages across the monorepo is updated (no `import rates`,
   `from signals`, etc. remain); `[tool.uv.sources]` entries in dependents updated; root workspace
   `members` updated.
3. Each renamed database is `rate`/`commodity`/`portfolio`/`signal` (datname), with its internal schema
   renamed to match; `tools/deploy_all.py` REGISTRY updated; `deploy_all --status` clean for all 13
   projects. No data lost (DB + schema rename are catalog-only, in place).
4. The Sqitch project name (`%project=` + the deployed registry) is reconciled for each renamed DB so
   `deploy_all` deploy/verify/status all succeed (see Knot 1 — this is the hard part).
5. `lineage`: package constants + `Dataset(package=…)` + the `(package, table)` lineage keys + bucket
   job builders (`bucket_jobs.py`) updated; `lineage.definitions` loads; the data-monitor bucket keys
   that derive from the package name still resolve (or are deliberately kept — see Knot 2).
6. `config.package_dsn` resolves the new names (it derives the DSN from the package name, so a renamed
   package + renamed DB just works — verify, no code change expected).
7. If routes are renamed (per Decision 2): the api router `prefix=`, the frontend api client + the
   regenerated `api-types`, and any console links/pages are updated; the console pages load.
8. **No behavior change.** Full suites green (every package + api), ruff clean, `lineage.definitions`
   loads, `deploy_all --status` clean, and a live smoke (the renamed packages' CLIs + the console
   pages they back) works.

## Developer context — READ THIS FIRST

This is a **pure, wide, mechanical rename** — the danger is not complexity but COVERAGE (miss one
import/schema-ref/registry-entry and something breaks at runtime) and the **stateful renames** (DB,
schema, sqitch project). Do it **one package at a time**, fully green between each, never all four at
once. Blast-radius counts from the 2026-06-25 survey (per package): ~11–18 code refs (imports /
sources / workspace), ~15–30 `<pkg>.<table>` schema-qualified SQL refs, plus the lineage graph keys.

### 🚨 Knot 1 — the Sqitch project rename (the genuinely hard part)
Each package's `db/sqitch.plan` has `%project=rates` (etc.), and the **deployed database's sqitch
registry** (`sqitch.projects`/`changes`) records that project name. Renaming `%project` so it no longer
matches the registry makes sqitch treat it as a different/unknown project — `deploy`/`verify`/`status`
will not line up with the deployed history. Options (pick + document):
- **(a) Rename the project in the registry** to match the new `%project`: update `sqitch.projects.project`
  + `sqitch.changes.project` in the renamed DB (a small, scoped UPDATE), so history is preserved.
  Cleanest if it works with the installed sqitch version.
- **(b) Fresh baseline** on the renamed DB: since these are personal single-instance DBs and the data
  is migrated by the DB/schema rename (not by sqitch), re-initialise the sqitch registry for the new
  project name (the schema already exists; mark all changes deployed / `sqitch deploy` is a no-op). The
  fx/universe/equity drops set the precedent that a non-load-bearing sqitch state is acceptable on these
  DBs.
Verify `deploy_all --status` is clean for the renamed project afterwards either way.

### 🚨 Knot 2 — DB + schema rename mechanics (catalog-only, but ordered)
- **DB rename:** `ALTER DATABASE rates RENAME TO rate` — requires **no active connections** to the DB
  (close pools / stop the api + any Dagster first). Catalog-only; data stays.
- **Schema rename:** `ALTER SCHEMA rates RENAME TO rate` inside the DB — catalog-only; tables/views/
  FKs/indexes follow. Then the schema-qualified SQL in the package's own code (`rates.curve_point` →
  `rate.curve_point`, ~15–30 refs) + any cross-package reader must use the new schema name. If a
  package relies on a DB-level `search_path` (equity's pattern) or unqualified names, confirm it still
  resolves; if it fully-qualifies (fx/rates pattern), every qualified ref must be rewritten.
- **data-monitor / lineage bucket keys** that are the literal package string (e.g. `package_dsn("rates")`)
  follow automatically via the registry rename; bucket *job names* / *data-monitor bucket keys* that
  are cosmetic strings (e.g. `rates_load`) — decide keep-vs-rename (the fx/universe extractions KEPT the
  bucket/job keys to avoid lineage churn; recommend KEEP unless Andre wants them singular too).

### Per-package mechanical checklist (apply to each of the 4)
- `git mv packages/<plural> packages/<singular>`; `git mv .../src/<plural> .../src/<singular>`.
- `pyproject.toml`: `name`, `[project.scripts]`, `[tool.hatch.build.targets.wheel] packages`, pytest
  `pythonpath`/`testpaths` if they name the pkg.
- Rewrite imports repo-wide: `\b(from|import) <plural>\b` → `<singular>`; intra-package
  `<plural>.` → `<singular>.` module refs.
- `[tool.uv.sources]` + `dependencies` in every dependent pyproject (e.g. sym/api/backtest/optimiser
  depend on signals/portfolios/etc.).
- root `pyproject.toml` `[tool.uv.workspace] members`.
- `tools/deploy_all.py` REGISTRY (project key + dir + dbname).
- `db/sqitch.conf` (comments) + `db/sqitch.plan` `%project=` + Knot 1.
- DB rename + schema rename (Knot 2) + the schema-qualified SQL.
- `lineage`: `buckets.py` / `bucket_jobs.py` / `assets.py` (constants, `Dataset(package=…)`,
  `(package, table)` keys, `_spec` package labels).
- api: the package's `router.py` `prefix` (Decision 2) + how the gateway mounts it (`services/api`
  router registry) + `config.package_dsn` (verify only).
- frontend (Decision 2): api client calls to `/api/<plural>`, regenerated `api-types`, console links.
- `.env`: no `<PKG>_DB_NAME` overrides exist today (DB name == package name by default), but check.

### Invariants
- **Pure rename — no behavior, schema-shape, or data change.** A second run of any CLI / endpoint must
  produce identical results to before.
- DB/schema rename is in-place (no dump/restore, no data copy).
- Everything stays green between each package (do NOT batch all four).
- Keep house conventions: Docker-sqitch deploy, explicit-tz schedules, the per-package DB topology.

## Suggested phasing
1. **signal** (smallest user-facing surface; has frontend route — exercises Decision 2 once).
2. **commodity** (data-monitor + console page, no cross-package consumers of note).
3. **rate** (rates curve store + analytics/derive consumers).
4. **portfolio** (most coupled: analytics + optimiser + api routes + lineage user-input nodes).
Each: rename → fix refs → DB/schema/sqitch → lineage/api/frontend → that package's suite + api + ruff +
`deploy_all --status` + live smoke green → commit. Then the next.

## Out of scope / Deferred
- `analytics` (Decision 1 — excluded by default; mass noun).
- Renaming cosmetic Dagster job names / data-monitor bucket keys (e.g. `rates_load`) unless Andre asks
  (Knot 2 — recommend KEEP to avoid lineage churn).
- Any non-name refactor (this is rename-only).

## Verification
- `uv sync --all-packages`; per-package + api suites green; ruff clean; `lineage.definitions` loads.
- `deploy_all --status` clean for all 13 projects (esp. the 4 renamed — Knot 1).
- Grep guard: zero residual `\b(import|from) (rates|commodities|portfolios|signals)\b` and zero
  `\b(rates|commodities|portfolios|signals)\.` schema refs (modulo analytics if excluded).
- Live smoke: each renamed CLI (`rate`/`commodity`/… `--help` + a read verb) + the console pages the
  renamed packages back (CDP/inspection per feedback_minimize_dev_churn).
- Cross-cutting rename → land on a branch, code-review the COVERAGE (no missed ref) + the Knot-1 sqitch
  state + the Decision-2 frontend surface before merge.
