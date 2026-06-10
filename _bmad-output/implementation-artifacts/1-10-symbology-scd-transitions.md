# Story 1.10: Symbology SCD transitions — renames close the old row (chunk-4 D2)

Status: done

## Story

As Andre (the data steward),
I want a ticker/ISIN change to CLOSE the security's previous identifier row and open the new one as one SCD transition,
so that "which ticker on date D?" has exactly one answer per security — the behavior `docs/data-conventions.md` §4 documents with the SQ→XYZ worked example, which today describes code that does not exist.

## Background (why this story exists)

Chunk-4 review (2026-06-10), ledger **D2**: no writer ever closes a `security_symbology` row. `_insert_symbology` guards the COLLISION case (recycled identifier held by a different FIGI → `SymbologyCollisionError`, the in-review mitigation) but a rename of the SAME security leaves two open ticker rows — the as-of query then returns both, and the data-conventions §4 worked example (Block's SQ→XYZ, old row `valid_to=2025-07-23`, new row from the same day) is aspirational documentation. The V3 validation AC for overlap/closed-without-successor was dropped with it.

## Design (recorded choices)

1. **Reconcile-on-write:** `write_security` already "reconciles" symbology — make that true. Per symbol type (ticker, isin), if the FIGI holds open row(s) of that type that differ from the seed's value (or MIC, for tickers), CLOSE them at the new row's `valid_from` (half-open `[from, to)` — the boundary day belongs to the new row, exactly §4's table) and insert the new row.
2. **Same-day transition = update in place** (standing rule): when the open row's `valid_from` equals the new `valid_from`, close+insert would violate the `valid_to > valid_from` CHECK — update the existing row's value/MIC instead.
3. **Collision guard stays first:** the new value held by a DIFFERENT figi still raises `SymbologyCollisionError`; transitions never steal identifiers.
4. **One open row per (figi, type) is the invariant**, enforced going forward by reconcile-on-write and audited by a new V3-style check: `symbology_transitions` FAILs duplicate-open rows and WARNs closed rows with no successor (`successor.valid_from == closed.valid_to`) when the security isn't delisted.
5. **Out of scope (documented):** updating `securities.mic`/`currency_code` on a relisting — a lifecycle question with price-currency cascades; the symbology row transition is recorded, the securities-row staleness is noted on the ledger.

## Acceptance Criteria

1. **Rename closes the old row:** given FIGI X with open ticker `SQ@XNYS` since D0, `write_security(seed ticker XYZ@XNYS, valid_from=D1)` closes SQ at D1 (`valid_to=D1`) and opens XYZ from D1 — the §4 as-of semantics hold (D1 resolves to XYZ; D1−1 to SQ).
2. **Same-day rename updates in place:** when the open row's `valid_from == D1`, the row's value is rewritten (no close+insert, no CHECK violation).
3. **ISIN transitions** use the same machinery (type `isin`, MIC-less).
4. **Collision precedence:** a rename TO a value held by a different figi raises `SymbologyCollisionError` and changes nothing (the old row stays open).
5. **Idempotency preserved:** re-running with the current value remains a no-op; `write_security`'s return contract and all existing callers (`apply_resolutions`, `resolve_review`, universe bridge) are unchanged.
6. **V3 audit check:** `symbology_transitions` in `sym validate` — FAIL per (figi, type) with >1 open row; WARN per closed row without a successor on a non-delisted security; wired into `run_all`, error-isolated.
7. **Docs honest:** data-conventions §4 notes the behavior is implemented (write path + check); ledger D2 done; the relisting/securities.mic scope-out recorded.
8. **Tests + live:** DB-free tests for ACs 1-6 (the rename, same-day, isin, collision, idempotent, check classifications); full suite green; live check — the steward-assigned fixtures and the 2,150-security master show zero duplicate-open rows (the check PASSes live, or surfaces real pre-existing drift to triage).

## Tasks / Subtasks

- [x] Task 1: Reconcile-on-write in `symbology.py` (AC: 1-5)
  - [x] `_reconcile_symbology`: collision check first; identical-open no-op; same-day in-place update (RETURNING-guarded); close-ALL earlier opens of the type at `valid_from`; insert unless rewritten
  - [x] `write_security` routes ticker + isin through it (call sites renamed)
- [x] Task 2: `symbology_transitions` validate check (AC: 6) — wired as the 13th check
- [x] Task 3: Docs + ledger (AC: 7)
- [x] Task 4: Tests + live audit (AC: 8)

## Dev Notes

### Constraints

1. **The EXCLUDE/CHECK constraints are the backstop, not the mechanism** — `valid_to > valid_from` CHECK forces the same-day in-place rule; the overlap EXCLUDE on (type, value, mic) stays untouched.
2. **Close means `valid_to = new valid_from`** (exclusive end; boundary day belongs to the successor) — exactly the §4 table.
3. **Defensive close-ALL:** pre-fix data may hold multiple open rows of one type for a figi; the transition closes every differing open row of that type, not just "the" one.
4. **No schema change.**
5. **`as_of_date` canonical naming** for any new date params (the existing `valid_from` SCD names stay — they're column names, the convention's range-vocabulary).
6. **Callers unchanged:** `apply_resolutions` (`_apply_one` wraps in a transaction), `resolve_review` (transaction since 1.9 review), `backfill`/bridge paths — reconcile must stay safe under all three.

### Previous-story intelligence

- 1.9 review hardened `resolve_review` to a single transaction — transitions inside it inherit atomicity.
- Today's stewarding exercised `write_security` reconcile twice per fixture (assign, then isin-completion re-run) — the idempotent path is live-proven; the TRANSITION path has never run anywhere.
- Validate-check template: `validate/symbology.py::check_identity_completeness` (same file gets the new check); wire in `runner.py` (12 → 13 checks).
- Suite baseline 516 / ~7s (OpenFIGI-probe tests added time; DB-free core ~3.5s); lint baseline 18.

### References

- [Source: docs/data-conventions.md §4 — the SQ→XYZ worked example this story makes true]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — chunk-4 D2]
- [Source: packages/sym/src/sym/identity/symbology.py; packages/sym/src/sym/validate/symbology.py]

### Review Findings (code review 2026-06-10, commit 24a0923 — ALL RESOLVED)

- [x] [Review][Patch] [HIGH] Backdated writes now REFUSE (`SymbologyTransitionError`) — verified live (state unchanged after the refusal) [symbology.py]
- [x] [Review][Patch] The drift sweep runs on the idempotent path too, keyed per-row on (value, mic) — pre-1.10 duplicate-opens self-heal on the next routine write of the current value (tested: survivor untouched, stale row closed) [symbology.py]
- [x] [Review][Patch] Restructured around one fetch of the type's open rows: same-day drift (>1 differing same-day open) refuses; in-place and close UPDATEs precisely keyed by the old (value, mic); mutation phase in `conn.transaction()` (savepoint under caller transactions, real txn under autocommit) [symbology.py]
- [x] [Review][Patch] Closed-row overlap reasoning recorded at the backdating guard (a non-backdated new row starts at/after every open row's start, so no closed range can overlap it) [symbology.py]
- [x] [Review][Patch] Check upgraded: `s.status <> 'delisted'` (suspended no longer exempt); `checked` = rows scanned (2,199 live); OVERLAP detection added (same figi/type ranges, both-open pairs excluded — the V3 AC fully restored) [validate/symbology.py]
- [x] [Review][Patch] Bridge isolates `SymbologyCollisionError`/`SymbologyTransitionError` per member (`skipped_collision` counter; tested: collision doesn't abort the loop) [universe/ingest.py]
- [x] [Review][Patch] Live round-trip on synthetic `BBG000000ZZ9` against the REAL constraints: rename closed A at the boundary + opened B; same-day B→C rewrote in place; backdated D refused; the check PASSed with the transition history present (closed-with-successor not false-warned); cleaned up (2,201 → 2,199 rows) [live verification]
- [x] [Review][Patch] §4 notes the refusal semantics + full audit scope; dual-listing representation design on the ledger [docs, ledger]
- [x] [Review][Defer] Dual-listing representation design — ledger
- Dismissed (3): country_iso-only refresh on the no-op path (country derives from the static exchange table); fakes not modeling EXCLUDE/CHECK (project DB-free convention — the live round-trip patch is the compensator); the "no schema backstop" partial-unique-index suggestion (the audit check + refusal guards are the chosen mechanism; an index migration can ride the next schema batch).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8) via Claude Code, red-green-refactor.

### Debug Log References

- RED: collection error (`check_symbology_transitions` absent) → GREEN 9/9; suite 525; lint at the 18 baseline.

### Completion Notes List

- **Task 1:** `_insert_symbology` became `_reconcile_symbology` with the full SCD transition: collision guard first (unchanged — transitions never steal identifiers), identical-open no-op (idempotency preserved), same-day in-place rewrite (the `valid_to > valid_from` CHECK forbids zero-length closes — the standing SCD rule), close-ALL earlier differing opens at the new `valid_from` (defensive plural for pre-1.10 drift), insert unless the in-place path fired. The §4 boundary-day semantics hold by construction (`valid_to` = successor's `valid_from`, exclusive).
- **Task 2:** `symbology_transitions` check: FAIL per (figi, type) duplicate-open; WARN per closed row on a non-delisted security with no successor at exactly its `valid_to`. 13th check in `run_all`.
- **Tests:** stateful fake modeling the symbology table — the close/insert/in-place logic asserted BEHAVIORALLY (rename, same-day, isin, MIC-change relisting, collision-unchanged, idempotent re-run) + 3 check-classification tests.
- **Live:** `symbology_transitions` PASSes against the 2,150-security master — zero duplicate-open, zero closed-without-successor (no rename has ever occurred; the machinery now precedes the first one). Overall validate unchanged at the 2 pre-existing data-quality fails.
- Scope-out recorded (design choice 5): a relisting transitions the ticker row but `securities.mic`/`currency_code` stay stale — needs its own design (price-currency cascade); on the ledger.

### File List

- packages/sym/src/sym/identity/symbology.py (modified — `_reconcile_symbology` transition)
- packages/sym/src/sym/validate/symbology.py (modified — new check)
- packages/sym/src/sym/validate/runner.py (modified — wire, 13 checks)
- packages/sym/tests/test_symbology_transitions.py (new — 9 tests)
- docs/data-conventions.md (modified — §4 implemented-behavior note)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D2 done + relisting scope-out)

### Change Log

- 2026-06-10: Story implemented (Tasks 1-4); suite 516 → 525 green; live audit clean. Status → review.
- 2026-06-10: Code review (3 adversarial layers) — 8 patches applied (HIGH: backdated writes refused; drift sweep on the no-op path; same-day drift refused; bridge isolation; overlap detection; live round-trip proved the transition branch against the real EXCLUDE/CHECK constraints — the prior "live audit clean" was correctly called vacuous), 1 deferred (dual-listing design → ledger), 3 dismissed. Suite 525 → 530 green. Status → done.
