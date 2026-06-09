# Story: De-hub sym — sym is a peer, not the hub

Status: done

## Story

As the **QRP owner-operator**,
I want **the "sym hub" framing removed from code, the architecture principle, and docs**,
so that **the platform consistently reflects that sym is a standalone peer package (a read-only upstream), not a privileged hub**.

## Context

Per Andre's directive (2026-06-08), sym is a peer, not the hub/warehouse/main package. The "hub"
framing is embedded in: a production function `hub()` (8 packages' `db.py`, returns a `sym`
connection), ~20 "sym hub" comments/docstrings, the architecture **P3** principle ("Dependencies
point inward to the hub"), several planning docs, and a stale README line. This story de-hubs all
of it. **Scope is framing only** — the dependency structure is unchanged (packages still read sym
as a read-only upstream); we are renaming/rewording, not re-architecting.

## Acceptance Criteria
1. `hub()` renamed to `sym_conn()` in all 8 package `db.py` modules, with a peer-framed docstring.
2. All imports + call sites updated (`from X.db import connect, sym_conn`; `sym_conn()`); no
   remaining `hub` identifier in `packages/**`.
3. "sym hub" / "the hub" comments + docstrings reworded to "sym package" / "read-only upstream".
4. Architecture **P3** principle revised to drop "hub" (sym = read-only upstream peer; deps still
   point at sym via the stable read contract).
5. Planning-doc "sym hub" references reworded; README stale "reserved fold-in slot" line corrected
   (sym is folded in).
6. **No regression:** all packages import; `dagster definitions validate` passes; lineage tests
   pass; the API service starts.
7. Reviewed (`bmad-code-review`); patches applied.

### Out of scope
- Changing the dependency structure / DB topology (packages still read sym).
- The `database="qrp"` vs group `operate` label nit (tracked separately).

## Tasks / Subtasks
- [x] Codemod: rename `hub()`→`sym_conn()` + reword "sym hub" in `packages/**` (22 files)
- [x] Revise architecture P3 + planning-doc refs (epics-roadmap) + README + services config + .env.example
- [x] Verify: grep clean, 19/19 modules import, gateway builds (40 routes), 22 tests, dagster validate
- [x] Code review + patches (2 applied)

### Review Findings
_Focused independent review 2026-06-09. 2 patch (applied), 3 defer._
- [x] [Review][Patch] `analytics/pyproject.toml` description "sym hub" → "sym package" (codemod only ran on `.py`) [analytics/pyproject.toml:4]
- [x] [Review][Patch] `.env.example` "sym is the hub" → "sym is a peer package (read-only upstream)" [.env.example:3]
- [x] [Review][Defer] `db/spikes/*` "sym hub" mentions — point-in-time spike artifacts, left intact
- [x] [Review][Defer] `__main__` `sym_conn = sym_conn()` self-shadow — valid + harmless (pre-existing `= hub()` pattern); cosmetic
- [x] [Review][Defer] broader "sym **warehouse**" framing (prd/epics-qrp/package.json/OVERNIGHT) — out of de-hub scope; sym genuinely is a market-data warehouse *internally*

## Dev Notes
- `hub()` is a one-line `return connect("sym")` wrapper — mechanical rename, low logic risk; the
  only danger is missing a call site (breaks the gateway import). Verify by importing every package
  + starting the API.
- Inventory: 8 `db.py` defs; routers (portfolios/signals/backtest/optimiser/analytics); engines
  (backtest/optimiser engine, signals/compute, altdata/ingest); gateway comments; P3 in
  `architecture-qrp-structure.md:47-49`; `epics-qrp-roadmap.md` (9 refs); README:16.

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-09
### Completion Notes List
- Codemod renamed `hub()` → `sym_conn()` across 8 packages + all call/import sites; reworded
  "sym hub" prose to "sym package / read-only upstream"; P3 principle revised (sym = peer, not
  hub); README intro + stale "reserved fold-in slot" line corrected; `epics-qrp-roadmap.md`
  reworded; `services/api/config.py`, `analytics/pyproject.toml`, `.env.example` hand-fixed.
- Verified: 19/19 modules import, gateway app builds (40 routes), 22 tests pass, dagster validate
  green; no "sym hub" framing remains outside immutable `db/spikes/` artifacts. Dependency
  structure unchanged — packages still read sym via a read-only connection (framing-only change).
- NOT committed (awaiting owner go) — left in the working tree for review.

### File List
- 8 `db.py` (sym_conn def) + routers (portfolios/signals/backtest/optimiser/analytics) + engines
  (backtest/optimiser) + signals/compute.py + altdata/ingest.py + gateways (comments) — 22 .py
- `services/api/src/qrp_api/config.py`, `packages/analytics/pyproject.toml`, `.env.example`
- docs: `architecture-qrp-structure.md` (P3 + anatomy), `architecture-qrp.md` + `epics-qrp-roadmap.md`
  ("sym hub" reword), `README.md` (intro + fold-in line)
