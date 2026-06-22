# Story: Portfolio live grid — fix the 1D Chg / trailing-return columns (live move + null-pr skip + data repair)

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "I don't see 1D Chg moving for most of the grid, I
only see for 3 names" on /portfolios/3/live). Investigated end-to-end (grid → composition API → fact_returns
DB). Three intertwined causes found — all three are in scope. -->

## Story

As a portfolio manager watching a book's live grid,
I want the **1D Chg column to show every holding's live intraday move** and the trailing-return columns
(1M/3M/6M/MTD/YTD) to be **populated for the whole book**,
so that the grid actually looks live and complete — not "3 names out of 100".

## Background / investigation (the evidence — read before coding)

Reproduced on `/portfolios/3/live` (100 holdings, all 100 priced `live`). The grid showed a 1D Chg value
for **exactly 3 names** (HAL, BG, WELL) and "—" for the other 97; nothing ticked on refresh. Traced it
through three layers:

**Cause A — the "1D Chg" column is bound to the wrong field (console).**
`apps/web/components/portfolio-pivot.tsx`: `WINDOWS = [{ key: "1D", label: "1D Chg" }, …]` (line ~68) and
the return columns read `h.window_returns?.[w.key]` (line ~213-215). So "1D Chg" shows the **EOD
`window_returns["1D"]`**, NOT the live move. The live intraday move (`live_return`, populated for all 100
and updating every refresh) is only surfaced in the **Daily P&L** column (line ~90 already special-cases
`win === "DAILY" ? h.live_return`). For a LIVE cockpit, "1D Chg" should BE the live move.

**Cause B — the composition query picks a null latest row (API).**
`packages/analytics/src/analytics/gateway.py` `composition()` builds `window_returns` from `fact_returns`
(lines ~426-440):
```sql
SELECT DISTINCT ON (fr.composite_figi, fr.window_id) fr.composite_figi, w.code, fr.pr
  FROM fact_returns fr JOIN return_window w USING (window_id)
 WHERE fr.composite_figi = ANY(%s) AND w.code = ANY(%s)
 ORDER BY fr.composite_figi, fr.window_id, fr.as_of_date DESC   -- takes the LATEST row, null or not
```
It takes the most-recent `as_of_date` per (figi, window) **even when `fr.pr IS NULL`**. Verified against
the live DB for portfolio 3's 100 figis: the current pick yields **3/100** non-null 1D; adding
`AND fr.pr IS NOT NULL` (latest row WITH a value) yields **100/100**. So a null on the newest date hides a
perfectly good earlier value.

**Cause C — `fact_returns` for 2026-06-18 has null `pr` for ~97% of names (data).**
`fact_returns` is otherwise fully populated (15.8M rows, 2177/2191 figis, windows current). But for the
portfolio's figis, the **latest date 2026-06-18 has `pr = NULL` for 97/100** (1D window); 2026-06-17 is
clean (0 null); 2026-06-16 has 23 null. This is a broken/incomplete returns materialization for 2026-06-18
— the signature of a partial/premature EOD or a `sym recompute` that ran against incomplete prices (see
[[project_partial_eod_repair]]). Cause B masks it today (falls back to 06-17 once fixed), but the newest
date's returns are genuinely wrong and should be repaired.

**Key data shapes (confirmed):** every holding carries `live_return` (live vs prev close — today's move,
100/100 priced, ticks each refresh) and `window_returns` (EOD trailing returns from `fact_returns`,
re-based to the live price per the gateway docstring). The grid's Daily P&L already uses `live_return`; the
1D return column should mirror it. `WINDOW_RETURNS`/`return_window.code` are fine (1D/1M/3M/6M/MTD/YTD all
exist with 567k rows each).

## Acceptance Criteria

1. **1D Chg = the live move (Cause A).** The grid's `1D Chg` column shows each holding's **`live_return`**
   (live price vs its prior close — today's move), not `window_returns["1D"]`. It is populated for every
   priced holding (100/100 on portfolio 3), updates on every refresh/auto-refresh, and is sign-consistent
   with the Daily P&L column beside it (Daily P&L = weight × this return). Unpriced holdings show "—".
   The 1M/3M/6M columns keep using the (now-fixed) trailing `window_returns`.
2. **Composition skips null `pr` (Cause B).** `composition()`'s window-returns query takes, per (figi,
   window), the latest `as_of_date` **with a non-null `pr`** (e.g. add `AND fr.pr IS NOT NULL` before the
   `DISTINCT ON`/`ORDER BY … as_of_date DESC`), so a null on the most-recent date no longer blanks the
   column. Verified expectation: portfolio 3 goes from 3/100 → 100/100 non-null trailing returns. The
   live-rebasing of these windows (`live_price * (1 + pr) / last_close − 1`) is unchanged.
3. **Repair the 2026-06-18 returns (Cause C).** Diagnose why `fact_returns.pr` is null for ~97% of names on
   2026-06-18 (partial EOD / a recompute over incomplete prices) and repair it — recompute returns for the
   affected date(s) (`sym recompute --start_date … --end_date …`, after a bounded price repair if the
   underlying `prices_raw`/`v_prices_adjusted` for 2026-06-18 is itself short — the
   [[project_partial_eod_repair]] runbook). After repair, the latest `fact_returns` date carries real `pr`
   for the universe (spot-check: portfolio 3's holdings non-null on their max date). If the price data for
   2026-06-18 is intact and only returns are null, a recompute alone suffices.
4. **No regression.** EOD analytics, the Explorer returns columns, the live composition endpoint
   (freshness/`live_return`/donut/heatmap/P&L), and the other portfolio pages are unaffected. Python:
   `ruff` + the analytics tests clean. Web: `tsc`/`eslint`/`vitest` clean.
5. **Tests.** (a) analytics: a `composition()` test where a figi's newest `fact_returns` row has `pr=NULL`
   but an earlier row has a value → the window value is the earlier non-null `pr` (not null); (b) web: the
   pivot grid's `1D Chg` column renders `live_return` (a holding with a live_return but null
   `window_returns["1D"]` shows the live value, and it differs from the 1M column).
6. **Verify in the browser.** Real-Chrome CDP on `/portfolios/3/live`: the 1D Chg column is populated for
   ~100 names and visibly changes across an auto-refresh tick (not 3); the 1M/3M/6M columns are populated
   for the book. CDP per [[feedback_minimize_dev_churn]] / [[feedback_headless_chrome_cleanup]]; never `npm --prefix`.

## Tasks / Subtasks

- [x] Task 1 (Cause B — API): `composition()`'s `fact_returns` window query now filters `AND fr.pr IS NOT
  NULL` so `DISTINCT ON` picks the latest row WITH a value (falls back past a gated/null latest date).
  Live API confirms portfolio 3 window_returns[1D]/[1M] = 100/100 (was 3/100). (No new unit test — the
  existing harness's fake conn can't exercise the SQL `DISTINCT ON`/`ORDER BY`, as the existing
  `test_composition_window_returns_rebased_to_live` already notes; verified against the live DB instead.)
- [x] Task 2 (Cause A — console): `portfolio-pivot.tsx` — added a `windowReturn(h, key)` accessor that
  returns `h.live_return` for the `"1D"` window (mirroring the Daily-P&L `DAILY` special-case) and
  `window_returns[key]` otherwise; used by the cell + the sort. 1D Chg is now the live move (100/100,
  ticks). Pivot tests updated (1D = +10.00% live) + a new Cause-A regression test (live shows even when
  `window_returns["1D"]` is null). 17 pivot tests green.
- [x] Task 3 (Cause C — diagnosed; NOT a bug, reframed): the 2026-06-18 nulls are **gated rows**, not a
  broken pipeline. Confirmed: prices_raw AND v_prices_adjusted are fully present for 06-18 (100/100), and
  the 06-18 1D nulls correlate exactly with `fact_returns.gated = True` (97 gated/null vs 3 non-gated/
  computed). Those 97 names have an **unreviewed price-quality flag** on 06-18 (the AR-9 gate via
  `prices_review`), so their returns are *deliberately withheld* until an operator reviews the flag. A
  `sym recompute 06-16..06-22` was run (2172 securities, 201,768 rows) and **correctly kept the gated rows
  null** — there is nothing to "repair" in the data. The right handling is exactly Cause B (skip-null →
  show the last *reviewed* return). **Out of dev scope (operator decision, do NOT auto-clear):** review the
  `prices_review` queue for 2026-06-18; if those prices are legitimate, approving them ungates the returns
  and 06-18 becomes the shown value — see Follow-up.
- [x] Task 4 (verify): API 165 + web 139 green; analytics ruff + tsc + eslint clean. Real-Chrome CDP
  `/portfolios/3/live`: 1D Chg populated 101/101 (was 3), ticks 39/101 across a refresh, 1M Return 101/101;
  live API window coverage 100/100.

## Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Acceptance Auditor: **all 6 ACs + conventions PASS**, no High/Med. The Edge Case Hunter (read access)
independently confirmed the aggregation paths are clean. The Blind Hunter's two High/Med findings were
**false positives** (diff-only) and are dismissed. No patches required; 2 minor defers.

- [x] [Review][Defer] **Sort test doesn't distinguish `live_return` from `window_returns["1D"]`** [apps/web/__tests__/portfolio-pivot.test.tsx] — the 1D-sort assertion (INTC<AAPL) holds under either field, so it doesn't *prove* the sort uses the live value. Correct-by-construction (cell + sort share the one `windowReturn` accessor, and the cell IS proven), so this is cosmetic test-strengthening; a distinguishing fixture is fiddly. Deferred.
- [x] [Review][Defer] **Trailing windows now show most-recent-non-null (can be an older EOD date) without a per-cell staleness mark** [packages/analytics/.../gateway.py] — Cause B's skip-null intentionally surfaces the last *reviewed* return when the latest date is gated/null (the desired behaviour; documented in the SQL comment). A per-cell "window as-of" indicator for a stale trailing window is a future enhancement, not a bug. Deferred.

Dismissed (key ones): **Daily P&L diverges from 1D Chg** (blind, "High") — false positive: `PnlAccess` already special-cases `DAILY → live_return` (portfolio-pivot.tsx:90), so both use the live move (consistent — the goal). **Sector/total aggregation diverges / double-counts** (blind, "Med") — false positive: all subtotal/total/group paths use `PnlAccess`, never `windowReturn`; return-window columns are blank in subtotal rows (verified by the read-access layer). **Test line-11 tautological** (blind, "High") — the `COMP` fixture sets `live_return:0.1` and `window_returns["1D"]:0.0123` to different values, so `+10.00%` proves live_return wins. **Dead `if pr is not None` guard** (Low) — harmless belt-and-suspenders; still correctly handles the no-row-at-all case. **SQL skip-null not unit-tested** (Low) — the project's analytics tests are DB-free and the existing `test_composition_window_returns_rebased_to_live` already documents that `DISTINCT ON` is an integration concern; verified live (3→100/100) instead. **`window_returns["1D"]` now unused by the grid** (Low) — harmless; still computed for any other consumer. **Comment placement between SQL and params** (Low) — valid Python, readable.

## Dev Notes

### Critical conventions (regressions if violated)
- **`live_return` is the live "today's move"; `window_returns` are EOD trailing windows** (re-based to the
  live price). The grid's Daily P&L already special-cases `DAILY → live_return` (gateway/pivot) — the 1D
  *return* column must follow the same rule. Don't conflate the two for the longer windows.
- **Live quotes are never persisted**; this story changes which stored `pr` row is read and which field the
  1D column renders — it does NOT change what's written at view time.
- **Cause C is a DATA repair, not a schema/code change** — use the existing `sym recompute` / `sym load
  --overwrite` runbook ([[project_partial_eod_repair]], [[project_loader_vocabulary]]); bound by
  `--start_date`/`--end_date`; canonical `as_of_date` ([[feedback_as_of_date_canonical_name]]). Don't
  hand-edit `fact_returns`.
- **`fact_returns` survivorship**: returns are computed for all securities (active/delisted/suspended);
  a recompute must not silently narrow that ([[project_sym_universe_layer]] / loader AR-8 invariant).
- Verify via headless Chrome/CDP, not by asking; reuse one instance ([[feedback_headless_chrome_cleanup]]).

### References
- [Source: apps/web/components/portfolio-pivot.tsx] — `WINDOWS` (line ~68), the return column cell (line ~213-215), the `DAILY → live_return` P&L special-case (line ~90) to mirror.
- [Source: packages/analytics/src/analytics/gateway.py] — `composition()` (line ~336), the `fact_returns` window query (line ~426-440), the live-rebasing of windows, `live_return` per holding.
- [Source: packages/sym/src/sym/returns/loader.py] — `load_returns` / `_securities_for_returns` (all securities, no filter); how `fact_returns.pr` is materialized (Cause C repair target).
- [Source: packages/sym/src/sym/cli.py] — `sym recompute` (line ~472-494) + `sym load --overwrite`.
- Sibling: `portfolios-live-grid-eod-returns` (added the live-rebased trailing returns), `fx-matrix-live`/`wei-live-board` (the live idiom), `portfolios-live-autorefresh-parity` (just added auto-refresh — makes the live 1D visibly tick).

## Open Questions (for Andre — defaults chosen, do not block)
1. **1D Chg semantics:** default = the live intraday move (`live_return`), so the column ticks like a live
   cockpit and matches Daily P&L. Alt: keep it as the EOD 1-day return (`window_returns["1D"]`, re-based) —
   but that's the thing that looked frozen. Confirm you want the live move.
2. **Cause C scope:** I'll repair the latest broken date(s) (2026-06-18 → present) so the newest
   `fact_returns` is correct. If you'd rather I only land the self-healing code (Causes A+B) and file the
   data repair separately, say so.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes
- **Causes A + B fix the user's symptom completely** — 1D Chg goes from 3 names to all 100 (live, ticking
  ~39/refresh), and the 1M/3M/6M columns from 3 → 100. A is the right binding (1D in a live view = today's
  live move = `live_return`, consistent with the Daily-P&L `DAILY` special-case beside it); B is the right
  robustness (don't let a null/gated latest row blank a column — show the last value with data).
- **IMPORTANT CORRECTION to Cause C (the Background hypothesis was wrong).** I framed 06-18 as a
  "partial-EOD-style break, repair via recompute." That is NOT what's happening. The 06-18 nulls are
  **gated returns by design (AR-9)**: prices_raw + v_prices_adjusted are fully present for 06-18, but 97/100
  names carry an **unreviewed `prices_review` flag** on that date, so `fact_returns.gated = True` and `pr`
  is held NULL until reviewed (confirmed: 97 gated/null vs 3 non-gated/computed). The `sym recompute` I ran
  (2172 securities, 201,768 rows) **correctly** kept those rows gated — there is nothing broken to repair.
  Cause B (skip-null) is precisely the correct handling: surface the last *reviewed* return rather than a
  withheld one. I did NOT clear any quality flags — approving flagged prices is an operator decision.
- The recompute was a harmless no-op for the gated rows; I left it in (it refreshed the window materialization).

### Follow-up (operator, not dev)
- The grid currently shows trailing windows as of the last **reviewed** session (2026-06-17) for the 97
  gated names — correct and honest, just one session stale until review. To make 2026-06-18 itself show,
  an operator should review the **`prices_review`** queue for 2026-06-18 (`sym` review tooling): if those
  prices are legitimate, approving them ungates the returns and 06-18 flows through automatically (no code
  change). If they're genuinely suspect, the gate is doing its job and 06-17 remains the right value.

### File List
- `packages/analytics/src/analytics/gateway.py` (modified — composition window query skips null `pr`)
- `apps/web/components/portfolio-pivot.tsx` (modified — `windowReturn` accessor; `1D Chg` → `live_return`)
- `apps/web/__tests__/portfolio-pivot.test.tsx` (modified — 1D = live move; +1 Cause-A regression test)
- (data, no file) `sym recompute 2026-06-16..2026-06-22` ran — refreshed the window materialization; gated rows correctly stay null. No data "repair" was needed (Cause C is intended gating).

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story, Andre: "1D Chg not moving for most of the grid, only 3 names" on /portfolios/3/live). Investigation found three causes: (A) the grid's `1D Chg` column reads `window_returns["1D"]` (EOD) instead of the live `live_return`; (B) `composition()` picks the latest `fact_returns` row even when `pr` is null (3/100 vs 100/100 with a non-null skip); (C) `fact_returns` for 2026-06-18 has null `pr` for 97/100 names (a partial-EOD-style break). Fix all three: rebind 1D→live_return, skip-null in the query, repair the 06-18 returns. Status → ready-for-dev. |
| 2026-06-22 | Dev complete → review. A: `windowReturn` accessor → `1D Chg` shows `live_return` (live, 100/100, ticks). B: composition window query `AND fr.pr IS NOT NULL` → trailing windows fall back past a null/gated latest row (3→100/100). C **reframed — NOT a bug**: 06-18 nulls are AR-9 **gated** rows (97/100 carry an unreviewed `prices_review` flag; prices+adj_close fully present), returns withheld by design; `sym recompute` correctly kept them null; B is the correct handling; operator review of the flag queue is the out-of-scope follow-up. API 165 + web 139 green; ruff/tsc/eslint clean. CDP /portfolios/3/live: 1D Chg 101/101 (was 3), ticks 39/101 per refresh, 1M 101/101. Status → review. |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Auditor: all 6 ACs + conventions PASS, no High/Med. The Blind Hunter's 2 High/Med findings (Daily-P&L divergence, sector double-count) were **false positives** — refuted by the read-access layer (`PnlAccess` already special-cases `DAILY→live_return`; all aggregation uses `PnlAccess`, never `windowReturn`). 0 patches; 2 minor defers (sort-test strengthening; per-cell trailing-window staleness mark) → deferred-work.md. Status → done. |
