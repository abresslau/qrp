# Story 1.8: GICS classification (slowly-changing dimension)

Status: review

<!-- Materialized retroactively from epics.md during dev-story resume (2026-06-06). The
     gics_scd migration was authored before this spec file existed; it is captured here as a
     completed task so the remaining loader + coverage test can be tracked to completion. -->

## Story

As a researcher,
I want all four GICS levels stored in an SCD-shaped table populated from financedatabase,
so that ≥90% of active securities are classifiable and the shape tolerates future point-in-time history.

## Acceptance Criteria

1. **Given** migrations, **When** the classification migration deploys, **Then** a GICS table in the `classification/` domain stores sector / industry-group / industry / sub-industry codes + labels in SCD (effective-dated) shape, keyed to CompositeFIGI, with audit timestamps.
2. **Given** the financedatabase loader, **When** it runs over identified securities, **Then** ≥90% of active securities have all four GICS levels populated (current-only data).
3. **Given** the architecture Requirements→Structure map, **Then** GICS is documented under `classification/`, not `identity/` (OI-4 correction). **And** all four levels are queryable and indexed.

> Reconciliation (recorded in `migrations/deploy/gics_scd.sql`): the financedatabase source supplies only the top three GICS **labels** (sector, industry-group, industry). Sub-industry and the numeric GICS **codes** are not available from it, so those columns exist in the SCD shape (for a future coded/point-in-time feed) but stay NULL today. AC-2's "all four levels" is satisfied at the **shape** level — the table has all four levels and is current-only-populated to the depth the free source provides. Coverage is measured on the levels the source supplies (sector present).

## Tasks / Subtasks

- [x] Task 1: GICS SCD migration (AC: #1, #3)
  - [x] `gics_scd` table: all four levels (code+name), `composite_figi` FK, `valid_from`/`valid_to`, audit timestamps
  - [x] `btree_gist` EXCLUDE no-overlap constraint (one classification per instant)
  - [x] Indexes on each queryable level + `composite_figi`; `set_updated_at` trigger
  - [x] revert + verify scripts; entry in `sqitch.plan`
- [x] Task 2: financedatabase GICS source + loader in `src/sym/classification/` (AC: #2)
  - [x] `GicsClassification` record (top-3 labels populated; sub-industry + codes NULL)
  - [x] `GicsSource` Protocol + `FinanceDatabaseGicsSource` concrete impl (keyed on `composite_figi`), isolating the external dependency behind a boundary (mirrors `OpenFigiClient` in `identity/figi.py`)
  - [x] `plan_classifications(securities, source)` — pure, no DB writes
  - [x] `apply_classifications(conn, plans, as_of)` — SCD-aware idempotent upsert, one transaction per security; returns a coverage summary
  - [x] `classify_universe(conn, source, as_of)` orchestrator
- [x] Task 3: tests in `tests/test_classification.py` (AC: #2, #3)
  - [x] Mapping: financedatabase row → `GicsClassification` (labels populated, sub-industry + codes NULL)
  - [x] Coverage: a fake source covering ≥90% of a security set yields summary coverage ≥ 0.90; a thin source falls below and is reported (threshold not silently widened)
  - [x] Idempotent SCD write against a fake connection (re-run = no overlap; changed classification closes prior row then inserts)
- [x] Task 4: OI-4 mapping correction in architecture.md Requirements→Structure Mapping (AC: #3)
- [x] Task 5: address code-review findings (AC: #2)
  - [x] Same-day reclassification updates the row in place instead of close+insert (avoids `valid_to = valid_from` CHECK violation)
  - [x] Per-security error isolation: a failing write is rolled back, counted (`summary.failed`), and the run continues
  - [x] `sym classify` CLI command wires `FinanceDatabaseGicsSource` → `classify_universe`; exits non-zero when coverage is below the threshold (AC #2 gate observable)
  - [x] Tests cover the same-day in-place path and error isolation; `_RouterConn` now carries `valid_from`
  - [x] `read_active_figis` reuses `lifecycle.iter_securities` instead of duplicating the active-scope SQL

## Dev Notes

- **Patterns to follow:** `src/sym/identity/figi.py` isolates the external dependency (OpenFIGI) behind a `Protocol` (`OpenFigiClient`) so classification logic is testable without the network, and persists with one `conn.transaction()` per security in `apply_resolutions`. GICS mirrors this: `GicsSource` Protocol + concrete `FinanceDatabaseGicsSource`, pure `plan_*` then transactional `apply_*`.
- **financedatabase shape (verified):** `fd.Equities().select()` returns a frame indexed by `symbol` with columns including `composite_figi`, `sector`, `industry_group`, `industry`, `isin`, `cusip`, `figi`, `shareclass_figi`, `mic`. There is **no** `sub_industry` column and **no** numeric GICS codes — only the top-3 labels. Many rows carry NaN `composite_figi`; the source must drop those and dedupe by first non-null `sector`.
- **Join key:** `securities.composite_figi` ↔ financedatabase `composite_figi`. (ISIN/ticker fallback via `security_symbology` is out of scope for this story; AC-2's 90% is met for the large-cap seed universe on `composite_figi` alone.)
- **SCD writes:** current-only data → `valid_from = as_of` (param, defaults `date.today()`), `valid_to NULL`. Idempotent re-run guard mirrors `symbology._insert_symbology`: a currently-effective row that matches → no-op; one that differs → close (`valid_to = as_of`) then insert (respects `gics_scd_no_overlap` EXCLUDE). Never reverse-engineer or hard-delete.
- **Testing standard:** existing suite is unit-level and DB-free (`tests/test_lifecycle.py` uses a `_RecordingConn`); GICS tests follow suit — a fake `GicsSource` + a fake/recording connection. No live Postgres or live financedatabase call in tests.

### Project Structure Notes

- GICS lives in `src/sym/classification/` (OI-4 correction: classification domain, not `identity/`). The package docstring is already in place; this story fills `classification/gics.py`.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.8: GICS classification (slowly-changing dimension)]
- [Source: _bmad-output/planning-artifacts/epics.md#AR-11 — D4 GICS SCD] — SCD shape is the one genuine one-way door.
- [Source: _bmad-output/planning-artifacts/epics.md#OI-4 — FR-4 mapping label] — GICS under classification/.
- [Source: migrations/deploy/gics_scd.sql] — table shape + the labels-only reconciliation note.

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

- `uv run pytest tests/test_classification.py` → 12 passed (new).
- `uv run pytest` → 43 passed (no regressions across the existing 31).
- `uv run ruff check` → all checks passed.
- Post code-review: verified `sym classify` is registered and `meets_threshold()` gates coverage.
- **Live end-to-end (2026-06-06):** deployed `gics_scd` via sqitch (Docker image), `sym resolve` → 30 securities, `sym classify` → **28/30 classified, 93.3% coverage, exit 0**; second run → `28 unchanged` (same-day idempotency confirmed). `gics_scd` holds 28 currently-effective rows.
- Live run also surfaced an unrelated bug in Story 1.6's `figi.py`: the unkeyed OpenFIGI `/mapping` batch size was 25 but the real cap is 10 jobs/request (HTTP 413). Fixed `_batch_size` 25 → 10 (and the doc comment). Not part of Story 1.8 scope but required to populate `securities` for the demo.

### Completion Notes List

- The `gics_scd` migration was already deployed before this story file existed; Task 1 was captured as complete and the remaining loader + tests implemented to finish the story.
- `src/sym/classification/gics.py` mirrors the `identity/figi.py` boundary pattern: the external dependency (financedatabase) sits behind a `GicsSource` Protocol with a concrete `FinanceDatabaseGicsSource`, so the loading logic is unit-tested with no network and no live Postgres.
- **Reconciliation honored:** financedatabase supplies only the top three GICS *labels*; sub-industry and numeric codes are written NULL (columns exist in the SCD shape for a future coded feed). Coverage (AC #2) is measured on sector presence; the 0.90 threshold is the default in `meets_threshold()` and a below-threshold run is reported, never silently widened (SM-C2 spirit).
- **SCD idempotency:** a re-run with an unchanged classification is a no-op; a changed one closes the prior row (`valid_to = as_of`) before inserting — respecting the `gics_scd_no_overlap` EXCLUDE constraint and never hard-deleting.
- AC #3 (OI-4): corrected the architecture's Requirements→Structure Mapping to home FR-4 under `classification/`, not `identity/`.
- ~~Note for review: the loader joins on `composite_figi` only. ISIN/ticker fallback via `security_symbology` was deliberately left out of scope~~ — **resolved 2026-06-06:** after the OpenFIGI resolution fix expanded the universe to 45 securities (incl. international names), composite_figi-only coverage fell to 84.4%. Added an **ISIN fallback** to `FinanceDatabaseGicsSource` (`SecurityIdentity` carries `composite_figi` + `isin`; `read_active_identities` joins `security_symbology`; a match found by ISIN is attributed to our CompositeFIGI). Coverage rose to 95.6% (43/45); only TSMC/Toyota remain (absent from financedatabase even by ISIN).

**Code-review follow-ups (all applied):**

- **[HIGH] Same-day SCD CHECK violation** — close-then-insert set `valid_to = valid_from = as_of` on a same-day correction, violating `gics_scd_validity_chk`. Now: when the currently-effective row's `valid_from == as_of`, `apply_classifications` overwrites it in place (`_update_in_place`) — no zero-width period. Cross-day changes still close-then-insert. `_current_row` now returns `valid_from` to make the distinction.
- **[MED] Error isolation** — each security's write is wrapped in `try/except psycopg.Error`; a failure is rolled back, counted in `summary.failed`, and the loop continues (matches the docstring's intent).
- **[MED] No entry point** — added `sym classify` (`_cmd_classify`) wiring `FinanceDatabaseGicsSource` → `classify_universe`; prints coverage + write counts and returns exit code 2 when below the 0.90 threshold, so AC #2's gate is operationally observable.
- **[MED] Test gap** — added `test_changed_classification_on_the_same_day_updates_in_place` (catches the HIGH bug) and `test_failed_write_is_isolated_and_counted`; `_RouterConn` now models `valid_from` and lifecycle-shaped securities rows. A live-Postgres test of the close path remains a sensible future add (the suite is otherwise DB-free by design).
- **[LOW] Reuse** — `read_active_figis` now delegates to `lifecycle.iter_securities` rather than duplicating `status = 'active'`.

### File List

- `src/sym/classification/gics.py` (new) — GICS source, loader, SCD-aware idempotent writer (same-day in-place / cross-day close), per-security error isolation, coverage summary.
- `src/sym/cli.py` (modified) — added the `classify` subcommand + `_cmd_classify`.
- `tests/test_classification.py` (new) — 12 unit tests: row mapping, financedatabase source over an injected frame, plan filtering, coverage threshold, SCD idempotency, same-day in-place update, failed-write isolation.
- `_bmad-output/planning-artifacts/architecture.md` (modified) — FR-4 Requirements→Structure Mapping correction (OI-4).
- `_bmad-output/implementation-artifacts/1-8-gics-classification.md` (new) — this story spec, materialized retroactively from epics.md.

## Change Log

| Date | Change |
|---|---|
| 2026-06-06 | Materialized Story 1.8 spec from epics.md; implemented financedatabase GICS loader + SCD writer + coverage harness; added 10 tests (41 total green); applied OI-4 architecture mapping correction. Status → review. |
| 2026-06-06 | Code-review pass + fixes: same-day in-place SCD update (HIGH CHECK-violation bug), per-security error isolation, `sym classify` CLI command + coverage gate, two new tests, `read_active_figis` reuse. 43 tests green, ruff clean. Status → review. |
| 2026-06-06 | Added ISIN fallback to the GICS source (`SecurityIdentity`, `read_active_identities`) after the OpenFIGI exchCode resolution fix widened the universe; coverage 84.4% → 95.6%. Verified live. |
