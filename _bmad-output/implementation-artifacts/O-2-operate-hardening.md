# Story O.2: Operate hardening — heartbeat, provenance, history, allowlist (chunk-1 D2)

Status: done

## Story

As Andre (the operator),
I want Operate jobs to heartbeat while running (so a dead process is visible, not a forever-"running" row), every sym run to carry WHO triggered it, the FR-6 run-history surface to exist, and the op allowlist to cover the operations I actually run,
so that the Operate module graduates from v1 demo depth to the operational backbone the spec described.

## Background (why this story exists)

Chunk-1 review (2026-06-10), ledger **D2 (Operate architecture)**. Investigation findings that sharpen the ledger text:

1. **ADR-1 is NOT contradicted** — `architecture-qrp.md:335` already records "sym ops run OUT of the web process… subprocess fallback if the sym import-boundary probe fails". Subprocess-everything is the fallback arm, chosen and shipped; what's missing is the one-line finalization ("mechanism finalized" note still says *pending the Q3.1 spike*). Task: record the finalization + scope library-first to data-access gateways. No reversal needed.
2. **Heartbeat:** `executor._run_job` blocks in `subprocess.run(timeout=1800)` — `qrp.job` has no `heartbeat_at`, so a killed API process leaves `running` rows forever (the busy-check staleness window covers only `queued`). ADR-5 explicitly promised "a QRP job heartbeat".
3. **Provenance:** sym's `pipeline_run_log` has no `triggered_by`; a qrp job and the sym run it caused are uncorrelatable.
4. **Allowlist:** 4 ops (validate, universe_monitor, universe_refresh, recompute); the daily reality is `eod`, `fx load`, `load` (fill), `universe accuracy`/`review` — absent.
5. **FR-6 run-history endpoint:** missing entirely (v1 spec item) — the console can't show what the pipeline has been doing.
6. **Lock granularity:** spec said per Operation; built per op+args. Per op+args is the better behavior (two universes can monitor concurrently) — record the deviation, don't change the code. ADR-2's residual risk (sym's own scheduled runs don't take the lock) stays documented.

## Acceptance Criteria

1. **Heartbeat:** `qrp.job` gains `heartbeat_at` (qrp sqitch migration); the executor supervises via `Popen` + poll loop, stamping `heartbeat_at` every ~10s while the child runs; timeout semantics preserved (kill + `failed` at 1800s).
2. **Orphan reconciliation:** a `running` job whose `heartbeat_at` is older than a stale window (3× the beat) is surfaced as `orphaned` by the job-listing/busy logic (read-time reclassification — no reaper daemon), and no longer blocks the advisory-lock path (the lock died with its process — document that Postgres frees advisory locks on disconnect, which is why read-time reclassification is sufficient).
3. **Provenance:** sym's `pipeline_run_log` gains `triggered_by TEXT` (sym sqitch migration, Docker flow); `write_run_log` populates it from the `SYM_TRIGGERED_BY` env var (NULL when unset — manual CLI runs); the executor sets `SYM_TRIGGERED_BY=qrp-job:<job_id>` on the child env. Correlation is queryable: job → runs it caused.
4. **Allowlist widened:** `eod` (writes, confirm), `fx_load` (writes, confirm), `load_fill` (writes, confirm, takes scope arg), `universe_accuracy` (read, takes universe), `universe_review` (read). Existing arg-validation/flag-injection guards apply to all.
5. **FR-6 history endpoint:** `GET /api/operate/history?limit=N` returns sym's recent `pipeline_run_log` rows (run_id, mode, source, started/finished, counts, status, triggered_by) — read-only against the sym DB via the same env-config pattern the sym module uses.
6. **ADR text finalized:** architecture-qrp.md ADR-1 note updated (subprocess arm chosen; library-first = data-access gateways); ADR-2 deviation recorded (lock per op+args, deliberately finer than spec).
7. **Tests + live:** DB-free tests for heartbeat stamping, orphan classification, env propagation, new op definitions, history gateway; live — run a real allowlisted op through Operate, observe heartbeats and the `triggered_by` correlation, history endpoint returns rows. Ledger D2 marked done.

## Tasks / Subtasks

- [x] Task 1: Schema (AC: 1, 3) — both migrations written (deploy/revert/verify) and registered via the Docker sqitch flow (qrp_core `job_heartbeat`, sym `pipeline_run_log_triggered_by`); DDL applied
- [x] Task 2: Executor heartbeat (AC: 1, 2) — Popen + side-thread output drain (an unread PIPE deadlocks a chatty child) + beat every 10s; gateway `_COLS` reclassifies stale-running as `orphaned` at read time; busy-check requires a FRESH beat for running rows (30s vs the old 2h wedge); advisory-lock-dies-with-connection reasoning documented
- [x] Task 3: Provenance (AC: 3) — `SYM_TRIGGERED_BY=qrp-job:<id>` on the child env; `_write_run_log` stamps it (NULL for manual runs)
- [x] Task 4: Allowlist + history endpoint (AC: 4, 5) — 4 → 9 ops; `takes_scope` validation (`universe:<id>` only); `GET /api/operate/history` (503 when sym DB unreachable)
- [x] Task 5: ADR finalization + ledger (AC: 6) — ADR-1 finalized (subprocess for execution; library-first = data access), ADR-2 per-(op+args) deviation recorded
- [x] Task 6: Tests + live verification (AC: 7) — 8 operate tests (new package test dir) + 1 sym provenance test; live: 9 ops listed, `universe_review` job heartbeat→success, `load_fill universe:ibov` job 4 → sym run 35 `triggered_by=qrp-job:4` via the history endpoint, scope guard rejects bad args (422)

## Dev Notes

### Wiring map

| File | Current | Change |
|---|---|---|
| `db/deploy/jobs.sql` (qrp sqitch) | no heartbeat | new migration `job_heartbeat` |
| `packages/sym/migrations/` | `pipeline_run_log` 13 cols | new migration `pipeline_run_log_triggered_by` |
| `packages/operate/src/operate/executor.py` | `subprocess.run` blocking; 4 ops | Popen+poll+beat; env injection; widened OPS |
| `packages/operate/src/operate/gateway.py` | `_row` maps 10 cols; busy via status | heartbeat col; orphaned classification |
| `packages/operate/src/operate/router.py` | ops/jobs/run | `GET /history` |
| `packages/sym/src/sym/ingest/pipeline.py::write_run_log` | 13-col INSERT | + triggered_by from env |
| `_bmad-output/planning-artifacts/architecture-qrp.md` | ADR-1 "finalized by spike" | finalization note + ADR-2 deviation |

### Constraints

1. **Operate never touches sym's schema from code** — the sym column arrives via sym's own sqitch migration; sym's writer populates it. The env var is the only coupling.
2. **`as_of_date` canonical naming**; env var named `SYM_TRIGGERED_BY` (provenance, not a date).
3. **Migrations via the Docker sqitch flow** (no local sqitch; `host.docker.internal`) — both targets (`db/sqitch.plan` for qrp, `packages/sym/migrations` for sym). Verify scripts included.
4. **No reaper daemon** — orphan detection is read-time classification (single-operator; the lock dies with the process).
5. **History endpoint is read-only** and must not crash when the sym DB is unreachable (degrade to 503 with a clear message, matching module conventions).
6. **Timeout/kill semantics preserved**: poll loop must kill the child at 1800s and record the same failure message.
7. **The api server is RUNNING (ports 8001/3000)** — restart it after operate/router changes to live-test (uvicorn runs without --reload per README).

### Previous-story intelligence

- Chunk-1 in-review patches (stable hashlib lock key, stale-queued window, thread-death guard) are in place — don't regress them.
- The chunk-5 ledger item "run-log row written up-front (status='running')" pairs with this but is sym-side pipeline redesign — NOT in scope; heartbeat_at on qrp.job covers the operator-visibility need from the Operate side.
- Suite baseline 530 (sym) — operate package tests live where? (check `packages/operate/tests` — may be none; the api module tests live under services/api). Add operate tests in the operate package.
- Lint baseline 18 (sym package); operate/qrp lint posture — check before committing.

### References

- [Source: _bmad-output/planning-artifacts/architecture-qrp.md §API & Communication Patterns — ADR-1/2/5]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-1 D2]
- [Source: db/deploy/jobs.sql; packages/operate/src/operate/*.py; packages/sym/src/sym/ingest/pipeline.py]

### Review Findings (code review 2026-06-10, commit 7b4a282 — ALL RESOLVED)

- [x] [Review][Patch] [HIGH] `_kill_tree` (taskkill /T /F on Windows) on the timeout path AND on executor-fatal exit — the sym grandchild no longer survives its job row; orphaned ≠ work stopped documented in the gateway comment + repair error text [executor.py, gateway.py]
- [x] [Review][Patch] Beats are best-effort (`except psycopg.Error: pass`) — a DB hiccup no longer abandons a healthy child (tested with a flaky conn) [executor.py]
- [x] [Review][Patch] Timeout path: `_kill_tree` guards `wait`'s `TimeoutExpired` (the real failure message always lands — constraint 6); the failed row now persists the output tail; reader joined via the shared `_tail()` helper [executor.py]
- [x] [Review][Patch] Drain pinned to `encoding='utf-8', errors='replace'` (the cp1252 deadlock vector — asserted in tests) + `[output truncated]` marker when the reader outlives the join [executor.py]
- [x] [Review][Patch] Beats stamped with server `now()` in SQL; the stale window is `_STALE_S = 3 × _BEAT_S`, interpolated into both gateway predicates — one knob (tested) [executor.py, gateway.py]
- [x] [Review][Patch] Orphan read-repair: list/get persist `status='orphaned'` + `finished_at` + the caveat message — verified LIVE (manufactured dead-running job 5: API read `orphaned`, STORED row converged to `('orphaned', finalized)`, cleaned) [gateway.py]
- [x] [Review][Patch] `/history` catches `psycopg.Error` mid-query → 503 "run log unavailable" (tested with `UndefinedColumn`) [router.py]
- [x] [Review][Patch] Arg symmetry: no-arg ops reject extras; `takes_universe` requires exactly one id (tested) [gateway.py]
- [x] [Review][Patch] Record corrections: constraint 3's `db/sqitch.plan` reference was stale — `qrp.job` lives in project `qrp_core` (`packages/operate/db/`) since `relocate_qrp`; the implementation deviated correctly. Timeout fires up to one beat (~10s) after the 1800s deadline (poll granularity) — accepted slack [this section]
- Dismissed (5): heartbeat-uncommitted (false positive — `conn.autocommit = True` at `_run_job` top, outside the blind layer's hunk); child env scoping (localhost; children need PG*/PATH + load .env); scope-regex alphabet (operator-created lowercase slugs); `RunHistoryRow` nullability (columns are NOT NULL in schema); pre-migration-DB gate (both registered, single environment).
- Dismissed (5): "beats may be uncommitted" (false positive — `conn.autocommit = True` at the top of `_run_job`, outside the diff hunk); child env scoping (localhost single-operator; children need PG*/PATH and load .env themselves); scope-regex alphabet (universe ids are operator-created lowercase slugs by convention); `RunHistoryRow` nullability (schema declares those columns NOT NULL); pre-migration-DB compat gate (both migrations registered; single environment).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code.

### Debug Log References

- Docker daemon was down at first deploy — DDL applied directly (idempotent `IF NOT EXISTS`), sqitch registered both changes once Docker came up (NOTICE skip = already-applied, registry rows written).

### Completion Notes List

- **ADR-1 finalization (investigation correction):** the ledger framed this as "reconcile subprocess vs library-first ADR-1" — but architecture-qrp.md:335 already mandated out-of-process execution with subprocess as the fallback arm; the only gap was the "finalized by the Q3.1 spike" placeholder. Recorded: subprocess is the chosen mechanism for op EXECUTION (isolation, the tested CLI as contract, timeout, output capture); library-first governs data-ACCESS gateways. No reversal existed.
- **Heartbeat design:** Popen + poll-loop beats every 10s; output drained on a side thread (unread PIPE deadlock); timeout semantics preserved (kill + same failure message at 1800s). Orphan = read-time CASE reclassification at 3× the beat; no reaper needed because Postgres frees advisory locks on disconnect — the dead run's lock is already gone. The busy-check now unwedges dead running rows in 30s (was a 2h blanket window; queued rows keep 2h for the launch-thread-never-started case).
- **Provenance:** the only Operate↔sym coupling is the env var. sym's column arrived via sym's own migration; sym's writer stamps it. Verified live end-to-end: `qrp.job` 4 ↔ `pipeline_run_log` 35.
- **Allowlist:** eod / fx_load / load_fill (scope-validated `universe:<id>` — the CLI accepts more scopes; the API stays narrow) / universe_review / universe_accuracy. Flag-injection guard applies to all.
- Out of scope (already on the ledger): the chunk-5 "run-log row written up-front" sym-side redesign; API CSRF hardening (chunk-1 D4); error envelope (D6).

### File List

- packages/operate/db/{deploy,revert,verify}/job_heartbeat.sql + sqitch.plan (new migration)
- packages/sym/migrations/{deploy,revert,verify}/pipeline_run_log_triggered_by.sql + sqitch.plan (new migration)
- packages/operate/src/operate/executor.py (modified — Popen+beat, env, 5 new ops, takes_scope)
- packages/operate/src/operate/gateway.py (modified — orphan CASE, busy-check, scope validation, run_history)
- packages/operate/src/operate/router.py (modified — heartbeat_at + /history)
- packages/sym/src/sym/ingest/pipeline.py (modified — triggered_by stamp)
- packages/operate/tests/test_operate_hardening.py (new — 8 tests)
- packages/sym/tests/test_pipeline.py (modified — provenance test)
- _bmad-output/planning-artifacts/architecture-qrp.md (modified — ADR-1 finalized, ADR-2 deviation)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — chunk-1 D2 done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-6); sym suite 530 → 531, operate suite 0 → 8, all green; live end-to-end verified (heartbeats, orphan logic, qrp-job↔run-log correlation, history endpoint, scope guard). Status → review.
- 2026-06-10: Code review (3 adversarial layers; Auditor independently reproduced EVERY live claim — registries, correlation, endpoint — and passed all 7 ACs/constraints) — 9 patches applied (HIGH: process-TREE kill so the sym grandchild can't outlive its job row; best-effort beats; utf-8 drain pinning; server-time stamps; orphan read-repair verified live on a manufactured dead row), 0 deferred, 5 dismissed (1 blind false-positive on autocommit). Operate suite 8 → 14. Status → done.
