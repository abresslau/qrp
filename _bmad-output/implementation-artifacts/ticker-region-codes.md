# Story: Qualified tickers — Bloomberg & FactSet exchange/region codes (ADS GY · ADS GR · ADS-DE)

Status: done

<!-- Andre 2026-06-22: default convention = **Bloomberg Region** ("ADS GR") — overrides the AC#4
ready-for-dev default of Bloomberg-Exchange. The region code (exch_code) already exists + is accurate,
so the default view disambiguates with zero dependence on the new venue seed. -->


<!-- Created via bmad-create-story 2026-06-22 (Andre: "show ticker also with the acronym for the exchange
and region… distinguish ADS Adidas vs ADS Bread Financial… Bloomberg Ticker Region + FactSet Ticker
Region… create Exchange and a region (based on Exchange). e.g. ADS GY (Xetra) and ADS GR (Germany),
Bloomberg convention"). Investigation found the exchange reference already carries most of this. -->

## Story

As a markets analyst,
I want tickers shown **qualified by their exchange and region** in Bloomberg and FactSet conventions
(e.g. **ADS GY** / **ADS GR** / **ADS-DE** for Adidas on Xetra, vs **ADS UN** / **ADS US** / **ADS-US**
for Bread Financial on NYSE),
so that I can unambiguously tell apart same-ticker securities across exchanges instead of guessing from a
bare "ADS".

## Background / current state (read before coding)

- **The `exchange` reference table (35 rows) already carries 2 of the 3 codes** — verify before adding
  anything (`packages/sym/migrations/deploy/exchange.sql` + `exchange_figi_exch_code.sql`):
  - `exch_code` — the **Bloomberg COMPOSITE / region code** (XETR→`GR`, XNYS/XNAS→`US`, XLON→`LN`,
    XPAR→`FP`, …). Added for OpenFIGI resolution, but it IS the "Bloomberg Ticker Region" the story wants
    ("ADS GR", "ADS US"). **Reuse it — do NOT add a new region column.** (Caveat: a few values are the
    OpenFIGI exchCode rather than the textbook Bloomberg composite — XFRA→`GF`, XAMS→`NA`, XCSE→`DC`,
    XTAE→`IT` — fine for our universe; note in dev notes, don't silently "fix" without confirming.)
  - `country_iso` — ISO-3166 alpha-2 (`DE`, `US`, `GB`, `JP`). This is the **FactSet region** for the
    `TICKER-REGION` convention ("ADS-DE", "ADS-US"). FactSet regions are ISO-2 for all 35 of our MICs —
    **reuse `country_iso`**; only add a `factset_region` override column if a real divergence shows up.
- **The MISSING piece = the Bloomberg VENUE / primary-exchange code** (the local-venue 2-char, distinct
  from the country composite): XETR→`GY` (Xetra), XNYS→`UN` (NYSE), XNAS→`UW` (Nasdaq), XASE→`UA`,
  ARCX→`UP`/`UF`, XLON→`LN`, XPAR→`FP`, XTKS→`JT`, XHKG→`HK`, XSWX→`SW`/`SE`, … This is what makes
  "ADS GY (Xetra)" and disambiguates **same-composite venues** — NYSE (`UN`) vs Nasdaq (`UW`) both have
  composite `US`, so the venue code is the only Bloomberg field that separates two US listings of one
  ticker. **Add `bbg_exchange_code` to `exchange` + seed all 35 MICs.**
- **Ticker display surfaces today** (where the qualified form should appear): the Explorer
  (`apps/web/app/sym/explorer/page.tsx` — columns Ticker / Name / Sector / Country(`country_iso`) /
  Exchange(`mic`) / Ccy …), the security detail page (`app/sym/securities/[figi]/page.tsx`), the
  portfolio pivot grid (`components/portfolio-pivot.tsx`, has a `Ticker` + an `Exch`=mic column), movers
  (`portfolio-movers.tsx`), heatmap tiles, donut. The Explorer + pivot are the primary asks.
- **The serving queries already join `exchange`** — the securities list (`_SEC_FROM` + the securities
  query in `services/api/.../sym/gateway.py`) and the analytics `composition()` both `LEFT JOIN exchange`
  for `country`/`country_iso`/`mic`. Adding `exch_code` + `bbg_exchange_code` to those SELECTs is the API
  surface change; the qualified ticker is **derived at read/display time** (ticker + code), never stored.
- **Migrations are sqitch** ([[reference_sqitch_deploy_docker]]) — add a deploy/revert/verify trio mirroring
  `exchange_figi_exch_code.sql` (ALTER TABLE + a `VALUES` seed UPDATE keyed by MIC + a `COMMENT ON COLUMN`).
- **Identity context** ([[project_identity_key_decision]], [[reference_openfigi_resolution]]): a security's
  venue is its `securities.mic`; `exchange.exch_code` already feeds OpenFIGI — DON'T repurpose/overwrite it.

## The worked example (the disambiguation goal — must hold end-to-end)

| Security | MIC | ticker | Bloomberg exch (`bbg_exchange_code`) | Bloomberg region (`exch_code`) | FactSet (`country_iso`) |
|---|---|---|---|---|---|
| Adidas | XETR | ADS | **ADS GY** | **ADS GR** | **ADS-DE** |
| Bread Financial | XNYS | ADS | **ADS UN** | **ADS US** | **ADS-US** |

(Both the region form `GR`≠`US` and the venue form `GY`≠`UN` disambiguate; the venue form additionally
separates two **US** listings — `UN` NYSE vs `UW` Nasdaq — that share composite `US`.)

## Acceptance Criteria

1. **`bbg_exchange_code` added to `exchange` (sqitch).** A new nullable `bbg_exchange_code TEXT` column on
   `exchange`, seeded for **all 35 current MICs** with the Bloomberg venue/primary-exchange code (XETR→GY,
   XNYS→UN, XNAS→UW, XASE→UA, ARCX→UP, XLON→LN, XPAR→FP, XTKS→JT, XHKG→HK, XSWX→SW, … — the dev sources
   the full 35 from a documented Bloomberg exchange-code reference and lists them in the migration), with a
   `COMMENT ON COLUMN`. deploy + revert + verify scripts, mirroring `exchange_figi_exch_code.sql`. The
   existing `exch_code` (region) and `country_iso` (FactSet) are reused, NOT duplicated.
2. **Qualified-ticker derivation (single source of truth).** One helper produces the three forms from
   `(ticker, bbg_exchange_code, exch_code, country_iso)`: `bbg_exchange` = `"{ticker} {bbg_exchange_code}"`,
   `bbg_region` = `"{ticker} {exch_code}"`, `factset` = `"{ticker}-{country_iso}"`. A null code degrades to
   the bare ticker (never "ADS null"/"ADS-"). Derived at read time — **never persisted**.
3. **API exposes the codes.** The securities list, the security detail, and the analytics composition
   payloads carry the per-row exchange codes (`bbg_exchange_code`, `exch_code`/region, `country_iso`) — or
   the three pre-formatted qualified tickers. Read-only; reuses the existing `exchange` joins (no N+1).
   `api-types` regenerated.
4. **Console shows the qualified ticker.** The Explorer ticker cell (AC priority #1) shows the qualified
   ticker per the selected convention; the portfolio pivot `Ticker` column + the security detail header
   follow. A **convention selector** (Bloomberg-Exchange · Bloomberg-Region · FactSet · None/plain),
   persisted to localStorage via `useSyncExternalStore` (the established prefs pattern — SSR-safe, stable
   server snapshot), default = **Bloomberg-Exchange**. Where space is tight, show the qualified ticker with
   the bare ticker still searchable; a tooltip lists all three forms.
5. **Honest fallback.** A security whose MIC has no `bbg_exchange_code` (or no exchange row) shows the bare
   ticker (and the region/FactSet forms where those codes exist) — never a fabricated or half-formed code.
   Search keeps matching the bare ticker regardless of the displayed convention.
6. **No regression.** OpenFIGI resolution (which reads `exch_code`) is untouched; the Explorer/pivot/detail
   keep working; `sym validate` + the exchange/securities tests stay green; `sqitch verify` passes;
   `ruff`/`tsc`/`eslint`/`vitest` clean.
7. **Tests.** (a) migration/verify: `bbg_exchange_code` exists + is seeded for the 35 MICs (the verify
   script); (b) the qualified-ticker helper: ADS/XETR→"ADS GY"/"ADS GR"/"ADS-DE", ADS/XNYS→"ADS UN"/"ADS
   US"/"ADS-US", null-code→bare ticker; (c) API returns the codes for a known figi; (d) web: the Explorer
   renders the qualified ticker under each convention + falls back to bare on a missing code.

## Tasks / Subtasks

- [x] Task 1 (reference data — sqitch, AC#1): added `bbg_exchange_code` to `exchange` with deploy/revert/
  verify + a plan entry, seeded **31/35** MICs (XNYS UN, XNAS UW, XETR GY, XLON LN, XPAR FP, XTKS JT, … —
  the US venue split UN/UW is the key disambiguator); **4 left NULL by design** (XASE, ARCX, XSHG, XSHE —
  venue code unconfirmed; the null-safe display falls back rather than guess — flagged for confirmation).
  `COMMENT ON COLUMN` added; deploy uses `ADD COLUMN IF NOT EXISTS` so it's a safe no-op over the
  already-applied dev DB. **NOTE:** Docker Desktop was down, so the formal `sqitch deploy` couldn't run;
  the exact deploy SQL was applied to the dev DB directly (verified) — run `sqitch deploy --verify` when
  Docker is up (idempotent no-op). Reused `exch_code` (region) + `country_iso` (FactSet), not duplicated.
- [x] Task 2 (qualified-ticker helper, AC#2): `apps/web/lib/ticker.ts` — `qualifiedTicker(codes,
  convention)` for the 3 conventions + `plain`, null-safe (bare ticker on a missing code, "—" on a null
  ticker) + `allQualifiedTickers` (tooltip) + `TICKER_CONVENTIONS`. 6 unit tests (the ADS/ADS case both ways).
- [x] Task 3 (API, AC#3): added `ex.exch_code` + `ex.bbg_exchange_code` to the securities list SELECT +
  row dict + `SecurityRow` model (reusing the existing `exchange` join); `api-types` regenerated. Explorer's
  source endpoint. (Detail/composition deferred with the pivot/detail surfaces — Open Q#3.) Tests updated.
- [x] Task 4 (console, AC#4/#5): a persisted **convention selector** on the Explorer (`useSyncExternalStore`
  localStorage, **default Bloomberg Region** per Andre) — Bloomberg·Region / Bloomberg·Exchange / FactSet /
  Plain; the Ticker cell renders the qualified ticker with an all-three-forms tooltip; null-safe bare-ticker
  fallback; **search still matches the bare ticker** (the query hits `tk.symbol_value`, unaffected by display).
  Scoped to the Explorer (primary surface); the pivot `Ticker` column + detail header are deferred (Open Q#3).
- [x] Task 5 (verify, AC#6/#7): API 165 + web 145 green; ruff/tsc/eslint clean; helper 6 tests; explorer API
  tests updated. Migration applied + DB-verified (ADS/XETR→GR/GY/DE; XNYS→US/UN; XNAS venue UW≠UN). Real-Chrome
  CDP `/sym/explorer`: default shows **ADS GR**, selector switches to **ADS GY** / **ADS-DE** / **ADS**,
  tooltip lists all three. (`sqitch verify` pending Docker; `sym validate` not re-run — schema-only add, no
  data-integrity surface touched.)

## Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Acceptance Auditor: all 7 ACs PASS except AC#7(d) PARTIAL (no automated Explorer render test). Edge Case
Hunter verified the 15-col gateway alignment, `_SEC_FROM` isolation, SSR-safety, search/sort untouched,
and the migration structure — all clean. 3 patches, the rest dismissed/deferred.

- [x] [Review][Patch] **Validate the stored convention** [apps/web/app/sym/explorer/page.tsx] — APPLIED: `getConv()` now validates against `TICKER_CONVENTIONS` and falls back to the default, so a stale `localStorage` value can't render a blank `<select>`. Covered by the new "recovers from a stale/invalid stored convention" Explorer test.
- [x] [Review][Patch] **Trim the codes in `qualifiedTicker`** [apps/web/lib/ticker.ts] — APPLIED: each code is `.trim()`'d and the guard tests the trimmed value, so a whitespace-only code degrades to the bare ticker (never "ADS " / "ADS- "). New helper test asserts it.
- [x] [Review][Patch] **Add a web Explorer render test (AC#7d)** [apps/web/__tests__/explorer-page.test.tsx] — APPLIED: a 4-test component suite (default "ADS GR", selector → "ADS GY"/"ADS-DE"/"ADS", null-code row → bare, all-three tooltip, stale-convention recovery). Closes the AC#7(d) gap.

Dismissed: **`useSyncExternalStore` hydration mismatch** (blind, "High") — false positive: `useSyncExternalStore` renders with `getServerSnapshot` during hydration then re-renders with the client snapshot (its whole purpose); mirrors the proven FX/theme/sidebar stores — the read-access layer confirmed SSR-safe. **FactSet `country_iso` not guaranteed ISO-2** (edge, Low) — false: `exchange.sql` has `CONSTRAINT exchange_country_iso_chk CHECK (country_iso ~ '^[A-Z]{2}$')`. **verify checks 7 MICs not 35** (auditor, Low) — correct by design (asserting 35 would fail on the 4 deliberate NULLs); mirrors the `exch_code` precedent. **`allQualifiedTickers` dedupe-by-bare** + **`plain` 4th convention** (Low) — intended/benign.

Deferred (→ deferred-work.md): **verify passes if an exchange row is entirely absent** (`NOT EXISTS … IS NULL`) — matches the `exchange_figi_exch_code` precedent exactly + the 35 rows are seeded; optional hardening. **Bloomberg venue-code accuracy** (XBOM IB / XNSE IS / XFRA GF / XTSE CT / XASX AT) — display-only, needs a Bloomberg cross-check; already flagged for Andre + the 4 NULLs. **Detail / Attention pages show the bare ticker** — the click-through path is where ADS↔ADS ambiguity matters most; the documented Open-Q#3 deferral, but the strongest reason to do the detail fast-follow. **Revert uses bare `DROP COLUMN`** — matches the precedent.

## Dev Notes

### Critical conventions (regressions if violated)
- **Reuse, don't duplicate.** `exch_code` = the Bloomberg region (already seeded, also feeds OpenFIGI — do
  NOT overwrite or repurpose it). `country_iso` = the FactSet region. Only `bbg_exchange_code` (venue) is new.
- **Qualified tickers are DERIVED, never stored** — a display/serving concern formatted from ticker + the
  exchange codes at read time. No new fact table, no denormalised column on `securities`.
- **Null-safe + honest** — a missing venue code → bare ticker, never "ADS null" / "ADS " / "ADS-". The bare
  ticker stays searchable under every convention ([[feedback_freshness_per_market]]-style honesty).
- **Migration discipline** — sqitch deploy/revert/verify mirroring `exchange_figi_exch_code.sql`; seed by a
  `VALUES (mic, code)` UPDATE; `sqitch verify` must pass; canonical naming.
- Read-only API, no new dependency, SSR-safe console prefs (`useSyncExternalStore` like the FX/theme
  stores), verify via headless Chrome ([[feedback_minimize_dev_churn]], [[feedback_headless_chrome_cleanup]]).

### Reference: the Bloomberg venue codes (seed these; dev to confirm the full 35 against a Bloomberg ref)
US split (the key disambiguator): XNYS `UN`, XNAS `UW`, XASE `UA`, ARCX `UP`. Europe: XETR `GY`, XFRA `GF`,
XLON `LN`, XPAR `FP`, XAMS `NA`, XBRU `BB`, XMIL `IM`, XMAD `SM`, XSWX `SW`, XSTO `SS`, XOSL `NO`, XCSE `DC`,
XHEL `FH`, XLIS `PL`, XWAR `PW`. APAC/other: XTKS `JT`, XHKG `HK`, XKRX `KS`, XTAI `TT`, XSES `SP`, XASX `AT`,
XBOM `IB`, XNSE `IS`, XSHG `C1`, XSHE `C2`, XNZE `NZ`. Americas/MEA: XTSE `CT`, BVMF `BZ`, XMEX `MM`, XJSE `SJ`,
XTAE `IT`. (Venue vs composite differ where a country has multiple venues — NYSE `UN`/Nasdaq `UW` vs
composite `US`; ASX `AT` vs composite `AU`; Toronto `CT` vs composite `CN`. Confirm each against a Bloomberg
EQS/exchange-code list before committing.)

### References
- [Source: packages/sym/migrations/deploy/exchange.sql + exchange_figi_exch_code.sql] — the table + the `exch_code` (region) precedent migration to mirror.
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — `_SEC_FROM` + `securities()` + `composition` callers that join `exchange` (add the code columns here).
- [Source: apps/web/app/sym/explorer/page.tsx] — the Ticker/Exchange/Country columns (primary display surface).
- [Source: apps/web/components/portfolio-pivot.tsx] — the `Ticker` + `Exch` columns; [securities/[figi]/page.tsx] — detail header.
- [Source: apps/web/app/monitor/fx/page.tsx] — the `useSyncExternalStore` localStorage prefs pattern for the convention selector.

## Open Questions (for Andre — defaults chosen, do not block)
1. **Default convention:** Bloomberg-Exchange ("ADS GY") by default, with a selector for Bloomberg-Region /
   FactSet / plain. Prefer a different default, or always show one form + the rest on hover?
2. **FactSet region = `country_iso`** (ISO-2). True for all 35 MICs here. OK, or do you have specific
   FactSet region codes that diverge (then I'll add a `factset_region` override column)?
3. **Surfaces:** Explorer + pivot + detail in this story. Also do movers / heatmap tiles / donut / signals /
   optimiser tickers now, or a follow-up?
4. **`exch_code` accuracy:** a few values are OpenFIGI exchCodes rather than textbook Bloomberg composites
   (XFRA→GF, XAMS→NA, XCSE→DC, XTAE→IT). Keep as-is (they still disambiguate), or normalise the region code
   to the strict Bloomberg composite (separate from the OpenFIGI use)?

## Dev Agent Record
### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22
### Completion Notes
- **The investigation paid off — 2 of 3 codes already existed**, so the real work was one column +
  wiring. `exch_code` (Bloomberg region, GR/US) and `country_iso` (FactSet, DE/US) were reused as-is; only
  the Bloomberg **venue** code (`bbg_exchange_code`, GY/UN/UW) is new. With Andre's default = Bloomberg
  Region, the default view disambiguates with ZERO dependence on the new venue seed.
- **Codes returned raw, formatted client-side** — the convention selector switches all three forms with no
  re-fetch (`qualifiedTicker` reads the per-row codes the API now carries).
- **Venue seed honesty:** seeded 31/35 with confident Bloomberg codes; left 4 NULL (XASE NYSE-American,
  ARCX NYSE-Arca, XSHG/XSHE Shanghai/Shenzhen segments) rather than guess — the null-safe display falls
  back to the region/bare ticker. **Andre should confirm/fill those 4** (a one-line seed UPDATE). The
  seeded venue codes are best-effort from standard Bloomberg conventions; worth a sanity pass on the
  less-common ones (XASX AT, XTSE CT, XBOM IB, XNSE IS).
- **Deployment caveat:** Docker Desktop was down, so the migration was applied to the dev DB directly via
  the exact deploy SQL (idempotent `ADD COLUMN IF NOT EXISTS`); the formal `sqitch deploy --verify` (Docker)
  is a safe no-op to run when Docker is up — the migration files + plan entry are committed.
- **Scope:** Explorer surface (the primary ask + where ADS disambiguation matters). Pivot `Ticker` column +
  detail header + composition payload deferred (Open Q#3 — say the word and I'll fast-follow).
### File List
- `packages/sym/migrations/{deploy,revert,verify}/exchange_bbg_exchange_code.sql` (new) + `migrations/sqitch.plan` (appended)
- `apps/web/lib/ticker.ts` (new — qualified-ticker helper) + `apps/web/__tests__/ticker.test.ts` (new)
- `services/api/src/qrp_api/modules/sym/gateway.py` + `router.py` (modified — securities exposes exch_code/bbg_exchange_code)
- `services/api/tests/test_sym_explorer.py` (modified — 15-col rows + code assertions)
- `apps/web/lib/api-types.ts` (regenerated)
- `apps/web/app/sym/explorer/page.tsx` (modified — convention selector + qualified ticker + tooltip)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story, Andre: "show ticker with exchange + region; Bloomberg/FactSet ticker-region; ADS GY/ADS GR"). Investigation: `exchange.exch_code` already = the Bloomberg region (GR/US), `exchange.country_iso` already = the FactSet region (DE/US); the only gap is the Bloomberg venue code. Plan: add `bbg_exchange_code` (venue: GY/UN/UW…) to `exchange` (sqitch, 35-MIC seed) + a derived qualified-ticker helper (3 conventions) + expose via the existing exchange joins + a persisted convention selector on the Explorer/pivot/detail. Derived not stored; reuse exch_code/country_iso. Status → ready-for-dev. |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Auditor: all ACs pass (AC#7d gap closed by the patch). 3 patches applied: validate the stored convention (no blank select), trim the codes in `qualifiedTicker` (no "ADS "/"ADS-"), add a 4-test Explorer render suite. Blind Hunter's "High" hydration finding was a FALSE POSITIVE (useSyncExternalStore renders with getServerSnapshot during hydration; mirrors the FX/theme stores — read-access layer refuted it); "FactSet not ISO-2" also false (country_iso CHECK exists). 4 defers → deferred-work.md (venue-code accuracy + the 4 NULLs; detail/attention click-through; verify-missing-row; revert IF EXISTS). web 150 green; ruff/tsc/eslint clean. Status → done. |
| 2026-06-22 | Dev complete → review (Andre: default = Bloomberg Region). Added `bbg_exchange_code` to `exchange` (sqitch trio + plan; seeded 31/35, 4 NULL by design) — applied to dev DB directly (Docker down; formal `sqitch deploy` is a no-op pending Docker). New `apps/web/lib/ticker.ts` helper (3 conventions, null-safe) + 6 tests; securities API exposes `exch_code`/`bbg_exchange_code` (+ `SecurityRow` model + api-types regen); Explorer gains a persisted convention selector (default Bloomberg Region) + qualified-ticker cell + all-three tooltip, bare ticker still searchable. Scoped to the Explorer; pivot/detail deferred (Open Q#3). API 165 + web 145 green; ruff/tsc/eslint clean. CDP `/sym/explorer`: ADS → "ADS GR" default, selector → "ADS GY"/"ADS-DE"/"ADS". Status → review. |
