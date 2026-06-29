# Retrospective — Portfolio Live Cockpit arc

**Date:** 2026-06-29
**Facilitator:** Amelia (Developer) · **Participant:** Andre (Project Lead)
**Scope:** The portfolio live cockpit story arc — a set of standalone stories (tracked inline in
`sprint-status.yaml`, not a numbered epic) built on top of Epic Q4 (portfolio weight store) and Q5
(portfolio analytics / returns). Trigger: closing `portfolios-live-autorefresh-parity` (review → done,
code-reviewed + CDP-verified 2026-06-29), the last lingering `review` story on the board.

> Format note: QRP is solo / owner-operated. This retro is run as a genuine facilitator↔Andre review
> grounded in the real story records — not the skill's fabricated multi-agent roundtable. No invented
> team conflicts, no time/hour estimates.

## Stories in the arc (all `done`)

| Story | What it delivered |
|---|---|
| portfolios-exposure-and-layout | Cockpit layout + exposure block |
| portfolios-live-heatmap-and-pizza | Live heat map + sector donut |
| portfolios-donut-responsive → donut-container-fit | Donut sized by container (Tailwind container queries), not viewport |
| portfolios-column-reorder | Drag-to-reorder grid columns (Pointer Events) — **the load-bearing descriptor-registry refactor** |
| portfolios-multi-column-sort | Ctrl/Cmd-click secondary sort keys |
| portfolios-grid-pivot-grouping | Flat-by-default grid; drag a column to a zone to group |
| portfolios-nested-grouping | Multi-level nested grouping (recursive group tree) |
| portfolios-live-grid-eod-returns | Live-rebased trailing returns in the grid |
| portfolios-live-returns-fix | "1D Chg only 3 names" → all 100 (the AR-9 gating saga) |
| portfolio-returns-skip-gated | 3rd surface of the same gating issue (Top-Movers MTD/YTD) |
| portfolios-live-header-pnl-declutter | Fit-to-viewport: P&L into header, drop risk panel |
| portfolios-live-autorefresh-parity | Auto-refresh parity with WEI/FX (this session's close-out) |

## What went well

1. **Reuse discipline was the spine of the whole arc.** Every story carries an explicit
   "Reuse — do NOT reinvent" section, and the grid genuinely evolved by *extension*, not rebuild:
   sector-group → generic `RowGroup` → nested groups → column reorder → group-by-drag, all on one
   component (`portfolio-pivot.tsx`). The **descriptor-registry refactor** in `column-reorder` (one
   ordered column-id list → one registry → every row maps the same order) was the keystone that made
   reorder / grouping / nesting cheap and safe afterward.
2. **"Copy the proven pattern" paid off — and just got validated.** The `autoSec`/`refreshedAt`/
   `useOnline` auto-refresh trio is identical across `heatmap-view`, WEI, FX, and the cockpit. Because
   they're byte-identical, the non-finite-interval fix this session was one guard applied verbatim to
   4 files, and the CDP verification exercised all 4 the same way. Consistency compounded.
3. **Honesty/freshness conventions held everywhere.** Live quotes derive-at-view, never persisted;
   "N/M priced · as of … · not stored" kept on every surface; EOD-vs-live framing consistent. No
   surface silently implied stored/real-time data it didn't have.
4. **Adversarial 3-layer code review earned its keep.** Across the arc it caught real defects
   (e.g. the FX `ccys` dedupe, the autorefresh non-finite guard) *and* reliably refuted false positives
   (the "stuck refreshing" and "sector double-count" claims this session and earlier), with the parity
   argument doing the triage work.
5. **CDP-as-verification became a dependable method.** With the local web toolchain unrunnable, headless
   Chrome behavioral checks (reused single instance, killed by command-line match) are now the standard —
   and they're real evidence, as the autorefresh verification (positive control + overflow probe across
   4 boards) showed.

## What was hard / recurring

1. **The AR-9 gating saga — a data-semantics gotcha that bit three surfaces.** `portfolios-live-returns-fix`
   *initially misdiagnosed* the 06-18 null returns as a "partial-EOD break, repair via recompute." The real
   cause: returns **gated by design** (unreviewed `prices_review` flags → `fact_returns.gated`, `pr` held
   null). The correct handling (`pr IS NOT NULL` skip-null, surface the last reviewed return) then had to be
   applied independently in **three** places (live grid, Top-Movers, analytics). Re-derived per surface;
   re-misdiagnosed once.
2. **A tech choice that didn't survive contact.** Native HTML5 DnD didn't fire from inside the header
   button → had to pivot `column-reorder` to Pointer Events mid-story. (Documented as a gotcha for the
   grouping stories that followed, which reused the pointer-drag — so the lesson did propagate.)
3. **The positional-rendering trap.** The pivot rendered columns positionally across 4 row types with
   `colSpan` aggregate rows — a naive "reorder the header only" edit would have desynced header/body and
   corrupted the totals. Solved by the registry, but it was the central risk of the arc.
4. **No local web toolchain = no automated gate.** *Every* story in the arc shipped with the same caveat:
   "web tsc/eslint/vitest not runnable locally (`apps/web/node_modules/.bin` empty) → CDP-verified instead."
   Real, persistent friction and latent risk — type/lint/test regressions can only be caught by inspection +
   browser, never by a local gate. (Reinstall is hazardous: it broke lightningcss before.)
5. **`review`-status drift.** `autorefresh-parity` was dev-complete 2026-06-22 but sat in `review` until
   2026-06-29 while newer, larger work (index-package, etc.) was built, reviewed, and merged on top of it.
   It got skipped, not because of any problem with it, but because nothing swept the `review` column.

## Carried technical debt (deferred, from `deferred-work.md`)

- **Live header title lacks `min-w-0`/`truncate`** — a pathological long portfolio name can force horizontal
  header overflow (normal names wrap fine).
- **`pct(null) → "—"` placeholder path uncovered** in the P&L strip suite (the declutter dropped the only
  null-rendering assertion).
- **Per-cell trailing-window staleness mark** not surfaced in the live grid.
- **Per-row store subscription** in the pivot Ticker column (idiomatic island pattern; immaterial at
  realistic book sizes).
- Sort-test strengthening; behavioral test for the all-gated `ret_date=None` guard (needs a SQL-capable
  fake conn).
- *(Resolved this session: the non-finite auto-refresh interval guard, swept across all 4 boards.)*

## Action items

1. **Fix or sanction the local web verification path** *(highest leverage)*. Today every web story ships
   type/lint/test-unverified locally. Either repair `apps/web` deps in a way that doesn't break lightningcss,
   or stand up a dedicated verification env / CI gate so `tsc`/`eslint`/`vitest` actually run somewhere
   before merge. Owner: Andre to decide the approach (the churn risk is why it's stayed open).
2. **Periodic `review`-sweep so stories don't drift.** A lightweight habit: before starting new work, close
   out anything sitting in `review`. `autorefresh-parity`'s week in limbo is the evidence.
3. **Make the gated-returns convention shared, not re-derived.** The `pr IS NOT NULL` / skip-gated rule was
   reimplemented on 3 surfaces and misdiagnosed once. Consider a single documented helper/convention (and a
   pointer from `[[project_partial_eod_repair]]`) so future return-reading surfaces inherit the correct
   semantics instead of rediscovering them.
4. **Quick polish pass on the small UI defers** — header title truncate + the null-placeholder test
   assertion are both tiny and close two real gaps.

## Readiness assessment

- **Functionally complete + verified.** All 12 stories `done`; the close-out story is code-reviewed and
  CDP-verified across all 4 live boards (incl. positive control). Changes are merged and pushed to
  `origin/main`; working tree clean.
- **Quality gate caveat:** local web toolchain still can't run `tsc`/`vitest` (action item #1). This is the
  one standing gap; it didn't block this arc but it's the thing most likely to let a regression slip.
- **No queued successor epic.** This arc sits on Q4/Q5, both done; there is no numbered "next epic" waiting
  on cockpit work. Next-epic preparation is N/A — the board is otherwise fully closed.

## Key takeaways

1. A single well-placed refactor (the column descriptor registry) de-risked an entire downstream arc —
   the reuse-first instinct was correct and repeatable.
2. The most expensive bug class wasn't UI — it was a **data-semantics misread** (gated returns), and it
   recurred because the rule lived in three hand-written copies instead of one convention.
3. The biggest standing risk is **process/infra, not code**: no local web test gate, and a `review` column
   that can silently strand finished work.
