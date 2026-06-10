# Story 1.9: Review-queue gating — make the queue a gate, not a write-only log (chunk-4 D1)

Status: review

## Story

As Andre (the data steward),
I want resolution runs to SKIP inputs with an open review row (no OpenFIGI re-query, no auto-assignment) and a CLI to list and resolve queue items,
so that Story 1.4's AC2/AC3 actually hold: a queued input is excluded until I resolve it, and resolving it makes it eligible again — instead of the queue being a write-only log nothing reads.

## Background (why this story exists)

Chunk-4 review (2026-06-10) found Story 1.4 AC2 **violated**: `securities_review_queue` is write-only. Nothing reads it — `plan_resolutions` re-queries OpenFIGI for every seed on every run (quota burn), `apply_resolutions` would auto-assign an input whose review row sits open (bypassing the steward mid-review), and **no code path ever sets `resolved_at`**, so AC3 ("a resolved item becomes eligible") is unreachable. The schema was built for the gate that never came: the partial unique index frees a key once resolved, and `idx_securities_review_queue_open` is literally commented "Supports 'list/skip open items' scans by the assignment run."

Live state: 5 open rows (TWTR/ATVI/LEHMQ/ENE/CSGN — the adversarial seed names), re-queried every `sym resolve` run. In-review mitigation already applied (don't redo): `enqueue_review` refreshes an open row's status/candidates/detail.

## Design (recorded choices)

1. **Gate at the DB-aware caller, planner stays pure.** `plan_resolutions` is deliberately no-DB; the gate lives in `resolve_universe` (and anything else that pairs a conn with the planner): load the open-key set once, partition seeds, plan only the unqueued ones.
2. **Gate on ALL of a seed's resolution inputs**, not just the primary: the queued row's `source_key` may be the ISIN-fallback key (when the fallback pass produced the classified query) while the next run's primary is the ticker key — a primary-only check would miss it.
3. **Skipped ≠ silent:** `ResolutionSummary.skipped_queued` + the seeds' names surfaced; the CLI prints the count with a pointer to `sym review list`.
4. **Operator path is part of the gate:** `sym review list` (open items) and `sym review resolve <id> [--figi BBG...]`. With `--figi`, the steward picks the winner (validated shape; security + symbology written from the queued `source_input` via the existing `write_security` path) and the row closes; without, the row simply closes (dismiss) and the input becomes auto-retry-eligible next run (AC3). The partial unique index then frees the key, so a recurrence re-queues fresh.

## Acceptance Criteria

1. **Exclusion (1.4 AC2 made real):** a seed any of whose resolution-input keys has an OPEN queue row is skipped by `resolve_universe`: NOT sent to OpenFIGI, NOT assigned, counted as `skipped_queued` and listed in the run output.
2. **Eligibility (1.4 AC3 made real):** closing the row (`sym review resolve`) makes the input participate normally in the next run; a still-unresolvable input re-queues (the freed key admits a new open row).
3. **Steward assignment:** `sym review resolve <id> --figi <BBG...>` writes the security + current symbology from the queued `source_input` (existing `write_security`), then closes the row; invalid FIGI shape or unknown review_id / already-resolved row exits 1 with a clear message.
4. **List surface:** `sym review list` shows open items (id, key, status, candidate count, age in days); `--all` includes resolved ones; empty queue prints a clean message, exit 0.
5. **Quota honesty:** the gate demonstrably avoids OpenFIGI traffic for queued seeds (DB-free test asserts the client receives no query for a gated seed).
6. **Live verification:** against the real queue (5 open rows) — a resolve run skips all 5 with `skipped_queued=5` and zero OpenFIGI calls for them; `sym review list` shows them; dismiss-resolve one synthetic row end-to-end (synthetic, so the real 5 stay queued for actual stewarding). Cleanup per the test-row rule.
7. **Tests + suite:** DB-free tests for the gate (incl. fallback-key matching), summary counter, CLI list/resolve paths; full suite green; zero new lint.

## Tasks / Subtasks

- [x] Task 1: Queue read + close API (AC: 2, 3, 4)
  - [x] `review_queue.open_review_keys(conn) -> set[str]`; `list_reviews(conn, include_resolved=False)`; `resolve_review(conn, review_id, *, composite_figi=None, share_class_figi=None) -> outcome` (validates open + figi shape; assignment path reuses `write_security` with a `SeedSecurity` built from `source_input`)
- [x] Task 2: The gate in `resolve_universe` (AC: 1, 5)
  - [x] Partition seeds by any-input-key ∈ open set BEFORE planning; `ResolutionSummary.skipped_queued` + `skipped_names`; skipped seeds never reach `client.map_identifiers`
- [x] Task 3: CLI (AC: 3, 4)
  - [x] `sym review list [--all]`, `sym review resolve <review_id> [--figi ...] [--share-class-figi ...]`; `sym resolve` output gains the skipped line
- [x] Task 4: Tests (AC: 5, 7) — 12 DB-free tests
- [x] Task 5: Live verification + docs touch-up (AC: 6) — runbook gains the steward loop

## Dev Notes

### Wiring map

| File | Current | Change |
|---|---|---|
| `identity/review_queue.py` | `source_key` + `enqueue_review` only; nothing reads, nothing closes | add `open_review_keys`, `list_reviews`, `resolve_review` |
| `identity/figi.py` | `resolve_universe` plans ALL seeds; `ResolutionSummary` has no skip counter; `write_security` exists (reuse) | gate + counter; no change to `plan_resolutions` (stays pure) |
| `cli.py` | `resolve` command exists; no review group | new `review` subcommand group; resolve-output line |
| `migrations/` | schema complete (partial unique open index; `resolved_at`) | NOTHING — no schema change |

### Constraints

1. **`plan_resolutions` stays pure (no conn)** — the gate is the caller's job.
2. **Key matching must mirror `source_key` exactly** (symbol_type:value@mic; no exch_code) and cover every `seed.resolution_inputs()` entry (design choice 2).
3. **`resolve_review --figi` writes through `write_security`** — never hand-rolled INSERTs (symbology SCD + collision guard live there). The known symbology-SCD gaps are chunk-4 D2, NOT this story.
4. **Per-item error isolation** in the CLI resolve path (consistent with `apply_resolutions`); `conn.autocommit=True` durability pattern.
5. **`as_of_date` canonical naming** if any date params appear (none expected).
6. **universe-member resolution (`universe/resolution.py`) is OUT of scope** — it has its own retained-unresolved model (`universe_member_resolution`), not the securities queue.

### Previous-story intelligence

- Live queue rows 1-5 are real operator work (delisted/renamed names) — the live test must NOT consume or close them beyond listing; use a synthetic row for the end-to-end resolve.
- `enqueue_review` returns inserted-vs-refreshed via `xmax = 0` — reuse the established fake-conn SQL-substring pattern for tests (`RETURNING review_id, (xmax = 0)`).
- Suite baseline 495 / ~3.4s; lint baseline 18 pre-existing errors.

### References

- [Source: _bmad-output/planning-artifacts/epics.md §Story 1.4] — the violated ACs
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-4 D1]
- [Source: packages/sym/migrations/deploy/securities_review_queue.sql] — the gate the schema always expected
- [Source: packages/sym/src/sym/identity/{figi,review_queue}.py]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- RED: collection error (queue API absent) → GREEN 12/12; one F401 (unused import) fixed; suite 507, lint back to the 18-error baseline.

### Completion Notes List

- **Task 1:** `open_review_keys` / `list_reviews` / `resolve_review` in `review_queue.py`. `resolve_review` raises typed `ReviewQueueError` on unknown/already-resolved ids, malformed FIGIs, and ticker-less inputs (assignment needs the listing for currency/symbology); assignment goes through `write_security` only (constraint 3 — symbology SCD + collision guard live there). Cycle-safe: `symbology` doesn't import `review_queue`.
- **Task 2:** the gate partitions seeds BEFORE planning on the union of every `resolution_inputs()` key (design choice 2 — a queued ISIN-fallback key gates a ticker-led seed), so gated seeds never reach `client.map_identifiers`. `plan_resolutions` stays pure (constraint 1).
- **Task 3:** `sym review list [--all]` / `sym review resolve <id> [--figi ...]`; `sym resolve` prints the skipped count + names with a pointer to the steward surface.
- **Task 5 (live):** `sym review list` shows the 5 real queued names (TWTR/ATVI/LEHMQ/ENE/CSGN, open 4d). A full `sym resolve` run: 45 assigned/named normally, **5 skipped — open review rows** (named in the output), 0 new review rows — these 5 previously hit OpenFIGI on every run. Synthetic end-to-end (review #11, `ticker:ZZZTEST9@XNAS`): dismiss via CLI → key freed → re-enqueue inserts a NEW open row (AC2→AC3 cycle proven against the partial unique index) → 2 synthetic rows cleaned. Unknown-id resolve exits 1 cleanly. The real 5 remain queued for actual stewarding (deliberately untouched).
- Runbook gains the steward loop next to `sym resolve`; ledger chunk-4 D1 marked done.

### File List

- packages/sym/src/sym/identity/review_queue.py (modified — read/close API, ReviewQueueError)
- packages/sym/src/sym/identity/figi.py (modified — gate in resolve_universe, summary counters)
- packages/sym/src/sym/cli.py (modified — `review` group, resolve-output line)
- packages/sym/tests/test_review_queue_gating.py (new — 12 tests)
- docs/runbook.md (modified — steward loop)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — chunk-4 D1 done)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-5); suite 495 → 507 green; live gate verified (5 real queued names skipped on a full resolve run; synthetic dismiss→re-queue cycle proven). Status → review.
