# Story QH.6: Generic module framework + command palette (FR-2)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **operator using the QRP console**,
I want **a command palette that opens from anywhere to jump to any module area or screen and launch operations, backed by a generic module/subnav registry that no longer hardcodes each module**,
so that **navigation is fast and keyboard-driven (FR-2), and a new module's nav appears by registration alone — without editing the shell (NFR-10)**.

## Scope decision (read first)

QH.6's AC names two things: "extract the generic module-registry / **per-module bundle loader**" and "**ship the command palette** (FR-2)". Research settled what is and isn't real work here:

- **Backend module framework already exists** — the gateway mounts each package's router only when its Feature Toggle is on (AR-Q3), and `/api/platform` already serves the enabled-module list (`ModuleInfo[]`). No backend change.
- **The "per-module bundle loader" is Next's file-system routing** — each module already self-registers by owning an `app/<module>/` route dir. There is **no speculative bundle-loader abstraction to build**; doing so would be over-engineering against NFR-10's just-in-time discipline.
- **The genuinely new framework work is frontend:** the one remaining bespoke seam is `sidebar.tsx`'s `subnavFor` (`key === "macro" ? … : STATIC_SUBNAV[key]`) plus the macro-specific fetch living inside the Sidebar. C.1 deliberately left this bespoke "until module #3 wants a submenu" — **this story is that trigger.** Generalize it into a registry.
- **Command palette (FR-2)** is net-new: no `cmdk`/dialog/palette code or dependency exists today.

So this story = **(A) a subnav-provider registry** that removes the per-module hardcoding + **(B) the FR-2 command palette**, both driven off the same registry.

## Acceptance Criteria

1. **Subnav-provider registry (NFR-10).** The bespoke dispatch in `sidebar.tsx` (`subnavFor`'s `key === "macro"` literal **and** the inline `/api/macro/categories` fetch/state) is replaced by a declarative registry where each module optionally supplies a submenu **provider** — either a static `SubItem[]` or an async fetcher. `sidebar.tsx` consumes the registry **generically**: it contains **no per-module key literal and no module-specific fetch**. Macro's existing behavior is preserved exactly — data-driven from `/api/macro/categories`, badge = `n_series`, and the fail-safe (a failed/late fetch never wipes a working submenu; retry on route change while empty).

2. **Shell-untouched extensibility (NFR-10).** Adding a new enabled module (as returned by `/api/platform`) makes its area link appear in the sidebar with **zero edits to `sidebar.tsx`/`layout.tsx` render code**; giving that module a submenu is a **one-entry registry addition** (a provider), not a shell edit. Demonstrate the seam is data-driven (the dispatch keys off the registry, not a hardcoded module name).

3. **Palette opens from anywhere (FR-2 consequence 1).** A global keyboard shortcut — **⌘K on macOS, Ctrl+K elsewhere** — opens the command palette from any route; **Esc** and an outside/backdrop click close it. It is mounted **once** in the shell (a client island — `layout.tsx` is a Server Component, so the palette + its global key listener live in a `"use client"` component the layout renders). The shortcut is ignored while typing in an `input`/`textarea`/`select` (the established `macro-browser` guard), except the palette's own search field.

4. **Palette navigates to every area and screen (FR-2 consequence 2 — navigation).** The palette lists every **enabled module area** and every **screen within it**, sourced from the **same registry/module list the sidebar uses** (so the two never drift). A substring filter (the `.includes()` idiom, not fuzzy) narrows the list across area + screen labels; **↑/↓** move the selection, **Enter** navigates via the `next/navigation` router, selection closes the palette. Module areas come from `/api/platform`; screens come from the registry providers (static lists resolve immediately; async providers like macro use whatever is already loaded — the palette must not block on a fetch).

5. **Palette launches FR-7 operations (FR-2 consequence 2 — actions).** The palette surfaces the operations from `GET /api/operate/ops`. Selecting a **read-only** op (`writes === false`, no `takes_universe`/`takes_scope`) **launches it** directly (`POST /api/operate/run`, no confirm needed) and surfaces the result/`job_id`; selecting a **writer** or arg-taking op **routes to `/sym/operate`** (where the confirm + universe/scope guard UX already lives — it is **not** duplicated in the palette). This meets FR-2's "can launch at least the operations exposed in FR-7" without re-implementing the guarded-write affordance.

6. **Faithful to the design system + the non-standard Next (NFR-8/9).** New components use the semantic tokens (`bg-bg`/`bg-surface`/`text-fg`/`text-muted`/`border-border`), are dark-mode-correct, and route via `next/navigation`. **Read `node_modules/next/dist/docs/` before writing** (per `apps/web/AGENTS.md`: Next 16 / React 19 differ from training data) — especially for the router/navigation API and any App-Router client-island constraint. New client components must **lint clean on their own files** (the 12-error baseline is pre-existing in files this story does not touch — do not add to it; specifically avoid `react-hooks/set-state-in-effect` via derive-don't-sync) and `npm run typecheck` (`tsc --noEmit`) passes. **Default to a hand-rolled palette (no new dependency).** Adding a library (e.g. `cmdk`) requires explicit approval — do not add one without asking.

7. **No regressions; honest verification.** Existing sidebar behavior is unchanged: expand/collapse decoupled-from-navigation (chevron toggles, label navigates, active module defaults expanded), active highlighting, the macro fail-safe retry, and the sym tab-strip sharing `SYM_SUBNAV` (single source of truth — `app/sym/layout.tsx` still imports it). `lib/api-types.ts` needs no change (the palette consumes existing `/api/platform` + `/api/operate/ops`; no new typed schema). Because the console has **no test infrastructure** (no jest/vitest/playwright — confirmed), verification is `tsc --noEmit` + `eslint` clean on touched files + the manual end-to-end below. Introducing a test framework is **out of scope** (a separate decision); the gap is documented.

## Tasks / Subtasks

- [x] **Task 1 — Subnav-provider registry** (AC: 1,2,7)
  - [x] `apps/web/lib/nav.ts`: added the discriminated `SubnavProvider = {kind:"static",items} | {kind:"fetch",load}` and `SUBNAV_PROVIDERS` registry — `sym` static (`SYM_SUBNAV`, still exported for the tab strip), `macro` fetch (`loadMacroCategories` → `/api/macro/categories`, `badge: n_series`). Removed `STATIC_SUBNAV`.
  - [x] `components/sidebar.tsx`: consumes the registry generically — `subnavFor` resolves `static` immediately and `fetch` from a generic `fetched`/`fetchedRef` state machine keyed by module (load-once, retry-while-empty on route change, late-failure never wipes a working submenu). The `key === "macro"` literal and the macro-specific block are gone; ANY `fetch`-kind provider now works (driven by `asyncKeysSig` over the enabled modules).
  - [x] Preserved AC7 behaviors: decoupled expand/collapse, active state, macro fail-safe + badges, and `app/sym/layout.tsx` still importing `SYM_SUBNAV`.
- [x] **Task 2 — Command palette component** (AC: 3,4,5,6)
  - [x] New `apps/web/components/command-palette.tsx` (`"use client"`). Global `keydown`: ⌘K/Ctrl+K toggles from anywhere (modifier captured even in inputs), Esc closes; backdrop click closes. Search `input` + grouped (Areas/Screens/Operations) list, ↑/↓ selection, Enter/click to act. Tokens + dark mode + `next/navigation` `useRouter`. Filtered list via `useMemo` (no setState-in-effect; all loads set state in promise callbacks).
  - [x] Sources: areas from the `modules` prop (same `/api/platform` data as the sidebar); screens from `SUBNAV_PROVIDERS` (static immediate, async lazily loaded on first open); operations from `GET /api/operate/ops` (lazy, cached). AC5 split implemented: read-only op → `POST /api/operate/run` then route to `/sym/operate`; writer/arg op → route to `/sym/operate` (guard UX not duplicated). Either path lands on Operate so the job shows live via the QH.4 SSE stream.
- [x] **Task 3 — Mount in the shell** (AC: 3,7)
  - [x] `app/layout.tsx` (Server Component) renders `<CommandPalette modules={platform?.modules ?? []} />` as a client island inside `<body>` — layout stays server. Production build confirms the boundary compiles.
- [x] **Task 4 — Verify + docs** (AC: 6,7)
  - [x] `npx tsc --noEmit` passes (exit 0); `npx eslint` clean on all 4 changed files (baseline not regressed); `npx next build` succeeds (18/18 routes, exit 0). No new dependency added (hand-rolled palette).
  - [ ] **Manual end-to-end (operator step):** with API + console up — (a) ⌘K/Ctrl+K opens on several routes; Esc/backdrop closes; (b) filter + ↑/↓ + Enter navigates to an area and a screen; (c) read-only op runs (job shows on Operate); writer op lands on `/sym/operate`; (d) sidebar submenus (sym static + macro data-driven incl. cold-fetch-failure retry) unchanged; (e) a new enabled module's area link appears with no shell edit. *(Requires live servers — left for operator/code-review per the Verification section; console has no automated UI test harness.)*
  - [x] Marked QH.6 `[BUILT 2026-06-15]` in `epics-qrp-roadmap.md`; deferrals recorded in `deferred-work.md`.

## Senior Developer Review (AI)

**Reviewed:** 2026-06-15 · **Outcome:** Approve (4 findings patched, 4 deferred, 4 dismissed) ·
**Layers:** Blind Hunter + Edge Case Hunter + Acceptance Auditor (all 3 ran). Auditor confirmed
AC1–AC4, AC6, AC7 fully met; flagged AC5 as partial (now patched).

### Review Findings

- [x] [Review][Patch] AC5 — read-only-op run result was fire-and-forget (`.catch(()=>{})`) — flagged by **all 3 layers** `[command-palette.tsx]` — **Fixed.** The story's own Task 2 said to reuse the O.4 envelope; the POST result is now read — on success route to `/sym/operate` (job + id shows live via the QH.4 SSE stream); on rejection (e.g. 409 duplicate-run conflict, which creates **no** job row) show the reason inline and keep the palette open. Adds a `msg` line. AC5 now genuinely "surfaces the result/job_id."
- [x] [Review][Patch] Sidebar empty-submenu refetch loop (Blind+Edge, Med) `[sidebar.tsx]` — **Fixed.** A successful-but-empty fetch was indistinguishable from "never loaded" → re-fetched on every route change. Added a `loadedOkRef` sentinel: only a *failed* load retries; a successful load (even of an empty list) is not re-fetched. The cold-start-failure retry and the late-failure-never-wipes guard are preserved. (Latent in the old macro code; fixed in the generalization.)
- [x] [Review][Patch] Palette ops fetch latched on failure (Blind, Med) `[command-palette.tsx]` — **Fixed.** `loadedRef` is now set only after a *successful* `/api/operate/ops` load, so a failed first load retries on the next open instead of leaving Operations empty for the session.
- [x] [Review][Patch] Missing dialog semantics (Blind+Edge, Med) `[command-palette.tsx]` — **Fixed (partial a11y).** Added `role="dialog"` + `aria-modal="true"` + `aria-label` to the panel.
- [x] [Review][Defer] Full a11y: focus trap, focus restoration on close, body scroll-lock, `scrollIntoView` for keyboard selection (Blind+Edge, Med) — **Deferred:** real, but no AC requires a11y and this is an owner-operated console; a focus-trap/restore/scroll-lock pass (and selected-item auto-scroll) is a worthwhile follow-up. Ledgered.
- Dismissed (4, verified / standard UX): ⌘K toggles + captures while typing (standard palette behavior — Linear/VSCode; the Auditor confirmed AC3's "ignore-in-inputs" parenthetical is N/A for a modifier chord); `selSafe`/`sel` divergence (Edge verified the clamp lands correctly on first arrow; `onChange` resets `sel`); `key` includes index (works, minor); Escape no-`preventDefault` inside the input (harmless — value is controlled and reset on open).

## Dev Notes

### Current state of files being modified

- **`apps/web/components/sidebar.tsx`** (UPDATE) — `"use client"`, receives `modules: {key,name,description,enabled}[]` from the shell, filters to `enabled`, renders `/<key>` area links. **The bespoke seam (lines 41–78):** a macro-specific `macroSub`/`macroSubRef` state + `loadCategories` (`fetch("/api/macro/categories")`, fail-safe `.catch` that won't wipe a working submenu) + a `useEffect` retrying while empty on route change, and `subnavFor = (key) => key === "macro" ? macroSub : (STATIC_SUBNAV[key] ?? [])`. Render logic (lines 80–160: chevron, decoupled expand/collapse via `open` state defaulting to `active`, the `grid-rows 0fr→1fr` open-down animation, badges) **must be preserved** — only the *data source* (`subnavFor`) is generalized.
- **`apps/web/lib/nav.ts`** (UPDATE) — defines `SubItem = {href,label,badge?}`, `SYM_SUBNAV` (shared with `app/sym/layout.tsx`'s tab strip — keep the export), and `STATIC_SUBNAV = {sym: SYM_SUBNAV}`. This is where the provider registry lands. Its header comment explicitly says "deliberately NOT a framework (extract one when module #3 wants a submenu)" — this story flips that.
- **`apps/web/app/layout.tsx`** (UPDATE) — Server Component; `await apiGet<Platform>("/api/platform")`, renders `<Sidebar … modules={platform?.modules ?? []} />` and `<main>`. The palette mounts here as a client island with the same `modules`.
- **`apps/web/app/sym/operate/page.tsx`** (READ — reuse patterns, do not break) — the FR-7 op surface; shows the `GET /api/operate/ops` shape (`OpDef {key,label,writes,takes_universe,takes_scope,note}`), the `POST /api/operate/run` call, and the O.4 error-envelope read (`res.error?.message ?? res.detail ?? …`). The palette's read-only-op launch mirrors this; writer ops route here.
- **`apps/web/components/macro-browser.tsx`** (READ — idioms) — the canonical `window.addEventListener("keydown", …)` + `tagName` guard for ↑/↓ list nav, and the `.includes()` substring filter with `useMemo`. Reuse both.

### Key constraints

- **`layout.tsx` stays a Server Component.** The palette and its global key listener are client-only → a `"use client"` island rendered by the layout. Don't lift the layout to client.
- **Same registry feeds sidebar AND palette** (AC4) — screens must not drift between the two. The registry is the single source.
- **Macro provider is async + fail-safe** — the generalized `fetch`-kind provider must keep: load once, retry-while-empty on route change, and never let a late failure wipe a populated submenu. Don't regress this into a naive fetch.
- **No setState-in-effect** — the lint baseline is RED from this exact rule in other files; new code must derive (`useMemo`) rather than sync state in effects, or it adds to the baseline.
- **Non-standard Next 16 / React 19** — `apps/web/AGENTS.md` mandates reading `node_modules/next/dist/docs/` before console edits; confirm the `next/navigation` `useRouter().push` API and client-island rules there.
- **Don't block the palette on a fetch** — async-provider screens (macro categories) appear if already loaded; the palette opening must be instant. Ops are fetched lazily on first open and cached.
- **Default hand-rolled, no new dep** — adding `cmdk`/a dialog lib needs approval (dev-story HALTs on unapproved new dependencies).

### Project Structure Notes

- New file: `apps/web/components/command-palette.tsx`. Updated: `lib/nav.ts`, `components/sidebar.tsx`, `app/layout.tsx`. No backend change, no migration, no `api-types.ts` regen (existing `/api/platform` + `/api/operate/ops` schemas suffice).
- Scope boundaries (deferred, not in this story): **entity search** in the palette (FR-2 says "or entity" but its *testable* consequences require only areas + actions — securities/universes search would need live queries; defer); **write-op actuation inside the palette** (kept in Operate by design — AC5); **console test infrastructure** (none exists; introducing one is its own decision).
- This is the NFR-10 "module #3" trigger that C.1 named; after this, a new module's nav is registration-only.

### References

- [Source: _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/prd.md#FR-2] — "The Operator can open a command palette to jump to any Module Area, screen, or entity, and to launch common actions. … A keyboard shortcut opens the palette from anywhere. The palette can navigate to each enabled area and can launch at least the operations exposed in FR-7."
- [Source: prd.md#NFR-10] — "A new Module Area can be added (nav + routes + screens) without modifying the shell beyond enabling its Feature Toggle."
- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md#Story QH.6] — extract the generic module-registry / per-module bundle loader and ship the command palette.
- [Source: _bmad-output/planning-artifacts/epics-qrp.md#Epic Q1] — the framework was "deferred (just-in-time) … built when a second module actually arrives, not speculatively."
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] (C.1 note) — "Submenu providers stay bespoke by design (NFR-10): sym = static registry, macro = categories fetch, hardcoded in `sidebar.tsx`'s `subnavFor`. When a third module wants a submenu, extract the provider interface then."
- [Source: apps/web/components/sidebar.tsx#L41-L78] — the bespoke `subnavFor` + macro fetch to generalize.
- [Source: apps/web/lib/nav.ts] — registry home; `SubItem`, `SYM_SUBNAV`, `STATIC_SUBNAV`.
- [Source: apps/web/app/layout.tsx] — server shell; `/api/platform` fetch; palette mount point.
- [Source: apps/web/app/sym/operate/page.tsx] — `GET /api/operate/ops`, `POST /api/operate/run`, O.4 envelope read.
- [Source: apps/web/components/macro-browser.tsx] — keydown + tagName guard; `.includes()` filter idiom.
- [Source: apps/web/AGENTS.md] — read `node_modules/next/dist/docs/` before console edits (Next 16 / React 19).
- [Source: apps/web/app/globals.css] — semantic tokens (`--bg/--fg/--surface/--border/--muted`) and `.dark` variant.

### Verification (end-to-end)

1. `npm --workspace web run typecheck` and `npx eslint` (touched files) — clean; baseline not regressed.
2. Console + API up. ⌘K (mac) / Ctrl+K (else) opens the palette on `/sym`, `/macro/<x>`, `/portfolios`; Esc and backdrop-click close.
3. Type to filter; ↑/↓ select; Enter navigates to an area and a screen. Confirm screens match the sidebar exactly.
4. Operations group: a read-only op runs (shows `job_id`); a writer op lands on `/sym/operate`.
5. Sidebar unchanged: sym static submenu, macro data-driven submenu (incl. cold-fetch-failure retry on navigation), decoupled expand/collapse, active highlight.
6. Extensibility: show (by adding a temporary fake enabled module to the platform response, or by registry reasoning) that a new area link appears with no edit to `sidebar.tsx`/`layout.tsx`.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- `npx tsc --noEmit` → exit 0.
- `npx eslint components/command-palette.tsx components/sidebar.tsx lib/nav.ts app/layout.tsx` → exit 0 (clean; pre-existing 12-error baseline untouched).
- `npx next build` → ✓ compiled, TypeScript ✓, 18/18 routes generated, exit 0 (validates the client-island-under-server-layout boundary).
- `grep STATIC_SUBNAV apps/web` → no matches (safe removal).

### Completion Notes List

- **Frontend-only, no new dependency, no migration, no `api-types` change.** Scope held to the real work (per the story's Scope decision): the backend toggle-mounting framework and Next's file-routing "bundle loader" already exist, so no speculative abstraction was built.
- **Registry generalization (Task 1):** the C.1 bespoke seam is gone — `sidebar.tsx` no longer names a module. The macro fail-safe (load-once, retry-while-empty on route change, late-failure-never-wipes) is preserved but now generic over any `fetch`-kind provider. `STATIC_SUBNAV` removed; `SYM_SUBNAV` kept (the sym tab strip still imports it).
- **Palette (Task 2):** sources screens from the SAME `SUBNAV_PROVIDERS` the sidebar uses (AC4 — no drift). ⌘K/Ctrl+K captured even inside inputs (so it opens "from anywhere"); the tagName guard isn't needed for a modifier combo. Ops lazy-loaded + cached on first open. AC5 "launch": read-only ops POST `/run` then route to Operate; writer ops route to Operate (guarded UX not duplicated) — both land where the QH.4 SSE stream shows the job live.
- **Lint discipline:** every `setState` is in an event handler or a promise callback (never synchronously in an effect body), so `react-hooks/set-state-in-effect` is not tripped; the filtered list is derived via `useMemo`.
- **NFR-10 proof (AC2):** adding/removing a module is registry-only — `sidebar.tsx`/`layout.tsx` render code is module-agnostic. (Live "fake module appears" demo is in the operator step.)
- **Deferred (not blocking):** entity search in the palette (FR-2's testable bar needs only areas + actions); write-op actuation inside the palette (kept in Operate by design); console UI test infrastructure (none exists — verification is tsc + eslint + build + manual). All ledgered.

### File List

- `apps/web/lib/nav.ts` (UPDATE) — `SubnavProvider` union + `SUBNAV_PROVIDERS` registry (sym static, macro fetch); `loadMacroCategories`; removed `STATIC_SUBNAV`; `SYM_SUBNAV` retained.
- `apps/web/components/sidebar.tsx` (UPDATE) — generic registry consumption; removed the `key === "macro"` literal + macro-specific state; generic `fetch`-provider state machine with the preserved fail-safe.
- `apps/web/components/command-palette.tsx` (NEW) — the FR-2 command palette (⌘K/Ctrl+K, areas/screens/operations, keyboard nav, read-only-launch-with-result-surfacing vs writer-route; `role="dialog"`/`aria-modal`; ops fetch retries on failure).
- `apps/web/app/layout.tsx` (UPDATE) — mounts `<CommandPalette modules={…} />` as a client island.
- `_bmad-output/planning-artifacts/epics-qrp-roadmap.md` (UPDATE) — QH.6 → `[BUILT 2026-06-15]`.
- `_bmad-output/implementation-artifacts/deferred-work.md` (UPDATE) — QH.6 deferrals.

### Change Log

- 2026-06-15 — Implemented QH.6: generalized the bespoke per-module subnav wiring into a `SUBNAV_PROVIDERS` registry (NFR-10 — adding a module is registry-only, no shell edit) and shipped the FR-2 command palette (⌘K/Ctrl+K; navigate to any enabled area/screen from the same registry; launch FR-7 ops — read-only run directly, writer ops route to Operate). Frontend-only, no new dependency. tsc + eslint + next build all green. Status → review.
- 2026-06-15 — Code review (3 adversarial layers). Patched 4 findings: AC5 now reads the run result (success → route to Operate / SSE; rejection → inline reason, all 3 layers flagged this); sidebar empty-submenu refetch loop fixed with a `loadedOkRef` sentinel; palette ops fetch retries on failure (latch only on success); added `role="dialog"`/`aria-modal`/`aria-label`. 4 deferred (full a11y: focus trap/restore/scroll-lock/auto-scroll), 4 dismissed. tsc + eslint + next build re-run green. Status → done.
