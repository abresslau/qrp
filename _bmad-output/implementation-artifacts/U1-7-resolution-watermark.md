# Story U1.7: Snapshot-pin resolution watermark (ledger D2)

Status: done

## Story

As Andre (the operator),
I want a snapshot pin to watermark RESOLUTIONS as well as events,
so that re-running the same pin returns the same member set even after a previously-unresolved member resolves — full reproducibility, not events-only reproducibility.

## Background (why this story exists)

Ledger **D2** (chunk-3 review): `members_pinned` (Story U1.6) re-projects from events `<= log_version`, but joins to `universe_member_resolution` as it stands NOW. A member that was unresolved at pin time (excluded from the projection) and resolves later silently APPEARS in a re-run of the same pin. The caveat is documented in `snapshot.py`'s module docstring.

Investigation for this story found the ledger's premise stale and a second defect:

1. **`resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()` already exists** in `universe_member_resolution` — NO schema migration is needed (the ledger said "needs resolved_at (schema)").
2. **The upgrade-only upsert doesn't bump `resolved_at`:** `_write_resolutions`' `ON CONFLICT ... DO UPDATE` (unresolved→resolved upgrade) leaves `resolved_at` at its INSERT-time default. A watermark filter would therefore INCLUDE post-pin upgrades (their timestamp predates the pin) — the watermark would be silently defeated for exactly the rows it exists to exclude.

`members_pinned` has no production callers yet (it is the U1.6 reproducibility API, built for backtest pins), so extending the pin signature is non-breaking.

## Design (recorded choice)

A pin becomes `(universe_id, as_of_date, log_version, resolved_through)` where `resolved_through` is a timestamp watermark over `universe_member_resolution.resolved_at`. The pinned query adds `AND r.resolved_at <= resolved_through` to the resolution join. Because resolutions are upgrade-only (a frozen RESOLVED row is never re-pointed), the only mutation class is unresolved→resolved — and once that upgrade BUMPS `resolved_at`, the filter excludes exactly the post-pin upgrades: the pin sees the resolution state as it stood. `resolved_through=None` keeps the legacy events-only behavior (existing pins stay readable; the docstring says what they guarantee).

## Acceptance Criteria

1. **Upgrade bumps the clock:** the unresolved→resolved upsert sets `resolved_at = now()`; a fresh INSERT keeps the column default. (Without this the watermark is defeated — tested.)
2. **Watermarked pin:** `members_pinned(..., resolved_through=T)` excludes resolutions with `resolved_at > T`; a member unresolved at pin time stays out of the pin's member set forever, even after it resolves. `resolved_through=None` preserves current behavior.
3. **Pin capture helper:** `current_resolution_version(conn, universe_id)` returns the watermark to store alongside `current_log_version` when taking a pin (max `resolved_at` for the universe; epoch-safe when no resolutions exist).
4. **Caveat retired:** the KNOWN CAVEAT paragraph in `snapshot.py` is replaced by the real semantics; D2 marked done on the ledger.
5. **Tests:** DB-free — upgrade-bumps-`resolved_at` (SQL asserted), watermark excludes a post-pin upgrade, None = legacy, capture helper; full suite green.
6. **Live smoke (ibov):** capture `(log_version, resolution_version)`, run `members_pinned` twice with both watermarks — identical non-empty sets, equal to the unpinned current members (no pending divergence on a quiet log).

## Tasks / Subtasks

- [x] Task 1: Bump `resolved_at` on upgrade (AC: 1)
- [x] Task 2: Watermark plumbing (AC: 2, 3) — `_membership_events(resolved_through=...)`, `members_pinned(resolved_through=None)`, `current_resolution_version`
- [x] Task 3: Docs + ledger (AC: 4)
- [x] Task 4: Tests + live smoke (AC: 5, 6)

## Dev Notes

### Constraints

1. **No schema change** — `resolved_at` exists; this is code only. (If it hadn't, the Docker sqitch flow applies — not needed.)
2. **Frozen-resolution invariant is the design's load-bearing wall:** the upsert's upgrade-only guard (`WHERE status='unresolved' AND EXCLUDED.status='resolved'`) means a row mutates at most ONCE; with the bump, `resolved_at` is "when this mapping became visible". A future re-pointing path would break pin reproducibility and must come with resolution SCD — note in the docstring.
3. **Status flips to `unpriced`** (set by ingestion on resolved members) don't touch the figi mapping and both `resolved`/`unpriced` project; the watermark is unaffected. Verify no other writer touches the table.
4. **`as_of_date` canonical naming**; pin param is `resolved_through` (a timestamp, not a business date — don't call it a date).
5. The pure layer (`members_from_events`, `project_membership`) is untouched — the watermark lives entirely in the SQL fetch.

### Previous-story intelligence

- U3.7 just touched `_membership_events` (provenance SELECT) and `members_pinned`'s docstring (one-time pairing shift note) — keep both.
- Fakes: SQL-substring dispatch; snapshot tests are pure today — the new DB-touching tests need a small fake conn (pattern in `test_universe_monitor_routing.py`).
- Suite baseline 486 / ~3s; lint baseline 18 pre-existing.

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md — D2]
- [Source: packages/sym/src/sym/universe/{snapshot,projection,resolution}.py]
- [Source: packages/sym/migrations/deploy/universe_member_resolution.sql — resolved_at already present]

### Review Findings (code review 2026-06-10, commit 47cd9ea — ALL RESOLVED)

- [x] [Review][Patch] Live exclusion round-trip EXECUTED (ibov, synthetic `ticker:ZZZTEST3@BVMF`): unresolved row written → `capture_pin` → member absent → `_write_resolutions` upgrade (re-stamps `resolved_at`) → watermarked pin STILL excludes it (`reproducible=True`) while the legacy events-only pin INCLUDES it — the D2 bug demonstrated and its fix proven against real Postgres on the same data. Cleanup verified, monitor baseline 0/0 [live verification]
- [x] [Review][Patch] AC1 fully tested: INSERT clause omits `resolved_at` (default preserved) AND both halves of the upgrade-only WHERE guard asserted [tests]
- [x] [Review][Patch] `capture_pin()` added — both watermarks from ONE statement (single-snapshot consistency), recommended by the docstrings; tested [snapshot.py]
- [x] [Review][Patch] Naive `resolved_through` now raises `ValueError` (session-timezone replay hazard); param keyword-only [projection.py, snapshot.py]
- [x] [Review][Patch] `current_resolution_version`/`capture_pin` raise `UnknownUniverseError` for a nonexistent universe (no silent epoch pins) [snapshot.py]
- [x] [Review][Patch] Capture-discipline preconditions documented in full on `capture_pin` (transaction-start `now()`, equal-timestamp boundary, clock monotonicity, epoch-pin semantics); `resolved_at` semantics = "last became visible"; future-`unpriced`-writer rule recorded (census: no such writer exists) [snapshot.py, resolution.py]
- [x] [Review][Patch] Ledger entry: sequence-based resolution watermark as the robust upgrade path [deferred-work.md]
- [x] [Review][Defer] Sequence-based resolution watermark (schema) — deferred to ledger; the timestamp approach + documented capture discipline is proportionate for a single-operator pipeline
- Dismissed (3): `resolved_through=None` default "backwards" (legacy compat was an explicit AC; keyword-only applied); substring/private-internal test style (project-wide DB-free convention; the live exclusion round-trip is the behavioral compensator); future-timestamp caller-error guard (tz-naivety is the silent hazard worth guarding; a future timestamp is loud operator error).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- RED: collection error (`current_resolution_version` absent) → GREEN 5/5 after implementation; full suite 491.

### Completion Notes List

- **Task 1:** the upgrade-only upsert now re-stamps `resolved_at = now()` — the design's load-bearing detail: without it an unresolved→resolved upgrade keeps its INSERT-time default, predates every pin, and leaks into every old pin's member set. Upsert comment explains the dependency.
- **Task 2:** `_membership_events` gained `resolved_through` (adds `AND r.resolved_at <= %s` to the resolution join); `members_pinned` forwards it (`None` = legacy U1.6 events-only pin, documented as the weaker guarantee); `current_resolution_version` captures `max(resolved_at)` (epoch-safe) with a take-the-pin-outside-a-resolution-run note.
- **Task 3:** snapshot.py module docstring rewritten — the KNOWN CAVEAT is retired, the four-tuple pin semantics + frozen-resolution dependency (re-pointing would need resolution SCD) recorded; ledger D2 done, including the stale-premise correction (NO schema change was needed — `resolved_at` already existed).
- **Task 4:** 5 DB-free tests (upgrade bump SQL, filter SQL+param, no-filter default, pin forwards both watermarks, capture helper). Live smoke (ibov): pin `(log_version=8660, resolved_through=2026-06-08T01:33:49+01)` run twice → identical 78-member sets, equal to the current projection as-of 2026-06-09.

### File List

- packages/sym/src/sym/universe/resolution.py (modified — upgrade re-stamps resolved_at)
- packages/sym/src/sym/universe/projection.py (modified — resolved_through filter)
- packages/sym/src/sym/universe/snapshot.py (modified — pin param, capture helper, caveat retired)
- packages/sym/tests/test_universe_resolution_watermark.py (new — 5 tests)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D2 done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-4); suite 486 → 491 green; live ibov pin smoke passed. Status → review.
- 2026-06-10: Code review (3 adversarial layers; Auditor ran the writer census — one writer, no delete path, no `unpriced` writer exists) — 7 patches applied, 1 deferred (sequence watermark → ledger), 3 dismissed. The decisive patch: the exclusion behavior was only substring-tested; the live round-trip now demonstrates both the fix (watermarked pin reproducible across an upgrade) and the original D2 bug (legacy pin leaks the member) on real Postgres. Hardening: `capture_pin` atomic capture, naive-datetime rejection, unknown-universe guard, full capture-discipline docs. Suite 491 → 495 green. Status → done.
