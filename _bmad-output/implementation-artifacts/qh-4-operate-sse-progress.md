# Story QH.4: Operate live progress via SSE

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **operator using the QRP console**,
I want **the Operate job panel to stream live job progress over Server-Sent Events instead of re-fetching the whole jobs list every 2 seconds**,
so that **status changes (queued → running → success/failed/orphaned) appear promptly without a steady drip of redundant polling requests, and the panel stays responsive while a long sym op runs**.

## Acceptance Criteria

1. **A new SSE endpoint streams the jobs list.** `GET /api/operate/jobs/stream?limit=N` returns `Content-Type: text/event-stream` and pushes the same payload shape the panel reads today — the `list[Job]` produced by `DbOperateGateway.list(limit)` (so `status` is still **derived from the heartbeat-vs-`pipeline_run_log` machinery**: the `orphaned` CASE in `gateway._COLS` and `_repair_orphans()` are unchanged). `limit` keeps the existing bounds (`ge=1, le=200`, default 50). Each emitted frame is a complete, well-formed SSE event whose `data:` line is the JSON array of jobs.

2. **Updates are pushed, not polled by the client.** The server re-reads the jobs from the DB on a server-side cadence (~1s while any job is `queued`/`running`, slower — ~5s — when all jobs are terminal) and emits an SSE `message` event **only when the serialized payload has changed** since the last emit. This collapses the dual-rate client polling (`2000ms`/`6000ms` in `page.tsx`) into one server-driven stream and removes redundant identical pushes.

3. **The stream is connection-safe and self-terminating.** The endpoint opens its **own** dedicated DB connection (NOT the request-scoped `_gateway` dependency, which closes when the handler returns) and closes it in a `finally`. The generator stops when the client disconnects (detected via `Request.is_disconnected()`), and a periodic keep-alive comment frame (`: keepalive\n\n`, on the same cadence as the heartbeat window or faster) is sent so dead connections are detected and intermediaries don't time the stream out.

4. **Honest failure, not a hung stream.** If the DB connection cannot be established at stream open, the endpoint returns the spec'd **503 error envelope** (`{error:{type:"unavailable",message,detail?}}`, same as `/api/operate/history`) before any streaming begins — never a raw 500 and never a silently empty stream. A DB error encountered **mid-stream** ends the stream cleanly (closes the connection and stops) rather than crashing the worker; the client's reconnect (AC6) re-establishes it.

5. **The endpoint is not blocked by the actuation origin guard.** It is a `GET` (non-mutating), so the `actuation_origin_guard` in `qrp_api/main.py` does not 403 it. The implementation does not introduce any mutating verb for streaming. Same-origin console access through the Next.js `/api/:path*` rewrite proxy works **unbuffered** (the stream is verified to flush incrementally end-to-end through the proxy, not delivered in one buffered blob).

6. **The Operate panel consumes the stream and drops the polling loop.** `apps/web/app/sym/operate/page.tsx` replaces the `setInterval(loadJobs, …)` effect (lines 48–53) with an `EventSource` subscription to `/api/operate/jobs/stream?limit=25` that calls `setJobs(...)` on each message and is torn down (`es.close()`) on unmount. EventSource's built-in auto-reconnect covers transient drops. The one-shot initial `loadJobs()` after a `run()` (line 74) and on mount may remain as a fast first paint, OR be subsumed by the stream's immediate first frame — either is acceptable as long as the panel shows current jobs within ~1s of mount and within ~1s of a status change. A **graceful fallback to the existing `/api/operate/jobs` polling** is used if `EventSource` is unavailable or errors repeatedly, so the panel is never worse than today.

7. **Behavior parity + tests.** The streamed jobs render identically to the polled jobs (same columns, same `orphaned` derivation, same expand-row output/error). New backend tests (DB-free, following the `_Conn` monkeypatch pattern in `packages/operate/tests/test_operate_hardening.py`) assert: (a) the stream yields correctly-framed `text/event-stream` data lines carrying the gateway's job rows; (b) a frame is emitted on change and suppressed when unchanged; (c) a keep-alive comment frame is produced; (d) a failed connect at open yields the 503 envelope; (e) the stream stops on client disconnect. The full operate suite stays green (`uv run pytest` in `packages/operate`).

## Tasks / Subtasks

- [x] **Task 1 — Backend SSE endpoint** (AC: 1,2,3,4,5)
  - [x] Added `GET /api/operate/jobs/stream` to `packages/operate/src/operate/router.py`. `StreamingResponse` with `media_type="text/event-stream"`; headers `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`. Body is the async generator `job_event_stream`.
  - [x] Accepts `request: Request` and `limit: int = Query(default=50, ge=1, le=200)`. **Registered BEFORE `/jobs/{job_id}`** so the literal `stream` segment isn't captured by the int path param (verified by a runtime route-order assert).
  - [x] Dedicated `connect()` (qrp ledger) opened eagerly in the route → `psycopg.OperationalError` raises `HTTPException(503, "job ledger unreachable: …")` before streaming (mirrors `pipeline_history`); the generator closes the conn in `finally`.
  - [x] Loop: `await request.is_disconnected()` → break; jobs read via `gw.list(limit)` through `starlette.concurrency.run_in_threadpool` (sync psycopg off the event loop); emits `data: <json>\n\n` only on change, `: keepalive\n\n` otherwise; `await asyncio.sleep(_STREAM_ACTIVE_S=1.0 / _STREAM_IDLE_S=5.0)` keyed on whether any job is `queued`/`running`.
  - [x] Mid-stream `psycopg.Error` breaks the loop cleanly (conn still closed); no 500 escapes — the client's EventSource reconnects.
- [x] **Task 2 — Frontend EventSource subscription** (AC: 6,7)
  - [x] Replaced the polling `useEffect` in `apps/web/app/sym/operate/page.tsx` with an `EventSource("/api/operate/jobs/stream?limit=25")` effect that parses `event.data` as `Job[]` → `setJobs`, and tears down with `es.close()`.
  - [x] `onerror` fallback: only when `es.readyState === EventSource.CLOSED` (dead, not the auto-reconnecting CONNECTING state) does it start a 3s `loadJobs` poll — so the panel is never worse than before. Also falls back if `EventSource` is undefined.
  - [x] Kept mount-time `loadJobs()` and post-`run()` `loadJobs()` for instant first paint; the stream's immediate first frame supersedes them.
  - [x] Reviewed `apps/web/AGENTS.md` — `EventSource` is a browser global (no Next API), change is confined to client React. The `/api/:path*` rewrite (`next.config.ts`) passes the stream through; `X-Accel-Buffering: no` + `Cache-Control: no-cache` set to defeat proxy buffering (live console verification is the operator's manual step below).
- [x] **Task 3 — Tests** (AC: 7)
  - [x] New `packages/operate/tests/test_operate_sse.py` (DB-free): drives `job_event_stream` via `asyncio.run` with a fake `Request` that flips `is_disconnected` after N polls. Asserts (a) well-formed `data:` framing carrying gateway rows, (b) change → new data frame, (c) unchanged → keepalive (no duplicate), (d) 503 on connect failure at open, (e) disconnect stops + closes conn, plus mid-stream-error degrade and normal-drain close. Cadence monkeypatched to 0 (no real waiting). 7 tests.
  - [x] `uv run pytest` green in `packages/operate` (21 passed); `services/api` suite incl. `test_topology_discipline.py` green (56 passed).
- [x] **Task 4 — Wiring + docs + verification** (AC: 1,5,6)
  - [x] No DB migration (reuses `qrp.job` + heartbeat). No type regen needed — `Job` schema unchanged and the SSE route is consumed via raw `EventSource`, not the typed client; `lib/api-types.ts` untouched (no drift). Confirmed the full gateway app mounts the route (`QRP_ENABLED_MODULES=sym`, all 6 operate routes present, stream precedes `{job_id}`).
  - [ ] **Manual end-to-end (operator step):** with API + console running, open `/sym/operate`, trigger a writer op, and confirm in the Network tab one long-lived `text/event-stream` request (no repeating `/jobs` polls) with the row updating live, and `orphaned` still appearing for a stale-heartbeat job. *(Requires a live DB + dev servers — left for operator/code-review verification per the Verification section.)*
  - [x] Updated the QH epic build-status line for QH.4 to `[BUILT 2026-06-15]`.

## Senior Developer Review (AI)

**Reviewed:** 2026-06-15 · **Outcome:** Approve (2 findings patched, 2 deferred, 5 dismissed) ·
**Layers:** Blind Hunter + Edge Case Hunter + Acceptance Auditor (all 3 ran). Acceptance
Auditor confirmed all 7 ACs satisfied.

### Review Findings

- [x] [Review][Patch] Connection lifetime split across the route/generator boundary (flagged **High** by Blind+Edge) `[packages/operate/src/operate/router.py]` — **Fixed.** The conn was opened in `stream_jobs` but closed only in the generator's `finally`; if the `StreamingResponse` were returned but never iterated (cancellation between route-return and first `__anext__`), the `finally` never runs → leak. Starlette was verified to close the generator on mid-stream disconnect (so the normal path was already safe), but the never-iterated window was real. The generator now opens AND closes its own connection inside its `try/finally`; a cheap pre-flight `connect().close()` in `stream_jobs` preserves the AC4 503-at-open. +1 test (`test_preflight_returns_stream_and_drops_its_probe_connection`).
- [x] [Review][Patch] Dead `_STALE_S` import (Blind+Edge, Low) `[packages/operate/src/operate/router.py:23]` — **Fixed.** Imported but unused (cadence uses the literals `_STREAM_ACTIVE_S`/`_STREAM_IDLE_S`); removed. `ruff check` clean.
- [x] [Review][Defer] Per-tick `_repair_orphans` write + one threadpool worker per active stream (Edge, Med) — **Deferred:** matches the pre-existing `/jobs` polling (which also ran `_repair_orphans` every poll); AC1 mandates reusing `list()` verbatim; owner-operated → low concurrency. A read-only stream path and a concurrent-stream cap are the future hardening if multi-console use ever lands.
- [x] [Review][Defer] Up to ~5s post-disconnect linger (disconnect is checked once at loop top, then the idle sleep runs) (Edge, Med) — **Deferred:** a departed client holds the conn + thread for at most one idle interval; acceptable for this context. A mid-sleep disconnect re-check or a shorter idle cap is the fix if it ever matters.
- Dismissed (5, verified handled / by design): `orphaned`→idle-cadence (counting `orphaned` as active would pin the 1s cadence **forever** since it's a lingering state — current behavior is correct); `json.dumps` change-detection (deterministic key order — `_row` builds fixed-order dicts); heartbeat-driven ~10s repaint of a running job (intended, keeps the cursor warm, within AC2's letter); frontend one-way degrade to polling (by design); React StrictMode double-mount (dev-only, benign).

## Dev Notes

### Current state of files being modified

- **`apps/web/app/sym/operate/page.tsx`** (UPDATE) — `"use client"` component. Today it polls: `loadJobs` (lines 29–34) GETs `/api/operate/jobs?limit=25` with `{cache:"no-store"}` and `setJobs`; an effect (lines 48–53) runs `setInterval(loadJobs, active ? 2000 : 6000)` where `active = jobs.some(j => j.status === "queued" || "running")`. `run()` (55–75) POSTs `/api/operate/run`, reads the `{error:{type,message}}` envelope (O.4) with a `.catch(()=>({}))` degrade, then `loadJobs()`. The table renders `jobs` with `STATUS_STYLE` per status and an expandable output/error row. **Preserve:** the trigger flow, the error-envelope read, `STATUS_STYLE` (note: there is no style entry for `orphaned` today → it falls through to `text-fg`; out of scope to add, but harmless to include).
- **`packages/operate/src/operate/router.py`** (UPDATE) — prefix `/api/operate`. `_gateway()` dependency opens `connect()` (qrp DB) and **closes it on handler return** — unusable for a long-lived stream, hence the dedicated connection in Task 1. `list_jobs` (82–86) is the polled handler the stream supersedes. `pipeline_history` (97–111) is the template for honest 503 degradation (`connect("sym")` in try/except → `HTTPException(503)`, `finally: conn.close()`). Models `Job`, `RunResult`, etc. are here.
- **`packages/operate/src/operate/gateway.py`** (READ, do not change) — `DbOperateGateway.list(limit)` calls `_repair_orphans()` then `SELECT {_COLS} … ORDER BY created_at DESC LIMIT %s`. `_COLS` contains the `CASE … heartbeat_at < now() - interval '30 seconds' THEN 'orphaned'` derivation. **The stream reuses `list()` verbatim** — that is what keeps AC1's "status still derived from `pipeline_run_log` + heartbeat" true without re-deriving anything.
- **`packages/operate/src/operate/executor.py`** (READ) — the supervisor stamps `heartbeat_at = now()` every ~10s (`_BEAT_S`) during a run; `_STALE_S = 30s` is the orphan window. The stream does not touch execution; it only reads the resulting rows faster.
- **`services/api/src/qrp_api/main.py`** (READ) — `actuation_origin_guard` middleware 403s **mutating** methods (POST/PUT/PATCH/DELETE) carrying a foreign Origin; a `GET` stream is unaffected. Global exception handlers translate `HTTPException`/validation/unhandled into the `{error:{type,message,detail?}}` envelope — the 503 raised at stream open flows through these. Operate router is mounted only when `"sym" in enabled` (lines ~248).

### Key constraints

- **`text/event-stream` framing:** events are `data: <payload>\n\n`; comments/keep-alives are `: <text>\n\n`. Multi-line data needs a `data:` prefix per line — keep the JSON single-line to avoid this.
- **Sync psycopg under async:** the gateway is synchronous. In an async generator, run the DB read off the loop (`anyio.to_thread.run_sync` / `starlette.concurrency.run_in_threadpool`) so a slow query can't block other requests. Do **not** convert the gateway to async (out of scope, and the threadpool path is the established FastAPI idiom).
- **Connection lifecycle:** one psycopg connection lives for the whole stream — must be explicitly closed on disconnect/error/normal-exit. Do not leak; do not reuse `_gateway`.
- **Proxy buffering:** the console reaches the API via the Next.js rewrite (`/api/:path* → ${API}/api/:path*`, `next.config.ts`). SSE must flush incrementally through it. Set `X-Accel-Buffering: no` + `Cache-Control: no-cache`; verify in the Network tab that the request stays open and frames arrive incrementally.
- **Change-detection:** compare the serialized payload (or a cheap hash) to the last emitted one; emit only on change to avoid spamming identical arrays. Always send a keep-alive on the idle path so the connection is proven live.
- **Cadence honesty:** ~1s active / ~5s idle is the server analogue of today's 2s/6s. Don't go below ~1s — the DB read + orphan-repair runs each tick.
- **Next.js is non-standard here:** `apps/web/AGENTS.md` mandates reading `node_modules/next/dist/docs/` before writing console code — EventSource is browser-native (no Next API), but verify nothing in the App Router / proxy layer interferes.

### Project Structure Notes

- New endpoint lives in the existing operate router (`packages/operate/src/operate/router.py`) — no new module, no new package, no DB migration. The job ledger (`qrp.job` + `heartbeat_at`) already carries everything the stream needs.
- Frontend change is confined to one client component (`page.tsx`). No new shared lib needed; EventSource is a browser global.
- Tests extend the existing operate test module (DB-free, `_Conn` monkeypatch). The suite runs via `uv run pytest` in `packages/operate`.
- This is the FR-8 "nice-to-have" deferred in v1; it changes transport only, not the data contract or the system of record (sym's run logs remain authoritative).

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md#Story QH.4 — Operate live progress via SSE] — "the Operate job panel streams via SSE instead of 2s polling; status still derived from `pipeline_run_log` + heartbeat. (FR-8 nice-to-have, deferred in v1.)"
- [Source: apps/web/app/sym/operate/page.tsx#L29-L75] — current poll loop, `loadJobs`, `run()`, error-envelope read.
- [Source: packages/operate/src/operate/router.py#L82-L111] — `list_jobs` (polled handler) + `pipeline_history` (503-degradation template).
- [Source: packages/operate/src/operate/gateway.py#_COLS / list / _repair_orphans] — the heartbeat→`orphaned` derivation the stream reuses unchanged.
- [Source: packages/operate/src/operate/executor.py#L28-L33,L194-L224] — `_BEAT_S`=10s heartbeat, `_STALE_S`=30s orphan window.
- [Source: services/api/src/qrp_api/main.py#actuation_origin_guard, _error_body] — GET is unguarded; the 503 envelope shape.
- [Source: apps/web/next.config.ts#rewrites] — `/api/:path*` same-origin proxy (buffering caveat).
- [Source: apps/web/AGENTS.md] — read `node_modules/next/dist/docs/` before console edits.
- [Source: packages/operate/tests/test_operate_hardening.py] — DB-free `_Conn` monkeypatch test pattern to follow.
- [Source: _bmad-output/implementation-artifacts/qh-3-readonly-db-role.md] — most recent QH story, format reference.

### Verification (end-to-end)

1. Start the API (`uv run` the qrp_api app on :8001) and the console (`npm --workspace web run dev` on :3000).
2. Open `/sym/operate`. In the browser Network tab, confirm a single long-lived `jobs/stream` request with `Content-Type: text/event-stream` that stays **pending/open** — and that the repeating `/api/operate/jobs?limit=25` polls are **gone**.
3. Trigger a writer op (e.g. a guarded `validate`/`load_fill` with `confirm`). Watch the row go `queued → running → success/failed` live, updating within ~1s, with no client-side interval firing.
4. Confirm frames are incremental (not one buffered blob at the end) — the row updates while the op is still running.
5. Stale-heartbeat path: simulate/await a `running` job whose heartbeat ages past 30s and confirm it flips to `orphaned` in the stream (same derivation as the polled path).
6. Kill the API mid-stream; confirm the panel falls back to polling (or EventSource reconnects when the API returns) and never throws.
7. Backend: `uv run pytest` green in `packages/operate`; new SSE tests pass.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- `uv run pytest -q` in `packages/operate` → 21 passed (14 existing + 7 new SSE).
- `QRP_ENABLED_MODULES=sym uv run pytest -q` in `services/api` → 56 passed (incl. `test_topology_discipline.py`).
- Runtime route-order assert: `/api/operate/jobs/stream` registered before `/api/operate/jobs/{job_id}`.
- Full gateway import smoke (`qrp_api.main`) → all 6 operate routes mounted, app imports OK.
- `StreamingResponse` wiring asserted directly: `media_type=text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.
- `npx tsc --noEmit` + `npx eslint app/sym/operate/page.tsx` → clean (no errors in the touched file).

### Completion Notes List

- **Transport-only change.** No DB migration, no data-contract change, no new dependency. The stream reuses `DbOperateGateway.list()` verbatim, so the heartbeat-derived `orphaned` status and `_repair_orphans()` read-repair are unchanged — the AC's "status still derived from heartbeat/`pipeline_run_log`" holds because the source view is identical to the polled `/jobs`.
- **Route ordering was the one real trap:** `/jobs/{job_id}` (`job_id: int`) would 422 on `/jobs/stream` if declared first. The stream route is declared before it; guarded by a runtime assert in dev verification.
- **503 is raised at the route (before streaming), not inside the generator** — so an unreachable ledger degrades to the honest envelope through the global handlers, exactly like `pipeline_history`. A *mid-stream* DB error instead ends the stream cleanly (EventSource reconnects).
- **Frontend fallback is CLOSED-gated:** EventSource auto-reconnects while CONNECTING; only a truly dead (CLOSED) stream — e.g. the 503 handshake — triggers the 3s polling fallback, so the panel is never worse than the pre-SSE behavior.
- **TestClient note:** a full ASGI streaming smoke via Starlette `TestClient` hangs on teardown (the infinite generator never receives a disconnect under TestClient). Covered instead by driving `job_event_stream` directly with `asyncio.run` (bounded by a fake `Request`) + asserting the `StreamingResponse` headers directly. Live end-to-end is the operator step.
- **Deferred (not blocking):** live console/Network-tab verification through the real dev proxy (needs DB + servers up); a unit-aware fallback-cadence knob; the `orphaned` `STATUS_STYLE` entry (pre-existing gap, falls through to `text-fg`) — out of scope.

### File List

- `packages/operate/src/operate/router.py` (UPDATE) — `job_event_stream` async generator + `GET /jobs/stream` route; module docstring + cadence constants `_STREAM_ACTIVE_S`/`_STREAM_IDLE_S`; imports (`asyncio`, `json`, `Request`, `StreamingResponse`, `run_in_threadpool`, `_STALE_S`).
- `packages/operate/tests/test_operate_sse.py` (NEW) — 7 DB-free tests driving the generator + the 503-on-open path.
- `apps/web/app/sym/operate/page.tsx` (UPDATE) — replaced the 2s/6s polling `useEffect` with an `EventSource` subscription + CLOSED-gated polling fallback.
- `_bmad-output/planning-artifacts/epics-qrp-roadmap.md` (UPDATE) — QH.4 marked `[BUILT 2026-06-15]`.

### Change Log

- 2026-06-15 — Implemented QH.4: Operate job panel streams live via SSE (`/api/operate/jobs/stream`) replacing 2s client polling; server pushes on change with keepalives, honest 503 at open, client fallback to polling. Status → review.
- 2026-06-15 — Code review (3 adversarial layers). Patched 2 findings: the SSE generator now owns its own ledger connection inside its `try/finally` (was split across the route boundary — a never-iterated `StreamingResponse` could leak it), with a pre-flight `connect().close()` preserving the 503-at-open; removed the dead `_STALE_S` import. 2 findings deferred (per-tick repair-write/threadpool, ≤5s disconnect linger — both match pre-existing polling, owner-operated), 5 dismissed. operate 22/22 + api 56/56 green, ruff clean. Status → done.
