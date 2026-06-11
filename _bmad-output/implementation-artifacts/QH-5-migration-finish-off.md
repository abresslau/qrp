# Story QH.5: Migration finish-off — deploy-all, the AR-R3 discipline gate, DuckDB live-attach

Status: done

## Story

As Andre (the operator),
I want one command that deploys every per-package Sqitch project (creating missing databases from a DSN registry), a suite-enforced check that the DB-per-package discipline holds, and the DuckDB live-attach spike actually re-run,
so that the DB-per-package migration's follow-ups are closed and the topology's "contract = discipline" is enforced by a gate instead of convention.

## Background + scope decision

Epic QH Story QH.5 `[NEW]`: *"one command deploys all per-package Sqitch projects + brings up all DBs (a DSN registry); a CI check forbids cross-DB FKs and asserts consumers read only sym's stable views (AR-R3). The DuckDB live-attach spike is re-run in a network-enabled env to finalise live-vs-materialised per surface."*

**Current state (read 2026-06-11):** 8 Sqitch projects (sym in `packages/sym/migrations`; operate owning the `qrp` DB; altdata/backtest/macro/optimiser/portfolios/signals each in `packages/<pkg>/db`), each deployed by hand via the Docker sqitch one-liner. No registry, no gate, and the live-attach spike was deferred for env reasons.

**Probes this session (the env reasons are GONE):** `duckdb` installs; `INSTALL postgres` succeeds (extension egress works); a live `ATTACH … (TYPE postgres, READ_ONLY)` federation joined `signals.score` × `sym.security_symbology` cross-database and reproduced the fiscal_sens ranking exactly (FFIV/CASY/EG); a DELETE through the attachment is refused with "attached in read-only mode" — physical read-only enforcement confirmed.

**Design decisions:**
1. **Registry + deployer = `tools/deploy_all.py`** (stdlib + psycopg; Docker sqitch like the by-hand runs). The registry maps project dir → database name, discovered from the repo layout with the two irregulars (sym→`sym` from `migrations/`, operate→`qrp`) explicit. Creates missing databases, then `sqitch deploy` + `verify` per project; `--status` mode reports without deploying. Exit non-zero on any failure.
2. **The "CI check" is a suite test** (no CI exists — the suite IS the local gate; the A.1 types-freshness lesson says scripts without runners rot): `services/api/tests/test_topology_discipline.py` asserting (a) no package's deploy SQL references another package's schema (cross-DB FKs are impossible in Postgres, so the enforceable rule is no cross-schema DDL coupling); (b) every consumer package's sym reads use only the DOCUMENTED read surface — an explicit allowlist constant (the architecture's "base tables are accepted until the federation restructure" note makes the allowlist the stable-views contract for now); (c) the workspace's package dependency edges match the declared topology (consumers import sym data only via connections, not via a sym Python import).
3. **DuckDB spike = recorded finding, not new plumbing:** the architecture asked to "finalise live-vs-materialised per surface" — the finding (live attach works, read-only enforced, extension reachable) goes into the architecture revision log + ledger; adopting DuckDB in serving paths is its own future story. `duckdb` added to the root dev group so the spike is re-runnable (`tools/duckdb_spike.py`).

**Explicitly OUT of scope:** adopting DuckDB in any serving path; CI infrastructure; the read-only Postgres role (QH.3, its own story); changing any migration content.

## Acceptance Criteria

1. **`tools/deploy_all.py`:** discovers all 8 projects via an explicit registry; `--status` shows per-project plan-vs-deployed state; default run creates missing databases (idempotent) and runs Docker sqitch `deploy` + `verify` per project; any failure → non-zero exit with the project named. Live-verified: a full run over the existing deployed state is a clean no-op pass; a scratch database created from nothing deploys clean (proven by dropping+redeploying a COPY database, not a live one — never destructive to live data).
2. **Topology gate (suite test):** (a) cross-schema DDL scan — each project's deploy scripts reference no other package's schema; (b) sym read-surface allowlist — every sym relation name found in consumer package sources ⊆ the documented allowlist (the AR-R3 contract, listed in the test with the architecture reference); (c) no consumer imports the sym Python package (data flows over connections only). All three FAIL loudly with the offending file/token named.
3. **DuckDB live-attach finding recorded:** `tools/duckdb_spike.py` (re-runnable; attaches sym+signals+macro read-only, runs the cross-DB join, asserts a write is refused); `duckdb` in the root dev group; architecture revision log + ledger updated with the finding (live attach viable in-env; adoption deferred to its own story).
4. **Suites green** (api gains the gate test; everything else untouched); epic QH.5 → `[BUILT]`; ledger.

## Tasks / Subtasks

- [x] Task 1: `tools/deploy_all.py` + live verification (AC: 1) — registry of 8 (sym/operate irregulars explicit; the root `db/` legacy monolith recorded as deliberately unregistered); `--status`/`--only`; **its first full run caught 12 ROTTEN verify scripts** (sym 11 — stale `asof`/`first_session`/`variant`/IPO-window/dropped-column refs invisible since the renames; operate 1 — the split-out portfolio tables) — all reworked to end-state assertions (the established convention) and 8/8 now deploy+verify clean; from-nothing proven on a scratch DB (created, deployed, verified, dropped — live data untouched)
- [x] Task 2: topology-discipline suite test (AC: 2) — 4 gate tests in the api suite: cross-schema DDL ban (comments stripped), AR-R3 sym read-surface allowlist (case-insensitive over known names), a vocabulary guard making silent contract growth require editing the gate (house-style keywords; peer-schema reads per AR-R2 excluded; CTE-aware), no-sym-imports; vacuous-pass holes closed (empty source/SQL scans assert)
- [x] Task 3: `tools/duckdb_spike.py` + dev dep + records (AC: 3) — re-runnable spike with CORRECTNESS checks (per-factor ranks exactly 1..3, non-null tickers, wrong-reason write failures distinguished); duckdb+psycopg in the root dev group; architecture revision log updated (spike RUN — the env blocker is gone; serving-path adoption stays its own story)
- [x] Task 4: finishers (AC: 4) — api suite 49/49 (45 + 4 gate); epic QH.5 `[BUILT]` + rollup line; ledger section (DuckDB adoption, legacy db/ decision, end-state verify convention, gate limits)

### Review Findings (code review 2026-06-11 — Blind Hunter / combined Auditor+Edge)

- [x] [Review][Patch] Gate regex evasions: uppercase-only FROM/JOIN (no IGNORECASE); test 3's `(?:\s|$)` terminator misses `FROM x"` / `FROM x)` / `FROM x;` (the dominant string shapes); schema-qualified reads (`public.x`, `sym.public.x`) evade BOTH scans — harden all three [test_topology_discipline.py] (HIGH, blind+auditor)
- [x] [Review][Patch] Gate vocabulary: 11 live sym relations missing (incl. index_levels, v_prices_adjusted, corporate_actions) + 1 phantom (universe_snapshot); "every relation" comment overclaims — complete from the live schema, soften the claim, add WITH RECURSIVE to the CTE collector, strip SQL comments in the DDL scan, assert consumer src dirs actually yield files (empty-scan-passes hole) [test_topology_discipline.py] (HIGH, blind+auditor F5)
- [x] [Review][Patch] Deployer: password in docker argv + unencoded in the URI (process-listing exposure; @-containing passwords misparse) → SQITCH_PASSWORD env + password-less target; "Nothing to deploy" rescue scoped to deploy only; --status exits non-zero on missing plans; PGPASSWORD absence named; ensure_database via sql.Identifier [deploy_all.py] (HIGH, blind)
- [x] [Review][Patch] Spike: assert stripped under -O (any error reads as refusal) + join correctness unchecked — explicit refusal check (no assert), per-factor rank 1..3 + non-null ticker validation [duckdb_spike.py] (MED, blind)
- [x] [Review][Patch] fact_returns verify's `>= 18` is vacuous against retirements — pin the core window codes too [verify/fact_returns.sql] (MED, blind)
- [x] [Review][Patch] The 9th plan (auditor F4): root `db/` = the pre-split `qrp` monolith project, DEPLOYED in sym's live sqitch registry (net-nil schema effect) — record as LEGACY in the registry docstring; the delete-or-keep decision ledgered [deploy_all.py, ledger] (MED, auditor)
- [x] [Review][Patch] Ledger section + story record + epic rollup line 383 still says "remaining: QH.5" (auditor F1/F2/F3) — write all [ledger, story, epic] (LOW, auditor)
- [x] [Review][Defer] Rewritten verifies assert END-state names — `sqitch deploy --verify`/`rebase` (per-change verification) would fail mid-plan on a fresh DB. This is the established house convention (Q8.3/Q5.2 verify fixes made the same trade); deploy_all's deploy-then-verify is end-state-consistent. Convention documented; per-change-correct verifies are a rebuild nobody needs yet — deferred, ledgered
- [x] [Review][Defer] Gate scope limits (consumers' .sql DDL covered by test 1, not tests 2-3; services/api excluded as the sym owner's serving surface; lineage reads information_schema only) — stated in the docstring as honest limits — deferred
- [x] [Review][Defer] Generic-name collision class (a consumer's OWN table named like a sym-internal relation would false-positive test 2) — no instance exists; revisit if a consumer ever names a table `universe`/`exchange` — deferred

Dismissed as noise (2): extension-egress only proven on cold envs (the spike's claim is about THIS env's viability, restated in the finding); dynamic `__import__("sym")` evasion (the import gate catches the static forms; dynamic imports are the docstring-admitted limit).

## Dev Notes

- Registry irregulars: sym → `packages/sym/migrations` deploys to db `sym`; operate → `packages/operate/db` deploys to db `qrp` (the plan comment says so). All others: `packages/<pkg>/db` → db `<pkg>`.
- Docker sqitch invocation precedent (every story this week): `MSYS_NO_PATHCONV=1 docker run --rm -v "<abs>\db:/repo" -w /repo sqitch/sqitch <cmd> db:pg://postgres:<pw>@host.docker.internal/<db>`; creds from `.env`.
- Consumer sym read surface (grep-derived, to be verified during dev): fact_returns, fact_index_returns, securities, security_symbology, security_names, universe_membership, fundamentals, return_window, instrument, pipeline_run_log (operate's correlated history). The allowlist is the CONTRACT — additions require touching the gate test deliberately.
- House test style; ruff 100; never destructive to live databases (AC1's scratch-db proof).
- Review-theme pre-emption: the deployer's summary counters must count what they claim; failures attributed per project; docstrings honest about what the gate can't see (raw SQL in strings is scanned by token, not parsed).

### References

- [Source: epics-qrp-roadmap.md — QH.5]
- [Source: architecture-qrp.md — 2026-06-08 DB-per-package revision (DSN registry, DuckDB federation, "base tables accepted")]
- [Source: live probes this session — duckdb extension + ATTACH + READ_ONLY verified]

## Dev Agent Record

### Agent Model Used

claude-fable-5 (Claude Code)

### Debug Log References

- The deploy-all's first full run was its own best test: 12 verify scripts had rotted invisibly (nobody had run `sqitch verify` on sym/qrp since the as_of_date canonicalisation and friends). The renames chain visible in the rot: `asof`→`as_of_date`, `first_session`→`first_session_date`, `floor_reached`→`floor_reached_date`, `date`→`effective_date`→`as_of_date`, variant columns never shipped, the IPO window retired.
- The auditor found a 9th sqitch.plan (root `db/`, the pre-split monolith) deployed in sym's live registry — recorded as deliberately-unregistered legacy, decision ledgered.

### Completion Notes List

- **All 4 ACs met.** One command (`tools/deploy_all.py`) now stands up the entire 8-database topology from nothing (proven on a scratch DB) and verifies it; the AR-R3 "contract = discipline" is enforced by 4 suite tests instead of convention; the DuckDB federation option is live-proven (cross-DB joins correct, writes physically refused) and recorded — adoption deferred deliberately.
- **Review hardening:** gate regexes (case rules split by purpose: case-insensitive allowlist over known names, house-style vocabulary guard — each documented), vocabulary completed from the live schema (11 added, 1 phantom removed), password out of docker argv (SQITCH_PASSWORD env), command-scoped "Nothing to deploy" rescue, identifier-quoted CREATE DATABASE, spike correctness checks replacing a strippable assert, pinned window codes in the fact_returns verify.
- Suites: api 49/49; all sqitch projects verify clean; spike passes.

### File List

- tools/deploy_all.py (new — the DSN registry + one-command deploy/verify)
- tools/duckdb_spike.py (new — re-runnable federation proof)
- services/api/tests/test_topology_discipline.py (new — the AR-R3 gate, 4 tests)
- packages/sym/migrations/verify/{trading_calendar,fact_returns,membership_proposal,universe_accuracy_check,fundamentals,backfill_floor_reached,fundamentals_effective_date,fundamentals_date_column,index_levels,fact_index_returns,cumulative_multiyear_windows}.sql (modified — rot fixes)
- packages/operate/db/verify/qrp_core.sql (modified — rot fix)
- pyproject.toml + uv.lock (modified — root dev group: duckdb, psycopg)
- _bmad-output/planning-artifacts/architecture-qrp.md (modified — spike finding + meta-orchestration record)
- _bmad-output/planning-artifacts/epics-qrp-roadmap.md (modified — QH.5 BUILT + rollup)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — QH.5 section)

## Change Log

- 2026-06-11: Story created (probe-first: the DuckDB env blocker is gone — extension installs, live attach + read-only enforcement verified).
- 2026-06-11: Implemented; the deploy-all's first run surfaced + fixed 12 rotten verifies; review (2 layers): 7 patches (gate regex hardening + vocabulary completion, deployer password/exit-code/scoping hardening, spike correctness, pinned verify codes, legacy-plan record, ledger+record), 3 deferred, 2 dismissed. api 49/49. Status → done.
