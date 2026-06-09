# Story QL.3: FK referential layer + field-flow visual + sym-internal capture

Status: done

## Story

As the **QRP owner-operator**,
I want **the intra-DB referential lineage auto-derived from Postgres foreign keys, a free visual of the join-key field flow, and sym-internal edges captured where possible**,
so that **even the within-package lineage stops being hand-declared, and I can *see* `composite_figi`/`sym_id` propagate without paying for Dagster+**.

## Context

QL-1 built the foundation; QL-2 auto-derived cross-package transform edges (downstream engines).
This story closes the QL-2 deferrals for the *referential* layer and the *visual*:
- Postgres **foreign keys** express intra-DB referential structure (securities→prices_raw,
  instrument→index_levels, universe→membership, …) — auto-derivable, retiring sym's hand-declared
  referential deps.
- The interactive cross-asset column-lineage graph is Dagster+ only; a generated **Mermaid**
  field-flow diagram is the free substitute.
- sym-internal *transform* edges (prices_raw→fact_returns) may be capturable non-invasively if sym
  exposes importable read helpers; else they stay hand-declared.

## Acceptance Criteria
1. **FK referential layer.** FK constraints across package DBs are introspected (Sqitch registry
   tables excluded), mapped child→parent to referential edges **among modeled tables only**, emitted
   to `derived_lineage.py`, and merged into asset deps with a distinct `referential` basis. No
   dangling deps (unknown tables dropped, not fabricated).
2. **Mermaid field-flow.** A generated Mermaid diagram renders the `composite_figi` and `sym_id`
   propagation across tables, written to a doc file; regenerable from the lineage data.
3. **sym-internal capture (best-effort).** If sym read helpers take a conn, generator recipes
   capture sym-internal transform reads non-invasively; otherwise sym-internal transform edges stay
   hand-declared and that's documented. No modification to the sym package.
4. **Tests + no regression.** Unit tests for FK edge mapping + Mermaid emission; `dagster
   definitions validate` passes; 31-asset catalog intact.
5. **Reviewed.** `bmad-code-review` run over QL-3; patches applied.

### Out of scope
- De-hub sym (task #14 — architecture P3 + `portfolios.db.hub()` rename): needs owner sign-off.
- Modeling unmodeled sym side-tables (price_gaps, prices_review, instrument_xref, …) as assets.
- Cross-DB schema qualification (still bare-name; QL-2 deferral).

## Tasks / Subtasks
- [x] QL-3a FK referential layer (task #15) — 17 FK edges auto-derived + merged
- [x] QL-3b Mermaid field-flow diagram (task #16) — `docs/field-flow.md`
- [x] QL-3c best-effort sym-internal recipes (task #17) — **not feasible non-invasively** (see notes)
- [x] Tests + regenerate + validate + review (task #18) — 22 tests pass, validate green, reviewed (8 patches applied)

### Review Findings

_Code review 2026-06-09 (Blind + Edge + Acceptance, autonomous). 8 patch (all applied), 4 defer, 2 dismiss._

**Patch (applied + verified):**
- [x] [Review][Patch] FK query → `pg_constraint` (one row per FK; old `constraint_column_usage` double-counted/misattributed composite & multi-FKs) [generate.py]
- [x] [Review][Patch] `edges()` dedups (guards `_EDGE_LIST` double-append on module reload) [assets.py]
- [x] [Review][Patch] FK/schema connect failures now WARN; `_write` won't clobber a good file on total-empty generation [generate.py]
- [x] [Review][Patch] FK 2-cycle guard in `_fk_parents` (mutual FKs can't make the dep graph cyclic) [assets.py]
- [x] [Review][Patch] FK edges recorded with a distinct `referential` basis (matches AC1 wording) [assets.py]
- [x] [Review][Patch] drift-guard test: `_MODELED` == SCHEMAS table names [tests/test_graph.py]
- [x] [Review][Patch] diagram polish: regex node-id sanitize, "key-carrying-edges-only" caption, `mkdir(parents=True)` [diagram.py]
- [x] [Review][Patch] comment the column_lineage invariant (derived carries only pass-through KEY_COLUMNS, so `column_name=k` is correct) [assets.py]

**Deferred:**
- [x] [Review][Defer] cross-DB bare-name keyspace (no namespacing) — same as QL-2 deferral; matters only on a future cross-DB table-name collision → DuckDB-federation era
- [x] [Review][Defer] `diagram` `parents[2]` path assumes the `src/` layout (fine today; breaks if installed as a wheel)
- [x] [Review][Defer] `analytics/metrics` (computed, schema-less) is omitted from the field-flow diagram — documented via the caption
- [x] [Review][Defer] `operate/job` db-label (`database="qrp"` vs group `operate`) — cosmetic, revisit with de-hub (#14)

**Dismissed (2):** test-count phrasing (20→22, both correct); composite-FK "no-op" note (subsumed by the pg_constraint patch).

## Dev Notes
- Reuse `derive.py`/`generate.py`; FK introspection query already prototyped (filtered for
  `changes/dependencies/events/projects/releases/tags`). Build referential edges only among names
  in `_NAME_INDEX` (the 30 modeled tables) to avoid pulling in unmodeled side-tables.
- Mermaid: emit `flowchart LR` from the key-flow edges (the data behind the removed `key_*` hack,
  now as a doc artifact instead of polluting the asset graph).
- Verify: `uv run python -m lineage.generate`; `uv run pytest packages/lineage/tests`;
  `uv run dagster definitions validate -m lineage.definitions`.

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09 (autonomous run)
### Completion Notes List
- **QL-3a FK layer:** `generate._fk_referential` introspects FK constraints across all package DBs
  (Sqitch tables excluded), keeps edges among the 30 modeled tables, emits `FK_REFERENTIAL` to
  `derived_lineage.py`; `assets.py` unions FK parents into every asset's deps (+ records an edge
  list). 17 referential edges auto-derived — the full sym-internal referential chain + intra-package
  edges (point←run, score←factor, weight←solution, observation←series, pageview←wiki_map). Retires
  the hand-declared referential deps.
- **QL-3b Mermaid:** `lineage/diagram.py` renders `composite_figi` + `sym_id` field-flow flowcharts
  to `packages/lineage/docs/field-flow.md` from the merged edge list — the free substitute for the
  Dagster+ column-lineage view.
- **QL-3c NOT done (documented):** sym's loaders (`load_returns`, `recompute_index_returns`,
  `rebuild_projection`, `recompute_market_cap_usd`, …) are **monolithic read+compute+write**
  functions — capturing their reads would execute heavy *mutating* recomputes. Not safe/non-invasive
  to run in a generator. sym-internal **transform** edges (prices_raw→fact_returns, index_levels→
  fact_index_returns) stay hand-declared; the FK layer covers sym-internal **referential** edges.
  Real sym-internal transform capture needs a sym-side hook → future work.

### File List
- `generate.py` (FK introspection), `assets.py` (FK merge + `edges()`/`key_tables()`),
  `diagram.py` (new), `derived_lineage.py` (regenerated: DERIVED + FK_REFERENTIAL),
  `docs/field-flow.md` (generated), `tests/test_graph.py` (new, 5 tests)
