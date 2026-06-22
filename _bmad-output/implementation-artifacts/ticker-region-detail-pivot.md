# Story: Qualified tickers — detail + pivot fast-follow (the click-through path)

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "do the detail/pivot fast-follow"). The follow-up
deferred by `ticker-region-codes` (Open Q#3 + the code-review's strongest defer): the security detail
page and the portfolio pivot grid still showed the BARE ticker, inconsistent with the Explorer on the
click-through path — exactly where ADS↔ADS ambiguity matters. This extends the qualified ticker there. -->

## Story

As a markets analyst, I want the **security detail page and the portfolio pivot grid to show the same
qualified ticker** as the Explorer (honoring my chosen convention), so the disambiguation is consistent
everywhere I land — not just the Explorer list.

## Acceptance Criteria

1. **Shared convention store.** The convention preference is a single shared store
   (`apps/web/lib/ticker-convention.ts`, `useSyncExternalStore` + localStorage, default Bloomberg Region),
   honored by the Explorer, the detail page, and the pivot — set once, applies everywhere. The Explorer's
   local store is replaced by it (no behaviour change).
2. **Detail page.** `/sym/securities/[figi]` shows the qualified ticker in its `<h1>` per the convention,
   with the all-three-forms tooltip; bare-ticker fallback on a missing code. (Server component → a small
   `QualifiedTicker` client island reads the store.)
3. **Pivot grid.** The portfolio pivot `Ticker` column renders the qualified ticker (reuses the
   `QualifiedTicker` island); the figi fallback stays for a null ticker.
4. **API.** The detail (`security_detail`) + analytics composition payloads carry `exch_code` +
   `bbg_exchange_code` (+ the existing `country_iso`) per security/holding, via the existing `exchange`
   joins. `api-types` regenerated.
5. **No regression.** Explorer unchanged; sym/analytics/web suites + ruff/tsc/eslint green.

## Tasks / Subtasks

- [x] Task 1: extract the shared convention store (`lib/ticker-convention.ts`) + repoint the Explorer to it.
- [x] Task 2: `QualifiedTicker` client island (`components/qualified-ticker.tsx`) — reads the shared store,
  renders the convention form + all-three tooltip.
- [x] Task 3: detail API — `security_detail` SELECT + dict + `SecurityDetail` model carry the codes; the
  detail page `<h1>` uses `<QualifiedTicker codes={d} />`.
- [x] Task 4: composition API — the meta query + holding dict + `CompositionHolding` model (analytics
  router) carry `country_iso`/`exch_code`/`bbg_exchange_code`; the pivot `Ticker` cell uses the island
  (the web `CompositionHolding` type gains the 3 optional fields).
- [x] Task 5: verify — API 165 + web 150 green; ruff/tsc/eslint clean; api-types regenerated; CDP — detail
  `/sym/securities/<adidas>` h1 = "ADS GR · ADIDAS AG" (tooltip all three), pivot `/portfolios/3/live`
  Ticker column = "SNDK US" / "LITE US" / … (Bloomberg Region default).

## Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Clean review — **all 5 ACs PASS, no High/Med**. Both read-access layers independently verified the
high-risk Python column-alignment chain (the composition meta SELECT 15-col tuple/`_MISSING`/in-loop
unpack/holding-dict all agree in order; the `security_detail` 4-tuple `country[2]/[3]` is None-guarded;
the line-275 live-method `meta` is a separate 2-tuple, unaffected). The shared store is a faithful 1:1
extraction (same key, validation, SSR contract); the island sits only in data rows (not subtotal/total);
the 3 new `CompositionHolding` fields are optional (no fixture breakage); the `_SymConn` right-pad doesn't
mask drift. No patches.

- [x] [Review][Defer] **Per-row `useTickerConvention()` in the pivot grid** [apps/web/components/portfolio-pivot.tsx + qualified-ticker.tsx] — each Ticker cell's `QualifiedTicker` island calls the store hook, so an N-holding book registers N store + N `storage` listeners (vs the Explorer's one page-level subscription). Correct + idiomatic (the Edge Case Hunter rated it a non-issue) and immaterial for realistic books (≤ few hundred rows); if a very large book ever needs it, lift to one page-level `useTickerConvention()` + a Context the island reads. Deferred.

Dismissed/clean (notable): the **column-alignment HIGH-RISK category is clean** (verified by both layers); list-path codes predate this diff (the `ticker-region-codes` reuse — correct); `country_iso` default asymmetry across the two models is cosmetic (the gateway always populates it); the detail tooltip is on the ticker `<span>` not the `<h1>` (satisfies the AC).

## Dev Notes
- Reuses the `ticker-region-codes` helper (`lib/ticker.ts`) + codes; no new reference data, no migration.
- The convention is now GLOBAL (one store) — the Explorer's selector controls it; detail/pivot honor it
  (no per-page selector this pass). Composition meta unpack widened 12→15 cols (test `_SymConn` right-pads
  the 3 code columns; detail-test country fixtures widened to 4-tuples).
- Derived not stored; null-safe; server detail page uses a client island for the hook.

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22
### Completion Notes
- Clean extension of the reviewed `ticker-region-codes` foundation — one shared store + one reusable
  client island wired into 2 more surfaces + 2 more API payloads. No migration/reference data.
- The convention is global (set on the Explorer, honored on detail/pivot). A per-page selector on the
  pivot/detail could be a future nicety but wasn't requested.
### File List
- `apps/web/lib/ticker-convention.ts` (new — shared convention store)
- `apps/web/components/qualified-ticker.tsx` (new — client island)
- `apps/web/app/sym/explorer/page.tsx` (modified — use the shared store)
- `apps/web/app/sym/securities/[figi]/page.tsx` (modified — qualified h1)
- `apps/web/components/portfolio-pivot.tsx` + `portfolio-heatmap.tsx` (modified — pivot Ticker cell + type)
- `services/api/src/qrp_api/modules/sym/gateway.py` + `router.py` (modified — detail codes)
- `packages/analytics/src/analytics/gateway.py` + `router.py` (modified — composition codes)
- `apps/web/lib/api-types.ts` (regenerated)
- `services/api/tests/test_portfolio_composition.py` + `test_sym_explorer.py` (modified — fixtures widened)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created + dev complete → review (Andre: "do the detail/pivot fast-follow"). Shared convention store + `QualifiedTicker` island; detail page h1 + pivot Ticker column show the qualified ticker; detail + composition APIs carry the codes. API 165 + web 150 green; ruff/tsc/eslint clean; CDP-verified detail "ADS GR" + pivot "SNDK US". No migration (reuses ticker-region-codes). |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Clean: all 5 ACs pass, no High/Med; both read-access layers verified the column-alignment chain (composition 15-col + detail 4-tuple) correct. 0 patches; 1 defer (per-row store subscription in the pivot — idiomatic + immaterial at realistic book sizes) → deferred-work.md. Status → done. |
