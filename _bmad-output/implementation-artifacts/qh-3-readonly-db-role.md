# Story QH.3: Read-only DB role for sym reads

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the Operator,
I want every consumer read of the **sym** package to go through a least-privilege **read-only** Postgres role (while op-execution and each package's writes to its OWN database keep full credentials),
so that "reads-are-read-only" is enforced by the database engine — not merely by code-review discipline — closing the architecture's dual-credential follow-up the way the DuckDB `READ_ONLY` attach already proved physically.

## Background + scope decision

This is a hardening story (Epic QH), not new capability. It makes the **app-side psycopg** read path match the guarantee the **DuckDB federation** spike already demonstrated.

**Where the guarantee stands today (the gap):**
- Credentials are **instance-level**: every package connects with the libpq-standard `PG*` env (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`), and `PGUSER=postgres` — the **superuser** — is shared by reads, writes, and op-exec alike [`services/api/src/qrp_api/config.py:1-9,73-101`, `.env.example`].
- Architecture says reads-are-read-only is, until federation lands, "a **code-review-enforced discipline, not a physical one**" and that "the dual-credential model resolves to a per-package read-only role" [`architecture-qrp.md` Architecture Revision Log L47-65, L143-144, L326-327].
- The DuckDB spike proved the *federation* read path refuses writes physically (`tools/duckdb_spike.py` claim 3) — but **app-side psycopg assembly remains the implementation** until a surface needs cross-DB SQL (per the QH.5 ledger). So the psycopg sym-read path is the one still on the honor system. **This story hardens exactly that path.**

**The clean seam that makes this small:** a package opens a connection to a **foreign** package's database (sym) *only to read it*; it writes only to its **own** database; and it executes sym ops via a **subprocess** (`uv run sym <op>` from `SYM_PROJECT_DIR`), never through these psycopg reads [`config.py:59-70`, `operate` executor]. So "connection to sym" ⇒ "must be read-only" is a true invariant we can enforce, and op-exec is untouched because it doesn't ride this connection.

**Scope — IN:**
1. A `qrp_readonly` Postgres role on the shared instance with **only** CONNECT/USAGE/SELECT on sym's read surface; no INSERT/UPDATE/DELETE/DDL.
2. A dedicated read-only DSN (`SYM_DATABASE_URL` already exists as the per-package override seam; add a read-only-role credential path) consumed by **every sym-read call site**.
3. Route all sym reads (the `connect("sym")` call sites + the gateway's `db_dsn()`) through the read-only role; own-DB connections and the Operate op-exec subprocess keep full creds.
4. A test proving the role **physically refuses a write to sym** and still **reads** correctly (the psycopg analogue of `duckdb_spike.py` claim 3), wired so it skips cleanly when the role isn't provisioned (no-live-DB CI).
5. `deploy_all.py` / `.env.example` / docs updated so a fresh environment provisions the role.

**Scope — OUT (ledger if touched):**
- DuckDB serving-path adoption (its own deferred story — QH.5 ledger).
- A per-package read-only role for *each* package's own DB (the architecture says "per-package read-only role consumed by the federation layer" — but today only **sym** is read cross-package; the others are read only by their own writer. Generalising to N roles is premature until a second package is read by a third. **Build the sym role now; note the generalisation.**).
- Authenticating the actuation path (NFR-3 conscious risk — unrelated, stays open) [`architecture-qrp.md:107-110`].

## Acceptance Criteria

1. **Read-only role exists, least-privilege.** A migration (or `deploy_all`-registered provisioning SQL) creates role `qrp_readonly` with: `LOGIN`, `CONNECT` on the `sym` database, `USAGE` on `public` (where the read surface lives), and `SELECT` **only** on the allowlisted read-surface relations — exactly the 10-relation `SYM_READ_SURFACE` set in `services/api/tests/test_topology_discipline.py:51-62` (`fact_returns`, `fact_index_returns`, `securities`, `security_symbology`, `security_names`, `universe_membership`, `fundamentals`, `return_window`, `instrument`, `pipeline_run_log`). Derive the GRANT list from that constant — do **not** fork it (the test's docstring says additions are made THERE, deliberately). The role has **no** INSERT/UPDATE/DELETE, no DDL, no privileged role-membership; no blanket `GRANT SELECT ON ALL TABLES` (that would leak the sym-internal relations the allowlist deliberately excludes). Re-running provisioning is idempotent.
2. **Sym reads use the role.** Every place that opens a connection **to sym** resolves the read-only credentials, not `PGUSER=postgres`: the standalone-package `connect("sym")` sites (`portfolios`, `analytics`, `backtest`, `optimiser`, `signals`, `altdata`, `operate` router) **and** the gateway's `db_dsn()` / `package_dsn("sym")` path. A package's connection to its **own** database is unchanged (full creds — it writes).
3. **Op-exec untouched.** Triggering a sym Operation still runs `uv run sym <op>` from `SYM_PROJECT_DIR` with full credentials (the subprocess path), and a live op (e.g. `fx_load`) still completes — the read-only role does not reach the actuation path. (Verified the op path does not borrow a read-only sym psycopg conn.)
4. **Physical refusal proven.** A test connects as `qrp_readonly` and asserts (a) a representative allowlisted `SELECT` succeeds; (b) an `INSERT`/`UPDATE`/`DELETE` and a `CREATE TABLE` against sym are **refused by Postgres** with an insufficient-privilege error (checked for the *right* reason — permission denied, not a syntax/connection error, mirroring `duckdb_spike.py`'s explicit `"read-only" in str(exc)` guard). The test **skips** (not fails) when the role/DB isn't provisioned, so DB-free CI stays green.
5. **Config + credential resolution.** The read-only DSN is resolved from env with a documented precedence (a `SYM_DATABASE_URL` read-only override, or a `PGRO*`-style read-only credential pair, falling back to the existing behavior so nothing breaks before the role is provisioned). No password is logged; libpq keyword-DSN password quoting is preserved (the `config.py:92-95` escaping pattern).
6. **Provisioning is reproducible.** `.env.example` documents the read-only credentials; `tools/deploy_all.py` (or a sibling `tools/` provisioning script it calls) creates/refreshes the role and its grants on a fresh instance; `architecture-qrp.md` dual-credential note + the QH.3 epic line move from "[NEW]" to built, and the ledger records anything deferred.
7. **No regression.** Full suite green; a live smoke shows the console's sym-backed reads (Overview, a signals ranked view, a portfolio's analytics) still render through the read-only role; `sym validate` and an Operate-triggered op still run.

## Tasks / Subtasks

- [x] **Task 1 — Provision the read-only role (AC: 1, 6).**
  - [x] `tools/provision_readonly.py`: idempotent role create/refresh (`CREATE`/`ALTER ROLE qrp_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD`), `REVOKE ALL` then `GRANT CONNECT` on `sym`, `REVOKE ALL` then `GRANT USAGE` on `public`, `GRANT SELECT` per surface relation only; `--check` mode reports surface coverage + flags any LEAK. Chose the `tools/` script over a sym Sqitch change (decision recorded in its docstring): it reads the allowlist from the shared contract and stays out of sym's migration plan; roles are cluster-global, grants per-DB — provisioned accordingly.
  - [x] GRANT list derived from `qrp_api.sym_contract.SYM_READ_SURFACE` — extracted the constant out of the test into a shared module both the test and the provisioner import (single source; no duplication). No blanket `GRANT SELECT ON ALL TABLES` (would leak the internal relations). Missing-from-DB surface relations are named, never silently skipped.
  - [x] Wired into `tools/deploy_all.py` (provisions after sym deploys; non-fatal when `PGRO_PASSWORD` absent → reads fall back to full creds); `.env.example` documents `PGRO_USER`/`PGRO_PASSWORD`/`SYM_READONLY_URL`.
- [x] **Task 2 — Read-only credential resolution in config (AC: 5).**
  - [x] `services/api/src/qrp_api/config.py` gains `sym_readonly_dsn()`; the 8 standalone `db.py` helpers gain an identical `_sym_readonly_target()` (kept byte-identical bar the docstring/`_OWN` — the DRY item the qrp-restructure folds later).
  - [x] Precedence implemented + unit-tested: `SYM_READONLY_URL` (whole DSN) → `PGRO_USER`/`PGRO_PASSWORD` role creds → full-cred fallback; libpq password quoting preserved (special-char test green).
- [x] **Task 3 — Route sym reads through the role (AC: 2, 3).**
  - [x] Routing centralized in the `connect()` helpers — `connect("sym")` (foreign read) → read-only target; `connect(_OWN)` → full creds. So the 5 router sites, the `__main__` smoke blocks, `operate/router.py` history read, and the gateway's default `connect()` route read-only with **no per-call-site edits** (verified live: each lands on `qrp_readonly`; own-DB stays `postgres`). **Exception (code review 2026-06-14):** the `lineage` package opens sym directly with full creds and is NOT routed — it is an offline introspection generator that reads sym-internal relations across all DBs and structurally cannot use the surface-only role; documented in `generate.py` + ledgered as a deliberate exception. "Every serving-path consumer" is the accurate claim, not "every connection".
  - [x] Op-exec confirmed untouched (AC3): `operate/executor.py` actuates via `subprocess.Popen(["uv","run","sym",...])` with full `PGUSER` creds (sym's own code never reads `PGRO_USER`); its only psycopg `connect()` is the own `qrp.job` ledger. Read-only role never on the actuation path.
- [x] **Task 4 — Prove physical refusal (AC: 4).**
  - [x] `services/api/tests/test_readonly_role.py`: live-gated integration test (skips unless the connection lands on `qrp_readonly`) asserts an allowlisted SELECT works, and INSERT/UPDATE/DELETE/CREATE + a sym-internal SELECT are refused with `psycopg.errors.InsufficientPrivilege` (the right reason — the `duckdb_spike.py` lesson) + 6 DB-free unit tests for resolution precedence and central routing. All 11 green (live test ran, not skipped).
- [x] **Task 5 — Docs, live smoke, finishers (AC: 6, 7).**
  - [x] `architecture-qrp.md` dual-credential note updated (psycopg read path: discipline → physical); QH.3 epic line → `[BUILT]`; ledger records the deferred per-package/cross-module generalisation.
  - [x] Live: role provisioned (10/10 surface relations); full suite **786 passed** (+ the 1 pre-existing, stash-confirmed unrelated `test_durable_reviews` import failure); gateway + signals + operate sym reads smoke-verified on `qrp_readonly`; ruff clean. Did NOT run a live mutating op (fx_load hits external sources) — AC3 covered structurally + by the passing Operate test suite.

### Review Findings (code review 2026-06-14 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

- [x] [Review][Patch] **`lineage` package bypasses the read-only helper — reads sym with full superuser creds** (edge+auditor, HIGH) — `packages/lineage/src/lineage/generate.py:142-149` builds `_dsn()` (`PGUSER`/`PGPASSWORD`) and calls `psycopg.connect(**base, dbname="sym")` directly, never the `connect()` helper, so the central `dbname=="sym"` routing never fires. It reads sym-INTERNAL relations (`prices_raw`/`fx_rate`/`gics_scd`…) and introspects ALL package DBs, so it **structurally cannot** use `qrp_readonly` (surface-only, sym-only). This contradicts the story's "converted every consumer call site" / "every place that opens a connection to sym" claim. Fix = correct the overclaim and **ledger `lineage` as a deliberate admin-introspection exception** to the read-only-role discipline (it is an offline Dagster lineage generator needing cross-DB catalog access, not a serving-path consumer; the topology gate already excludes it from `CONSUMER_PACKAGES`).
- [x] [Review][Patch] **`.env.example` ships `PGRO_USER` uncommented but `PGRO_PASSWORD` commented** [.env.example] (edge, MED) — the full-cred fallback only triggers when `PGRO_USER` is UNSET; with the example's default (`PGRO_USER=qrp_readonly`, `PGRO_PASSWORD` commented), a fresh copy builds a passwordless read-only DSN and consumer reads FAIL at connect. Fix = ship `PGRO_USER` commented too (opt-in to the role; pre-provision falls back to full creds as intended).
- [x] [Review][Patch] **`deploy_all.py` top-level `import provision_readonly` breaks `-m`/`--status`/`--help`** [tools/deploy_all.py:28] (blind+edge, MED) — the bare import resolves only when `tools/` is on `sys.path` (script form), and runs before argparse, so `python -m tools.deploy_all` (or any qrp_api-less env) ImportErrors even for no-provision paths. Fix = import lazily inside the provisioning branch.
- [x] [Review][Patch] **`provision()` REVOKE→GRANT is non-atomic under autocommit** [tools/provision_readonly.py] (blind, MED) — a crash between `REVOKE ALL` and the GRANT loop leaves a previously-working role stripped of all access (consumer reads break until re-run). Fix = wrap step-2 REVOKE+GRANT in one explicit transaction so the surface swaps atomically.
- [x] [Review][Dismiss] host/port omitted in package `_sym_readonly_target()` vs included in API `sym_readonly_dsn()` — consistent with the pre-existing standalone-`db.py` pattern (libpq reads `PG*` env); edge hunter verified it works. Not a defect.
- [x] [Review][Dismiss] live test `assert n >= 0` after `count(*)` is vacuous — it intentionally proves SELECT is *permitted*; acceptable. Also: reading `prices_raw` raising `UndefinedTable` instead of `InsufficientPrivilege` on a sym missing that table — implausible on a provisioned sym.
- [x] [Review][Dismiss] `provision()` returns 0 when a surface relation is absent — it WARNs by name (no silent drop); defensible for phased rollout.
- [x] [Review][Dismiss] AC2 phrasing "route `db_dsn()`" — `db_dsn()` intentionally kept full-cred; routing achieved by switching the gateway `connect()` default to `sym_readonly_dsn()`. Functionally correct; story wording tightened with the overclaim fix above.

### Post-merge correction (2026-06-14, found by live `npm run dev` smoke)

**Defect:** AC2 routed the gateway's default `connect()` (the `services/api` helper) through `qrp_readonly`, and AC7's "Overview renders through the read-only role" smoke was **never actually exercised in a browser**. The gateway's **first-party sym "See" module** (`modules/sym/gateway.py`) is QRP's observability window into sym and reads sym-INTERNAL relations by design — `universe`, `prices_raw`, `gics_scd`, `fx_rate`, `price_gaps`, `universe_member_resolution`, the review/validation logs — none of which are on the 10-relation surface. So the narrow role `permission denied`-ed the **entire** Q2 See surface (Overview/Universes/Heat map/Security detail/Attention/Validation): `GET /api/sym/overview` 500'd on `SELECT count(*) FROM universe`.

**Root cause:** scope error. The AR-R3 read surface is the **cross-package** contract (the 8 `packages/*` consumers reading sym for returns/labels — correctly hardened, the real win of QH.3). The gateway's first-party See module is NOT a cross-package consumer; it is the platform's broad sym viewer, read-only **by convention**, exactly analogous to the `lineage` full-cred exception this same review already blessed. Routing it through the surface-only role was overreach.

**Fix:** `services/api/src/qrp_api/db.py` `connect()` reverts to full creds (`db_dsn()`, read-only by convention) for the first-party See module; the 8 cross-package consumers keep `qrp_readonly` (their `db.py` helpers + `test_readonly_role.py` are untouched — that hardening stands). Verified live: all six See endpoints 200 (overview securities=2150/universes=14; heat map 838 cells with sectors). Ledgered: a **broad introspection-scoped read-only role** would harden this serving-path first-party reader physically (it's a bigger sym reader than offline lineage) — a follow-up decision, not done here.

## Dev Notes

### Current state of files being modified (read before changing)

- **`services/api/src/qrp_api/config.py`** — branding + DSN factory. `package_dsn(pkg)` builds a keyword DSN from `PG*` env, honoring `<PKG>_DATABASE_URL` (whole-DSN) and `<PKG>_DB_NAME` (name-only) overrides, with careful libpq password quoting (L92-95). `db_dsn()` = `package_dsn("sym")`. **`sym_project_dir()` (L59-70) is the op-exec code path — a directory, not a credential; leave it alone.** Add a read-only resolver here; do not break the existing override seams.
- **`services/api/src/qrp_api/db.py`** — one-liner: `connect(dsn=None)` → `psycopg.connect(dsn or db_dsn(), …)`. Docstring already says "read-only by convention" — this story makes it true. The gateway's sym reads come through here.
- **`packages/<pkg>/src/<pkg>/db.py`** — 8 near-identical standalone helpers. `connect(dbname=_OWN)` loads `.env`, resolves `<DB>_DATABASE_URL` or `dbname=<db>` from `PG*`. **The same `connect("sym")` is used for the cross-package read and `connect(_OWN)` for the own-DB write — the dbname is the discriminator** (sym ⇒ read-only). Keep the 8 copies byte-identical (known DRY debt; the qrp/packages restructure folds them — do not partially refactor here).
- **Sym-read call sites (Task 3 targets), confirmed read-only by inspection:** `packages/{portfolios,optimiser,backtest,analytics,signals}/src/.../router.py` open `connect("sym")` and hand it to a gateway as `sym_conn`, which only SELECTs (labels, `fact_returns`, `fact_index_returns`, `instrument`, `security_symbology`, `security_names`). `__main__` smoke blocks in `optimiser/engine.py:421`, `backtest/engine.py:364`, `altdata/ingest.py:187`, `signals/compute.py`. `operate/router.py:101 connect("sym")` — verify it's a read (run-history/freshness), then route read-only.

### Key constraints / patterns to follow

- **AR-R2 / AR-R3 (architecture-qrp):** cross-package reads are app-side over a **separate read-only connection**; sym is a read-only upstream **peer**, never mutated by consumers. This story implements the "read-only connection" literally at the credential layer. [Memory: `sym is a peer, not the hub`; `Two identity keys by design`.]
- **Single source of truth for the read surface:** the allowlist already lives in `services/api/tests/test_topology_discipline.py` (the AR-R3 sym read-surface allowlist + vocabulary guard from QH.5). The GRANT list must be **derived from it**, so granting and the discipline test can never drift. [`epics-qrp-roadmap.md` QH.5 AC.]
- **Idempotent provisioning, fresh-env proven** — match the QH.5 `deploy_all.py` ethos (create-missing/refresh, proven from-nothing on a scratch DB). [`epics-qrp-roadmap.md` QH.5.]
- **Explicit-reason error assertion** — when asserting the write is refused, check the error is *permission denied*, not any error (the `duckdb_spike.py:83-88` lesson: an unqualified `except`/`assert` would bless a connection failure as "success").
- **Engineering patterns:** psycopg3, ruff line-length 100, DB-free unit tests + a live-gated integration test, one durable transaction per unit of work; `as_of_date` is the canonical date name everywhere. [Memory: `as_of_date is canonical everywhere`; sym NFR6.]
- **Postgres role mechanics:** `psycopg.connect(connect_timeout=5)` is the house call; a keyword DSN (`host=… dbname=… user=… password='…'`) is what `package_dsn` emits — the read-only DSN should match that shape so quoting/edge-cases are shared, not reinvented.

### Project Structure Notes

- New artifact: a provisioning script under `tools/` (sibling to `deploy_all.py` / `duckdb_spike.py`) is the lowest-coupling home — it can read the allowlist and isn't part of sym's Sqitch plan. If instead a sym migration is chosen, it must live in sym's project and the role/grants are sym-DB-scoped (cross-DB role grants aren't a thing — roles are cluster-global, grants are per-DB; provision the role cluster-wide once, grant per sym DB).
- `.env` gains a read-only credential pair; `.env.example` documents it. No console/TS changes expected (this is a credential-layer change behind unchanged API responses) — confirm `gen:types` is a no-op.
- The 8 `db.py` copies are knowingly duplicated; the decided qrp/packages restructure folds them later. [Memory: `QRP structure target`.] Change all 8 consistently; do not start the fold here.

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md#Story QH.3 — Read-only DB role for sym reads]
- [Source: _bmad-output/planning-artifacts/architecture-qrp.md#Architecture Revision Log (L40-65: DuckDB READ_ONLY + read-only role; L143-144 & L326-327: dual-credential model; L107-110: NFR-3 least-privilege still applies)]
- [Source: services/api/src/qrp_api/config.py#package_dsn/db_dsn/sym_project_dir]
- [Source: services/api/src/qrp_api/db.py#connect]
- [Source: packages/signals/src/signals/db.py#connect (representative of the 8 standalone helpers)]
- [Source: tools/duckdb_spike.py (the federation read-only proof this story mirrors at the psycopg layer; claim 3 = physical write-refusal + explicit-reason assertion)]
- [Source: services/api/tests/test_topology_discipline.py (the sym read-surface allowlist — single source for the GRANT list)]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md (QH.5 deferrals: DuckDB serving-path is a separate story; topology-gate honest limits)]

## Dev Agent Record

### Agent Model Used

claude-opus-4-8[1m] (Opus 4.8, 1M context)

### Debug Log References

- Live provision: `uv run python tools/provision_readonly.py` → "granted SELECT on 10/10 read-surface relations; CONNECT on sym; no write, no DDL"; `--check` → "10/10 surface relations", no LEAK.
- Physical-refusal smoke (as `qrp_readonly`): SELECT securities = 2150 ✓; `prices_raw` (internal) refused — permission denied ✓; INSERT/CREATE refused — permission denied ✓.
- Routing smoke: gateway `connect()` → `qrp_readonly`; `signals.connect("sym")` → `qrp_readonly`; `signals.connect()` → `postgres`@`signals`; `operate.connect("sym")` → `qrp_readonly`.
- Suite: `uv run pytest -q --import-mode=importlib` → 786 passed, 1 failed; the failure (`test_durable_reviews::test_fx_coverage_warns_on_open_rejections`, `from tests.test_fx_coverage import _Conn`) reproduced on clean HEAD via `git stash` → pre-existing, unrelated.
- `ruff check` on all changed files → All checks passed.

### Completion Notes List

- **Central routing was the key simplification:** the sym read path is the `connect()` helper, so hardening it there (`dbname == "sym" and dbname != _OWN` → read-only target) converted every consumer call site that *uses the helper* at once — no router edits. The same guard excludes the sym package itself (its `_OWN == "sym"`, so it keeps full write creds). **Caveat (review):** `lineage/generate.py` connects to sym directly (not via the helper) and deliberately keeps full creds (admin introspection of internal relations across all DBs) — a documented exception, not a covered site.
- **Single source of truth:** `SYM_READ_SURFACE`/`SYM_INTERNAL_RELATIONS` moved to `qrp_api/sym_contract.py`; the topology gate imports them and so does the provisioner — the role's grants and the discipline gate can't drift.
- **Bonus guarantee:** the role also can't read sym-INTERNAL relations (only the 10-relation surface is granted), tightening AR-R3 beyond the write-refusal AC.
- **Pre-provision safety:** with no `PGRO_USER`, reads fall back to full creds (read-only by convention) — nothing breaks before the role exists.
- **Deferred (ledgered):** cross-module reads (signals→macro/altdata) still use full creds — only sym is hardened now; a per-package read-only role per cross-read target is the generalisation, premature today.

### File List

- `services/api/src/qrp_api/sym_contract.py` (NEW) — shared read-surface contract + `READONLY_ROLE`
- `services/api/src/qrp_api/config.py` (UPDATE) — `sym_readonly_dsn()` resolver; `db_dsn` docstring
- `services/api/src/qrp_api/db.py` (UPDATE) — default `connect()` → read-only sym
- `services/api/tests/test_topology_discipline.py` (UPDATE) — import surface from the contract module
- `services/api/tests/test_readonly_role.py` (NEW) — 6 unit + 1 live-gated test
- `packages/{altdata,analytics,backtest,macro,operate,optimiser,portfolios,signals}/src/*/db.py` (UPDATE ×8) — `_sym_readonly_target()` + read-only routing in `connect()`
- `tools/provision_readonly.py` (NEW) — idempotent role provisioner (`--check` mode)
- `tools/deploy_all.py` (UPDATE) — provision the role after sym deploys (non-fatal)
- `.env.example` (UPDATE) — `PGRO_USER`/`PGRO_PASSWORD`/`SYM_READONLY_URL` documented
- `.env` (UPDATE, gitignored) — local read-only role creds for provisioning + verification

### Change Log

- 2026-06-14 — Implemented QH.3: least-privilege `qrp_readonly` role; all consumer sym reads routed through it (gateway + 8 packages); physical write-refusal proven (live test + manual). 786 tests pass; ruff clean. Status → review.
