# Story O.4: Error envelope rollout (chunk-1 D6)

Status: done

## Story

As Andre (the operator),
I want every API error to carry the spec'd `{ error: { type, message, detail? } }` envelope with an honest HTTP status,
so that the console (and any future consumer) handles failures from all nine modules through ONE shape instead of per-router accidents.

## Background + scope decision

Chunk-1 review (2026-06-10), ledger **D6**. The spec (architecture-qrp.md §Format Patterns) mandates the envelope; today every error is whatever FastAPI's `HTTPException` produces (`{"detail": ...}`), across ~25 raise sites in 9 routers, plus framework 422s and the O.3 origin guard's hand-built JSONResponse.

**Implementation choice — global exception handlers, not router churn:** one set of handlers in `create_app()` converts every `HTTPException`, `RequestValidationError`, and unhandled exception into the envelope. Zero changes to the 25 raise sites (they keep raising `HTTPException(status, detail)` — the handler translates), and **top-level `detail` is KEPT alongside the envelope** for console back-compat (`operate/page.tsx` reads it today). The one console consumer is updated to PREFER `error.message`.

**Status-vocabulary half (recorded, not churned):** the `ok|degraded|failed|stale` vocabulary is a console design-token pattern (Q1.1) already in use; the API-side deviation is sym freshness's deliberate 3-state `ok|stale|unknown` ("unknown" when nothing is measurable — MORE honest than forcing a 4th state). Recorded as a deviation note in the architecture doc rather than flattening honesty into the token set.

## Acceptance Criteria

1. **Envelope on every error path:** `HTTPException` (any router), framework 422 validation errors, the origin-guard 403, and unhandled 500s all return `{"error": {"type": <vocab>, "message": <human>, "detail": <optional structure>}, "detail": <legacy mirror>}`.
2. **Type vocabulary from status:** 403 `forbidden`, 404 `not_found`, 409 `conflict`, 422 `validation`, 503 `unavailable`, 500 `internal`, other 4xx `error`. 500s NEVER leak tracebacks — generic message, the exception class name only.
3. **Statuses unchanged:** every existing status code is preserved (the envelope wraps, never re-codes).
4. **Console prefers the envelope:** `operate/page.tsx` reads `error.message ?? detail ?? reason`.
5. **Vocabulary deviation recorded:** the architecture doc's status-vocabulary bullet notes freshness's deliberate `unknown` third state.
6. **Tests + live:** api tests cover all four handler paths (guard 403, module 404, framework 422, synthetic 500) asserting envelope shape + legacy `detail` mirror + no traceback leak; live curl spot-checks against the running API; ledger D6 done.

## Tasks / Subtasks

- [x] Task 1: Handlers in `create_app()` (AC: 1-3) — `_error_type_for`/`_error_body`/`_error_response` shared helpers; HTTPException + RequestValidationError + unhandled-Exception handlers; the guard builds its envelope inline via the SAME helper (constraint 2 verified: the guard runs outside the exception layer)
- [x] Task 2: Console consumer (AC: 4) — `operate/page.tsx` prefers `error.message ?? detail ?? reason`
- [x] Task 3: Architecture notes + ledger (AC: 5) — envelope marked IMPLEMENTED in §Format Patterns; freshness's 3-state deviation recorded in §Process Patterns; D6 done
- [x] Task 4: Tests + live (AC: 6) — 8 new api tests (suite 13 → 21); live: guard 403, router 422, framework 422 (field errors riding inside the envelope), 404, and unwrapped success all verified against the running API

## Dev Notes

### Constraints

1. **`detail` stays top-level** until the console fully migrates — removing it is a breaking change for zero gain.
2. **The origin guard's JSONResponse** is replaced by raising `HTTPException(403, ...)` so ONE handler owns the shape (the guard's pre-routing position is unchanged — exception handlers run for middleware-raised HTTPExceptions... VERIFY: Starlette middleware raising before routing may bypass the FastAPI exception handlers — if so, build the envelope inline in the guard with a shared helper so the shape can't drift).
3. **No router edits** beyond the guard; no OpenAPI regen (exception bodies aren't in response models).
4. **Unhandled-exception handler must not swallow** — log via the API's structured logger pattern (or stderr), return 500 envelope.
5. Services are running — restart after main.py changes for live checks.

### References

- [Source: architecture-qrp.md §Format Patterns (the envelope), §Process Patterns (status vocabulary)]
- [Source: deferred-work.md — chunk-1 D6]
- [Source: services/api/src/qrp_api/main.py; apps/web/app/sym/operate/page.tsx]

### Review Findings (code review 2026-06-10, commit 9d348a2 — ALL RESOLVED)

- [x] [Review][Patch] [HIGH] `exc.headers` forwarded (live: 405 carries `allow: GET`); 3xx HTTPExceptions re-dispatch to the framework default (Location preserved) [main.py]
- [x] [Review][Patch] `print_exc()` dropped; the comment now states the TRUTH (ServerErrorMiddleware re-raises; uvicorn logs the traceback; the handler only shapes the body) [main.py]
- [x] [Review][Patch] Mirror fidelity restored: structured detail mirrors as-is — the framework 422's top-level `detail` is the errors ARRAY again (live-verified), byte-compatible with the original FastAPI contract and the committed TS types; string details mirror the message (tested both) [main.py]
- [x] [Review][Patch] `exc.errors()` routed through `jsonable_encoder` [main.py]
- [x] [Review][Patch] Unhandled 500s stamp ACAO for allowed origins (tested) [main.py]
- [x] [Review][Patch] Docs corrected: `unknown` renders via the neutral fallback pill (no degraded branch exists); the two accepted un-enveloped paths recorded (TrustedHost 400, CORS preflights) [architecture-qrp.md]
- [x] [Review][Patch] Tests: padding non-test dropped; mirror contracts asserted both ways; the fixture re-runs the operation_id audit; the console guards `r.json()` against non-JSON bodies — api suite 21 → 22 [tests, page.tsx]
- Dismissed (4): 500 class-name disclosure (deliberate, tested, owner-operated); the two-`detail`s naming collision (the mirror is transitional by design — documented); 502/504 → `internal` (spec-silent; reasonable choice now recorded); pinning the Starlette-layering comment with a dedicated test (the guard-403 envelope test already pins the live shape).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- One drafted test would have launched a REAL job against the live DB mid-suite (POST op=validate, a non-confirm read op) — replaced with a pure mapping test before ever running it.

### Completion Notes List

- Zero router churn: all ~25 raise sites keep `HTTPException(status, detail)`; three global handlers translate. Statuses are never re-coded; 500s carry the class name only (full traceback to the server log via explicit print — handling suppresses uvicorn's default).
- The legacy top-level `detail` mirror stays until the console fully migrates; the one consumer now prefers `error.message`.
- Constraint 2 confirmed in practice: the origin guard is OUTSIDE the exception layer (outermost middleware), so it builds the envelope inline through the shared `_error_response` — one helper owns the shape everywhere.
- Status-vocabulary half recorded, not churned: freshness's deliberate `ok|stale|unknown` documented as a deviation (more honest than forcing the 4th token state).

### File List

- services/api/src/qrp_api/main.py (modified — helpers + 3 handlers + guard envelope)
- services/api/tests/test_error_envelope.py (new — 8 tests)
- apps/web/app/sym/operate/page.tsx (modified — prefers error.message)
- _bmad-output/planning-artifacts/architecture-qrp.md (modified — IMPLEMENTED note + deviation)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D6 done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-4); api suite 13 → 21 green; all five live paths verified. Status → review.
- 2026-06-10: Code review (3 adversarial layers; the Auditor live-proved the dropped 405 Allow header AND empirically disproved the dev's own uvicorn-suppression comment with a double-traceback) — 7 patches applied (headers forwarded; honest comment; the mirror now restores FastAPI's original 422 contract exactly; jsonable_encoder; ACAO on 500s; doc corrections; test hygiene), 4 dismissed. api suite 21 → 22. Status → done.
