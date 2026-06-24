# Story: Title-Case the sidebar module menu labels

Status: done

<!-- Created via bmad-create-story 2026-06-24 (Andre: "Make the menu Camel case monitor -> Monitor,
alt data -> Alt Data"). "Camel case" here means Title Case (the examples are Title Case). Scope = the
top-level rail/sidebar module labels. Standalone story, tracked inline in sprint-status. -->

## Story

As a QRP user,
I want the left-rail module names shown in **Title Case** ("Monitor", "Alt Data") instead of lowercase,
so that the navigation reads like a polished product menu.

## Acceptance criteria

1. Every left-rail module label renders in Title Case: `monitor`→**Monitor**, `macro`→**Macro**,
   `rates`→**Rates**, `commodities`→**Commodities**, `alt data`→**Alt Data**, `signals`→**Signals**,
   `backtest`→**Backtest**, `optimiser`→**Optimiser** (keep the British -ise spelling),
   `portfolios`→**Portfolios**, `analytics`→**Analytics**, `lineage`→**Lineage**.
2. `Data Monitor` is already Title Case — leave it unchanged. The app/brand name `QRP` (the
   `[branding] name` at the top of `platform.toml`, not a module) is untouched.
3. **`sym`→`Sym`** — Andre chose full uniformity (resolved 2026-06-24), so `sym` is Title-Cased to
   **Sym** like every other label. (This is a display label only; the package, DB, and `key` stay
   `sym` — nothing in code/data changes.)
4. Module **`key`** values are NOT changed (they are route ids: `/monitor`, `/altdata`, `/rates`, …).
   Only the display `name` changes. Routes, deep links, and the API module registry keep working.
5. The collapsed rail (2-letter glyph = `name.slice(0,2)`) now shows capitalized initials
   ("Mo", "Al", …) — expected and fine; confirm nothing looks broken.

## Decision (resolved 2026-06-24)
- **`sym` label → `Sym`.** Andre chose **full uniformity** (option 2): Title-Case every menu label
  including `sym`. Note this is the only label that's a package brand otherwise styled lowercase
  everywhere (memories: "sym is a peer", "call the project QRP") — but the change is **display-only**;
  the package name, database, route, and module `key` all remain `sym`.

## Developer context

This is a **pure display-label change in config** — no code logic, no new component.

### The labels come from `platform.toml`
The sidebar reads each `[[modules]]` entry's `name` and renders it verbatim
(`apps/web/components/sidebar.tsx`: `{it.name}` at ~line 217, plus `title=`/`aria-label=` and the
collapsed `it.name.slice(0,2)` glyph at ~line 197). The `key` (e.g. `altdata`, `monitor`) is the
stable route id and the subnav-registry lookup key — **do not touch keys**.

**Change:** edit ONLY the `name = "..."` lines of the `[[modules]]` blocks in `platform.toml` to
Title Case per AC#1. Current → target:

| key | current `name` | target `name` |
|-----|----------------|---------------|
| monitor | `monitor` | `Monitor` |
| data-monitor | `Data Monitor` | (unchanged) |
| sym | `sym` | `Sym` (resolved — full uniformity) |
| macro | `macro` | `Macro` |
| rates | `rates` | `Rates` |
| commodities | `commodities` | `Commodities` |
| altdata | `alt data` | `Alt Data` |
| signals | `signals` | `Signals` |
| backtest | `backtest` | `Backtest` |
| optimiser | `optimiser` | `Optimiser` |
| portfolios | `portfolios` | `Portfolios` |
| analytics | `analytics` | `Analytics` |
| lineage | `lineage` | `Lineage` |

### Guardrails / what must not break
- **Display-only, verified:** module `name` is used purely for display in the sidebar — it is NOT a
  lookup key (the `.name === "S&P 500"` matches elsewhere are benchmark/index names, unrelated;
  routes and the subnav registry key off `key`). So changing `name` is safe.
- **Do NOT** apply a blanket CSS `capitalize` / JS `.toUpperCase()`/title-cmap transform in the
  sidebar — set the explicit strings in `platform.toml` instead. A blanket transform would wrongly
  mangle real acronyms/brands (it would turn a future `FX`/`QRP`-style label into `Fx`/`Qrp`).
  Explicit per-module names keep full control — set each one, including `Sym`, in `platform.toml`.
- Confirm `platform.toml` is consumed by the API config loader (`services/api/.../config.py`) and the
  web sidebar only as a display name — no parser asserts a specific lowercase value.
- Check for any test that snapshots/asserts a module label (grep `apps/web` + `services/api/tests`
  for `"monitor"` / `"alt data"` as expected strings) and update it if present.

## Verification
- This is a trivial copy/label change (`feedback_scale_verification_to_change`): **no CDP needed**.
  Confirm the rail shows the Title-Case labels in the running console (**:3001** this session) — a
  quick visual/dump-dom check — and that clicking each rail item still routes (keys unchanged).
- No Python/TS logic changed; if any label-asserting test exists, run that suite. ruff/tsc N/A to a
  TOML data edit (none runnable locally anyway).

## Files
- `platform.toml` — Title-Case the `[[modules]] name` fields (per the table).
- (only if a test asserts a label) the relevant `apps/web` or `services/api` test.

## Out of scope
- Submenu / tab labels (WEI, FX, etc.) — already styled; not part of "the menu" Andre named.
- Renaming module `key`s or routes.

## Dev Agent Record

**Implemented 2026-06-24 (bmad-dev-story).** Title-Cased the 12 rail module `name` fields in
`platform.toml` (sym→Sym per Andre's resolved choice; `Data Monitor` already cased; `QRP` brand
untouched). Module `key`s, descriptions, routes, and the subnav registry are unchanged — the change is
display-label only. No code logic touched (the sidebar already renders `m.name` verbatim from
`/api/platform`), so no blanket capitalize transform was introduced.

**Verification (trivial copy change → no CDP, per feedback_scale_verification_to_change):**
- `qrp_api.config.enabled_modules()` returns the new names — confirmed all 12 Title-Case.
- Restarted the API (it caches `platform.toml` at startup); live `GET /api/platform` now returns
  `[(monitor, Monitor), (sym, Sym), (macro, Macro), (rates, Rates), (commodities, Commodities),
  (altdata, Alt Data), (signals, Signals), (backtest, Backtest), (optimiser, Optimiser),
  (portfolios, Portfolios), (analytics, Analytics), (lineage, Lineage)]` (+ Data Monitor).
- No test asserts the old lowercase labels: `sidebar.test.tsx` / `command-palette.test.tsx` use their
  own Title-Case mock fixtures (e.g. `name: "Macro"`); other `"macro"`/`"rates"` references are
  bucket/package **keys**, unaffected. (Web vitest not runnable locally — fixtures confirmed by read.)

### File List
- `platform.toml` — 12 `[[modules]] name` fields Title-Cased.

### Change Log
- 2026-06-24: Title-Cased rail module labels (incl. sym→Sym); keys/routes unchanged. Status → review.

## Senior Developer Review (AI) — 2026-06-24

**Outcome: Approve (clean).** Reviewed the uncommitted `platform.toml` change across three lenses
(applied inline — a 24-line config label edit doesn't warrant spawning adversarial subagents, per
`feedback_scale_verification_to_change`).

- **Blind (diff-only):** 12 `[[modules]] name` fields Title-Cased; `key`/`description`/`enabled`
  untouched; TOML parses (13 modules, all enabled). No correctness issue.
- **Edge:** `name` is display-only (not a lookup key); collapsed-rail `slice(0,2)` glyphs render fine;
  no empty/boundary case. `[platform] name = "QRP"` correctly untouched.
- **Acceptance Auditor:** AC1–AC5 all MET (12 Title-Case labels; Data Monitor & QRP unchanged;
  sym→Sym; keys unchanged — verified 0 key changes in the staged diff; collapsed rail cosmetic).

**Triage: 0 decision · 0 patch · 0 defer · 1 dismiss.**
- *Dismissed:* the `core.autocrlf=false` raw diff shows the whole file changed (CRLF/LF), but the
  **staged** diff (what commits) is exactly `12 insertions(+), 12 deletions(-)` — git normalizes the
  line endings. Not a real change.

No High/Med findings. Status → done.
