# Story O.3: Actuation origin guard (chunk-1 D4, guard half)

Status: done

## Story

As Andre (the operator),
I want every state-changing API request to be refused unless it comes from my own console (or a headless script),
so that a malicious web page open in the same browser can't drive-by actuate localhost endpoints — run ops, create portfolios, kick backtests — using my ambient network position.

## Background + scope decision

Chunk-1 review (2026-06-10), ledger **D4 (API hardening)**: same-origin/CSRF guard on actuation endpoints + move backtest/optimiser engine execution out of request handlers. Investigation:

1. **The CSRF residue is narrower than the ledger feared but real:** JSON bodies force a CORS preflight, so classic cross-site POSTs are blocked by the existing `CORSMiddleware` allowlist — but that protection is incidental (one content-type change, one future form endpoint, or a CORS misconfiguration away from gone). The recorded ask — an explicit origin check on mutating methods — is defense-in-depth that costs ~30 lines.
2. **Engine relocation is RE-DEFERRED with its real dependency named:** moving `backtest/run` + `optimiser/solve` into Operate-style jobs changes the API contract (synchronous result → job_id + polling), which requires console (Next.js) changes — full-stack work that pairs with the decided qrp/packages restructure. The O.2 executor gives it a hardened home when it lands. Ledger entry updated, not silently dropped.
3. **Six mutating endpoints exist today** (backtest/run, operate/run, optimiser/solve, portfolios ×3) across per-module routers — the guard must be a `main.py` middleware so every CURRENT and FUTURE mutating route is covered without per-module opt-in.

## Acceptance Criteria

1. **Origin guard middleware** in `qrp_api.main`: for POST/PUT/PATCH/DELETE, a request carrying an `Origin` header NOT in the allowed set is refused with 403 and a clear message; the allowed set = the CORS origins (localhost/127.0.0.1 :3000) and is defined ONCE (shared constant with the CORS config).
2. **Headless clients keep working:** requests WITHOUT an Origin header (curl, scripts, schedulers) pass — the guard targets browser-ambient CSRF, not API access.
3. **Reads unaffected:** GET/HEAD/OPTIONS never blocked (OPTIONS must pass for the CORS preflight itself).
4. **Coverage is structural:** the middleware applies app-wide — verified against a representative mutating route from a module router (not just a main.py route).
5. **Tests:** the api service gains its first test file (TestClient): cross-origin POST → 403; allowed-origin POST passes the guard (reaches the route); no-Origin POST passes; GET with foreign Origin passes; OPTIONS preflight passes.
6. **Live verification:** against the running API — a forged-Origin POST to `/api/operate/run` → 403; the console (allowed origin) still actuates; a no-Origin curl POST still works.
7. **Ledger:** D4 split recorded — guard DONE; engine relocation re-deferred with the console-contract dependency named.

## Tasks / Subtasks

- [x] Task 1: Middleware + shared origin constant (AC: 1-4) — `ALLOWED_ORIGINS` shared by CORS + guard; `actuation_origin_guard` http middleware (mutating + foreign Origin → 403 before route logic)
- [x] Task 2: Tests — services/api/tests created (first api test file; 6 tests via TestClient; added `httpx2` as a dev dependency — TestClient's transitive requirement)
- [x] Task 3: Live verification + ledger (AC: 6, 7) — forged-Origin POST 403; console-origin POST reaches the route (422 unknown-op = past the guard); headless curl passes; reads unaffected; D4 split recorded on the ledger

## Dev Notes

### Constraints

1. **Deny-on-foreign-Origin, allow-on-absent** — the standard localhost-tool posture: browsers attach Origin to every cross-site (and same-site POST) request; scripts don't. Do NOT require a CSRF token (no session/auth exists to bind one to — single-operator localhost).
2. **One origin list.** The CORS middleware and the guard must read the same constant; drift between them recreates the misconfiguration class this story closes.
3. **403, not 422/409** — this is a refusal of the CALLER, not the payload; body: the module convention `{"detail": ...}`.
4. **Don't break the preflight:** OPTIONS passes untouched or CORS dies.
5. The api service has NO tests today — create `services/api/tests/`; fastapi TestClient + the real `create_app()` with module routers feature-toggled as configured (DB-dependent routes are fine to 4xx/5xx past the guard — assertions target the guard layer, with a mutating route that fails AFTER the 403 check would have fired).

### Previous-story intelligence

- O.2 just touched operate/router; the services run live on ports 8001/3000 — restart after the middleware lands (no --reload).
- Suites: sym 531, operate 14; lint baselines clean for new files.

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-1 D4]
- [Source: services/api/src/qrp_api/main.py — CORS config, create_app]

### Review Findings (code review 2026-06-10, commit 1904f91 — ALL RESOLVED)

- [x] [Review][Patch] `TrustedHostMiddleware` added (localhost/127.0.0.1/testserver) — the DNS-rebinding companion; verified live (rebound Host → 400) and in tests [main.py]
- [x] [Review][Patch] Test suite 6 → 13: PUT/PATCH/DELETE parametrized; `Origin: null` denied-by-design; empty-string fail-closed; pre-routing 403 on a nonexistent path (the REAL structural property); pass-tests assert the deterministic 422; fixture client [tests]
- [x] [Review][Patch] All four secure-by-accident decisions documented in the guard docstring (null-Origin, empty-string, no Referer fallback, http-scope-only/WS caveat) + the load-bearing registration-order comment at the middleware site [main.py]
- [x] [Review][Patch] `ALLOWED_ORIGINS` is an immutable tuple, env-overridable via `QRP_ALLOWED_ORIGINS` (the Next-bumps-to-:3001 lockout has a recourse) [main.py]
- [x] [Review][Patch] 403 echo truncated to 100 chars (attacker-controlled input); tested [main.py]
- [x] [Review][Patch] `httpx2` relocated to `services/api/pyproject.toml`'s own dev group per the workspace convention (a mid-sync collision with the running API stripped the venv — recovered with a full `uv sync --all-packages --all-groups` after stopping services) [pyproject]
- [x] [Review][Patch] Ledger blank line removed [deferred-work.md]
- Dismissed (5): `httpx2`-typosquat claim (FALSE POSITIVE — verified live: starlette 1.2.1's TestClient error names `httpx2`; it is the successor package, locked from PyPI, `httpx` absent); "structural test proves nothing" (inverted — pre-routing coverage IS the guarantee, now tested explicitly per the patch above); duplicate-Origin headers (browsers never send them; non-browser callers aren't the CSRF threat model); CORS methods/headers tightening (the guard supersedes; console-breakage risk for no gain); HEAD observability (no HEAD routes exist; the `_MUTATING` exemption is structural).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- RED required two steps: starlette's TestClient needs `httpx2` (added as a dev dep), then the genuine ImportError on `ALLOWED_ORIGINS`. GREEN 6/6.

### Completion Notes List

- The guard is an app-wide `@app.middleware("http")` — structural coverage of every current and future mutating route, no per-module opt-in. Deny-on-foreign-Origin / allow-on-absent (the standard localhost-tool posture; no session exists to bind a CSRF token to). OPTIONS untouched (preflight lives). 403 with the module-convention `{"detail": ...}` body.
- One origin list: the CORS middleware now reads `ALLOWED_ORIGINS` too — the drift class is closed at the source.
- Engine relocation (D4's other half) re-deferred with its real dependency named: sync-result → job-polling is a console contract change; pairs with the restructure; lands into the O.2 executor.

### File List

- services/api/src/qrp_api/main.py (modified — ALLOWED_ORIGINS + guard middleware)
- services/api/tests/test_origin_guard.py (new — 6 tests, first api test file)
- pyproject.toml / uv.lock (dev dep: httpx2)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D4 split)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-3); api test suite 0 → 6 green; live verification of all four postures. Status → review.
- 2026-06-10: Code review (3 adversarial layers) — 7 patches applied (TrustedHost DNS-rebinding companion; all guarded verbs + null/empty Origin tested; decisions documented; env-overridable origins; echo truncation; dep relocation), 5 dismissed — including the Blind layer's `httpx2`-typosquat "High", DISPROVEN live by the Auditor (starlette 1.2.1's own error names httpx2; it is the successor package). The Auditor independently verified postures the story hadn't tested (PUT/PATCH/DELETE, null Origin, pre-routing 403s, both console proxy paths). api suite 6 → 13. Status → done.
