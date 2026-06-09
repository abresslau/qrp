# Story QL.2: Auto-feeder rollout — derive lineage from live SQL

Status: done

## Story

As the **QRP owner-operator**,
I want **the lineage graph derived automatically from the SQL the loaders run (+ the live DB schema)**,
so that **lineage stays correct as the schema/code evolves and I stop hand-maintaining it** (the source of the QL-1 schema-drift defects).

## Context

QL-1 delivered the Dagster foundation with **hand-declared** deps/schemas — which drifted from
migrations (caught in code review). QL-1 also proved an auto-feeder prototype (`sql_capture.py` +
`derive.py`). QL-2 hardens that prototype (the 11 deferred items) and wires it in so the assets'
deps + column lineage are **generated**, not hand-written. Honest limit (from research): only
**table-level + pass-through-key** lineage is recoverable for QRP's Python-compute loaders;
computed-measure column lineage is out of scope.

## Acceptance Criteria

1. **derive.py hardened.** CTE aliases are excluded from source tables; placeholders (`%s` and
   `%(name)s`) are safely neutralized while preserving `%%`; `UPDATE`/`DELETE`/`MERGE`/`CTAS` are
   classified (writes recognized, CTAS not misread as a pure read); edge dedup unions `keys`;
   read→write correlation is statement-order-aware (a write depends only on reads before it).
2. **Schema-driven key detection.** Given the live Postgres schema, a read table contributes a
   pass-through key (`composite_figi`/`sym_id`) when that column exists in the table's schema —
   so `SELECT *` and unqualified columns no longer drop keys. Schema is keyed by bare table name
   (unique within QRP's per-package DBs today); cross-DB same-name qualification is deferred (QL-3).
3. **CaptureSession combines connections.** A loader that reads via one connection and writes via
   another (optimiser/signals/backtest) is captured into one shared sink, so `derive_edges` sees
   the full run and produces the cross-DB edge. All attribute sets (including `autocommit`)
   delegate to the real connection.
4. **Unit tests** cover classify/derive_edges for: INSERT…SELECT, INSERT…VALUES, UPDATE, CTE
   exclusion, cross-DB read+write, schema-based key detection, placeholder neutralization, dedup.
5. **Wired into Dagster.** Auto-derived deps + `dagster/column_lineage` replace hand-declared
   lineage for at least the cross-package edges. [DESIGN DECISION — see Dev Notes.]
6. **No regression** in QL-1: `dagster definitions validate` passes; the 31-asset catalog and
   GraphQL graph still resolve.

### Out of scope (→ QL-3)
- FK referential-layer auto-derivation + merge; Mermaid field-flow diagram; console/`platform.toml`
  integration; Dagster schedules.
- Computed-measure column lineage (not recoverable — Python compute).

## Tasks / Subtasks
- [x] Harden derive.py (AC1, AC2) — task #10
- [x] CaptureSession + attr delegation (AC3) — task #11
- [x] Unit tests (AC4) — 12 pass — task #12
- [x] Wire derived lineage into Dagster assets (AC5) — task #13 — Option A (offline generator)
- [x] Re-validate + GraphQL check (AC6) — 5 downstream assets now [auto-derived]

### Review Findings

_Code review 2026-06-09 (Blind + Edge + Acceptance). 7 patch, 6 defer, 4 dismissed._

**Patch (fix now):**
- [x] [Review][Patch] `classify`: `WITH … INSERT` (CTE before INSERT) drops real source tables and mislabels `basis="sql"` → lineage silently lost [derive.py:89-96]
- [x] [Review][Patch] `classify`/`derive_edges`: plain `DELETE` / no-`FROM` `UPDATE` fall to `basis="values"` and fabricate run-correlation edges to every prior read [derive.py:105-113,165-171]
- [x] [Review][Patch] `_spec` merge silently drops a correct hand-declared **cross-package** dep when derivation is incomplete → union derived ∪ full hand-declared instead of replacing [assets.py:431]
- [x] [Review][Patch] `_resolve` fabricates `("sym", name)` for any unknown source → dangling Dagster dep; guard to known asset keys only [assets.py:290-292]
- [x] [Review][Patch] generator silently degrades: `_try` swallows AttributeError/import drift, zero-dep tables omitted with no diagnostic; backtest recipe `_factor_at(…, "momentum")` hits the `else`/size branch (wrong factor key); connect() outside try (leak) [generate.py:32-65,103-114]
- [x] [Review][Patch] Spec accuracy: AC2 "schema keyed to avoid same-name collapse across DBs" is **not implemented** (flat bare-name keying; `_combined_schema` `.update()` collapses) — reword AC2 to match reality; AC3 "non-`autocommit`" wording misdescribes uniform delegation [QL-2 doc]
- [x] [Review][Patch] Tests: add DELETE/MERGE classification, WITH…INSERT sources, merge-union, `_resolve` guard [tests/test_derive.py]

**Deferred (low-reachability / future topology → QL-3 / deferred-work.md):**
- [x] [Review][Defer] CTAS branch also matches `CREATE VIEW … AS SELECT`; non-Schema/Table target → `target=None` edge silently lost [derive.py:98-103] — deferred (no loader emits)
- [x] [Review][Defer] MERGE / `DELETE…USING` / `UPDATE…FROM` target extraction is AST-order-dependent (could swap edge direction) [derive.py:105-107] — deferred (no loader emits)
- [x] [Review][Defer] `parse_one` ignores trailing statements in a multi-statement string [derive.py:72] — deferred (loaders single-statement)
- [x] [Review][Defer] `%%`/placeholder inside a string literal is rewritten (docstring "without corrupting" overstated) [derive.py:50-55] — deferred (no loader embeds them)
- [x] [Review][Defer] `UPDATE…FROM` sources not seeded into `reads_before` (asymmetry vs INSERT…SELECT) [derive.py:161-164] — deferred
- [x] [Review][Defer] `_combined_schema` qualify by (db,table) to remove latent cross-DB same-name collapse [generate.py:85-94] — deferred to QL-3 (DuckDB-federation era)

## Dev Notes

### DESIGN DECISION (AC5) — how derived lineage reaches Dagster
QRP loaders run in subprocesses (`sym` CLI) / API engines, so the parent Dagster process can't
sniff their psycopg directly. Options:
- **A — Offline generation (recommended):** a `lineage capture` step runs the loaders under
  `CaptureSession`, derives edges, and writes a generated `derived_lineage.py` (table→deps +
  key column_lineage) that `assets.py` imports. Deterministic, reviewable, no sym changes.
- **B — Runtime emission:** sym injects `CaptureSession` into its DB layer and emits captured SQL
  back; the asset emits `column_lineage` at materialization. More "live" but invasive to sym.
- **C — Hybrid:** offline now, runtime later.

### Source tree
- `packages/lineage/src/lineage/derive.py` (harden) · `sql_capture.py` (CaptureSession)
- `packages/lineage/tests/test_derive.py` (new)
- `packages/lineage/src/lineage/assets.py` (consume generated lineage)

### Testing
- `uv run pytest packages/lineage/tests` — pure static sqlglot, no live DB needed.
- `uv run dagster definitions validate -m lineage.definitions` — regression gate (AC6).

### References
- QL-1 + its Review Findings / `deferred-work.md` (the 11 items)
- Memory `project_data_manager_direction.md` (decisions, automatic-lineage research)

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Completion Notes List
- **Decision A implemented.** `generate.py` runs each downstream engine's read path under
  `CaptureSession` (no writes executed — targets synthesized from live schema), derives
  cross-package edges, writes `derived_lineage.py`. `assets.py` merges derived (cross-package,
  authoritative) + hand-declared (intra-package: solution→weight, factor→score, run→point,
  wiki_map→pageview). All 5 downstream targets render `[auto-derived]`; `backtest/point`
  auto-gained `fundamentals` (a real input the hand-model lacked).
- Regenerate with `uv run python -m lineage.generate`. sym-internal lineage stays declared (QL-3).
- Open: a fresh `bmad-code-review` over the QL-2 changes (generate.py + derive/capture hardening).

### File List
- `packages/lineage/src/lineage/derive.py` (hardened), `sql_capture.py` (CaptureSession),
  `generate.py` (new), `derived_lineage.py` (generated), `assets.py` (consume derived)
- `packages/lineage/tests/test_derive.py` (new, 12 tests)
