# Story QL.4: Wire lineage into the QRP console

Status: done

## Story

As the **QRP owner-operator**,
I want **the lineage graph + field-flow surfaced as a native module in the QRP console**,
so that **I can see lineage from the same console as everything else (not only the separate Dagster UI)**.

## Context

The Dagster lineage layer (QL-1/2/3) runs as its own code location on :3333. This story exposes
it through the QRP console using the standard module convention: a gateway-resident
`/api/lineage` router (like `sym` — keeps the `lineage` package pure-Dagster), a `platform.toml`
entry (which auto-drives the sidebar nav), and a `/lineage` console page. The interactive graph
stays best-in-Dagster (link out); the console shows the table-level graph + the rendered
`composite_figi`/`sym_id` field-flow + stats.

## Acceptance Criteria
1. **API:** `GET /api/lineage/graph` returns the table-level edges (`source`, `target`, `basis`,
   group per endpoint) + summary stats; `GET /api/lineage/field-flow` returns the Mermaid for each
   join key. Router is gateway-resident (`qrp_api/modules/lineage/`), lazy-imports `lineage.*`
   (no dagster cost at API startup unless hit).
2. **platform.toml:** a `lineage` module entry (enabled) → appears in the sidebar automatically.
3. **Gateway:** mounts the lineage router when enabled; `services/api` depends on `lineage`.
4. **Console:** `/lineage` page fetches the two endpoints and renders: summary stats, the rendered
   Mermaid field-flow (composite_figi + sym_id), a grouped edge view, and a link to the live
   Dagster UI (:3333).
5. **No regression:** gateway builds + serves; `npm run gen:types` succeeds; web typechecks/builds;
   nav shows lineage.
6. Reviewed (`bmad-code-review`); patches applied.

### Out of scope
- Replacing the Dagster UI (the rich interactive graph stays there; we link to it).
- Auth/role gating on the lineage endpoints.

## Tasks / Subtasks
- [x] `diagram.mermaid_for(key)` raw-mermaid helper
- [x] Gateway-resident `/api/lineage` router + module (lazy lineage imports)
- [x] platform.toml entry + services/api dep + main.py mount
- [x] Console `/lineage` page (+ mermaid render component) + gen:types
- [x] Verify + code review (2 patches applied)

### Review Findings
_Focused independent review 2026-06-09. No blockers/majors. 2 patch (applied), minors noted._
- [x] [Review][Patch] edge-dedup key had no separator (latent `${source}${target}` collision) → use `${source} ${target}` (+ stable list keys) [app/lineage/page.tsx]
- [x] [Review][Patch] page used hand-rolled types → switched to generated `Schemas["LineageGraph"]`/`["FieldFlows"]` (honors the gen:types contract) [app/lineage/page.tsx]
- [x] [Review][Defer] `mermaid.initialize` per-render + hard-coded dark theme (cosmetic; doesn't follow light toggle); also wrapped derived grouping in `useMemo` while patching

## Dev Notes
- Router lazy-imports `lineage.assets` (`edges`, `key_tables`, `SCHEMAS`) + `lineage.diagram`
  inside handlers (defer dagster import off the API startup path).
- Edge endpoints are bare table names; group inferred via `{table: db for (db,table) in SCHEMAS}`.
- Console renders mermaid client-side (add `mermaid` to the web workspace; dynamic import in a
  client component to avoid SSR issues).
- Verify: API JSON; `cd apps/web && npm run gen:types`; `npm --workspace web run build` (or tsc).

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Completion Notes List
- Gateway-resident `/api/lineage` router (`graph` + `field-flow`, lazy `lineage.*` imports so
  dagster stays off the API startup path); `platform.toml` entry auto-drives the sidebar nav;
  console `/lineage` page renders stats, the rendered Mermaid field-flow (composite_figi + sym_id),
  a grouped edge view, and a link to the live Dagster UI.
- Verified live: API + console up; `/api/lineage/graph` (31 assets, 58 edges) + `/field-flow` 200;
  `platform.modules` includes `lineage`; `console /lineage → 200`; `gen:types` succeeded (lineage
  in api-types); `npm --workspace web run typecheck` clean. Reviewed; 2 patches applied.
- Scope respected: links to the Dagster UI (doesn't replace it); no auth/role gating added.

### File List
- `services/api/src/qrp_api/modules/lineage/{router.py,__init__.py}` (new), `main.py` (mount)
- `packages/lineage/src/lineage/diagram.py` (`mermaid_for` helper)
- `platform.toml` (lineage module), `services/api/pyproject.toml` (lineage dep + de-hub desc)
- `apps/web/app/lineage/page.tsx` (new), `apps/web/components/mermaid.tsx` (new),
  `apps/web/package.json` (mermaid), `apps/web/lib/api-types.ts` (regenerated)
