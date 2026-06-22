# Story: WEI — backdate the World Equity Indices board to any as-of date

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a portfolio analyst,
I want to set an **as-of date** on the World Equity Indices board and see it exactly as it stood at
that historical close — every index's level, 1-day/5-day/MTD/1M/3M/6M/YTD/1Y/2Y/3Y/5Y change, and
52-week range computed *relative to that date*,
so that I can review how world markets looked on any past business day without leaving QRP.

## Background / context

The WEI board (`monitor/wei`, story `wei-world-equity-indices`) is currently anchored to the **latest**
session: `index_board()` uses `max(session_date)` as the anchor and computes everything from there.
This story makes that anchor a parameter — an **`as_of_date`** — so the board can be rewound to any
past date. Omitting it keeps today's behaviour (latest close) unchanged.

The warehouse already has the canonical pattern for this: **as-of resolution** — *"the value for date D
is the most recent observed value with `date ≤ D`."* (Used across FX `fx_rate(ccy, as_of)` and the
returns engine — [Source: _bmad-output/planning-artifacts/epics-fx.md#FR7, FR8].) Backdating the board
is the same idea applied per index: the anchor session for an index = its last `session_date ≤ as_of_date`,
and the prior session is the one before that. Because each index keeps its own calendar, this is
naturally **per-market** (a US index might anchor on the as-of date itself while a Tokyo index anchors a
day earlier) — consistent with `freshness_per_market` (per-member recency, never a single global "today").

## What QRP already has (reuse — do NOT reinvent)

- **`index_board()`** (`services/api/src/qrp_api/modules/sym/gateway.py`): the board gateway. TWO queries
  — (a) a ranked CTE (`row_number() OVER (PARTITION BY sym_id ORDER BY session_date DESC)` with
  `FILTER (WHERE rn = 1/2)`) for last + prior session per index; (b) a recent-levels query
  (`session_date >= (SELECT max(session_date) FROM index_levels) - 1900`) feeding the trailing-return
  bases + the 52w range + the 30-pt sparkline. Computes chg/chg_pct + the day-window returns via
  `_period_return(asc, N)` and the calendar windows via `_trailing_returns(asc)` (which anchor on
  `series[-1]`). MSCI aggregates filtered to NETR. **The anchor today is the global latest session — this
  story parameterises it.**
- **`_trailing_returns(series)` / `_period_return(series, days)`** (same file): PURE helpers — latest
  (`series[-1]`) vs the last observation on-or-before each window start. If the series is clipped to
  `≤ as_of_date`, `series[-1]` becomes the as-of anchor and **every window re-bases to the as-of date for
  free** (MTD/QTD/YTD anchor on the as-of's month/quarter/year; 1Y…5Y on as-of − N×365). No formula
  changes — only the input series and the per-index last/prev change.
- **`GET /api/sym/indexes/board`** + `IndexBoardRow` (`router.py`): the read endpoint + response model.
- **WEI page** (`apps/web/app/monitor/wei/page.tsx`): the board UI — one table, region `<tbody>` groups,
  16 columns, `Range52` bar, EOD "as of {boardDate}" header, per-row stale ● marker. `boardDate` is
  currently derived as `max(last_date)` across rows.
- **Canonical as-of resolution** (FX/returns): last value with `date ≤ D`; **canonical column/param/var
  name is `as_of_date`** ([Source: memory feedback_as_of_date_canonical_name] — never asof/as_of/today/date).
- **Date-axis / input conventions**: the console date charts use `lib/date-axis.ts`. A native
  `<input type="date">` is the lightest control and needs no dependency.

## Acceptance Criteria

1. **Board endpoint takes an optional `as_of_date`.** `GET /api/sym/indexes/board?as_of_date=YYYY-MM-DD`
   returns the board as it stood at that date. **Omitted ⇒ identical to today's behaviour** (latest
   session) — byte-for-byte the same response shape and values. The param is the canonical name
   `as_of_date` (a `date`); an invalid/garbage value is a 422 (FastAPI date coercion), never a 500.
2. **Per-index as-of anchoring.** For each index, the board's `last` = the level of its latest session
   with `session_date ≤ as_of_date`; `prev` = the session immediately before that; `last_date` = that
   anchor's date. `chg`/`chg_pct` = last vs prev. Indices with **no** session on-or-before `as_of_date`
   are omitted from the board (no fabricated zero row).
3. **All windows re-base to the as-of date.** 1D/5D/MTD/1M/3M/6M/YTD/1Y/2Y/3Y/5Y and the 52-week range
   are computed against the as-of anchor (MTD/QTD/YTD from the as-of's calendar; the day/year windows
   from as-of − N days; the 52w low/high over the trailing 365d **ending at** as-of). Achieved by clipping
   each index's level series to `session_date ≤ as_of_date` and reusing `_trailing_returns`/`_period_return`
   unchanged. `spark` = the last 30 points on-or-before as-of.
4. **The window query stays relative to as-of (no N+1).** The recent-levels pull is bounded
   `session_date <= as_of_date AND session_date >= as_of_date - 1900` (still one query for the whole
   board); the ranked last/prev CTE filters `session_date <= as_of_date` before ranking. When `as_of_date`
   is omitted the queries are exactly as today (latest-anchored).
5. **The WEI page has an as-of date control.** A native date picker in the board header; default = latest
   (empty/“Latest”), changing it refetches `?as_of_date=` and re-renders. The **"as of" header reflects the
   effective board date** (the max anchor date across rows, which equals or precedes the picked date), and
   a clear affordance resets to Latest. Picking a future date or clearing ⇒ latest. SSR-safe, no new dep,
   `react-hooks` lint clean (the existing newest-wins fetch guard pattern).
6. **Honest history + freshness.** Per-row stale ● still marks indices whose anchor date lags the board's
   effective date (per-market calendars). If the chosen date predates ALL index history, the board shows
   the honest empty state (not an error). Never invent a level or carry a value forward beyond what
   `index_levels` holds. Header still labelled EOD.
7. **No regression.** The latest-anchored board, the Indexes page, `index_levels` immutability, the read-only
   API, and all suites stay green. `ruff`/`tsc`/`eslint`/`vitest` clean.
8. **Tests.** (a) gateway `index_board(as_of_date=…)` from a fake conn: anchor = last ≤ as-of, prev = the
   prior, windows + 52w re-based to as-of, and an index with no on-or-before session is omitted; (b) the
   no-arg call is unchanged (existing assertions still pass); (c) route accepts `?as_of_date=` and rejects a
   bad value (422); (d) web: changing the date control changes the fetch URL and the header reflects the
   effective date (vitest, SSR-safe).

## Tasks / Subtasks

- [x] Task 1: Parameterise the gateway (AC: #1, #2, #3, #4) — `index_board(self, as_of_date: date | None = None)`.
  When set: ranked CTE gets `WHERE session_date <= %(as_of)s` before `row_number()`; recent-levels query
  gets `session_date <= %(as_of)s AND session_date >= %(as_of)s - 1900`. When `None`, the SQL is the exact
  prior latest-anchored strings (guarded via an `if as_of_date is not None` branch building the SQL + a
  `params` dict). Series clip falls out of the windowed query, so `_trailing_returns`/`_period_return` + the
  52w computation re-base for free; indices with no session ≤ as-of drop out via the inner JOIN.
- [x] Task 2: Route param (AC: #1) — `/indexes/board` gained `as_of_date: date | None = Query(None, …)`
  passed to `gw.index_board(as_of_date)`; bad input → 422 (FastAPI date coercion). Response model unchanged.
- [x] Task 3: WEI page as-of control (AC: #5, #6) — a header `<input type="date">` bound to `asOf` state; the
  fetch effect depends on `asOf` and appends `?as_of_date=` (newest-wins `alive` guard); default Latest with
  a "Latest" reset button; the "as of" header shows the effective board date + a "(backdated)" hint; future/
  empty ⇒ latest (server-side). Stale ● markers + empty state preserved.
- [x] Task 4: Verify (AC: #7, #8) — 152 api + 114 web tests green; ruff/tsc/eslint clean. Live API: `as_of=
  2024-09-30` re-anchors S&P (5762.48 vs latest 7383.74), re-bases YTD (+20.81% vs +7.86%)/1Y/52w
  (4117–5762 ending at the anchor); `?as_of_date=banana` → 422. Real-Chrome CDP `/monitor/wei`: picking
  2024-09-30 flips the header to "as of 2024-09-30" and re-anchors the rows; the Latest button restores
  the live board.

### Review Findings (code-review of c1736fe + 1c9534f, 2026-06-21)
- [x] [Review][Patch] `chg_pct` truthiness guard nulls a legitimate-zero level — fixed: `last_f is not None and prev_f` (divisor still guards /0) [services/api/.../sym/gateway.py]
- [x] [Review][Patch] Date-input `max` only applied when `!asOf` (unbounded after first pick) — fixed: bound to the captured `latestDate` always [apps/web/app/monitor/wei/page.tsx]
- [x] [Review][Defer] 1900-day lookback is anchored on as-of/global-max, not each index's own anchor — 3Y/5Y can read None for a pathologically-stale market (tests already assert honest-None; 75d cushion fine for daily data)
- [x] [Review][Defer] story #1 (`wei-world-equity-indices`) AC#3/Task3/File-List still say `/sym/wei` + `SYM_SUBNAV` — stale after the Monitor move (doc-only)
- [x] [Review][Defer] A server region outside `REGION_ORDER` is silently dropped from the board (`region_for` only emits the 4 known regions today; latent)
- Dismissed (3): `_period_return`/`_trailing_returns` consistency (verified identical guard+series); ISO-string date compare (safe, zero-padded); dropped Net-Chg/As-of columns (intended in-session design change).

### Review Findings — round 2 (code-review of 234d6b1 + c19763c + 8bfc1ed, 2026-06-21)
- [x] [Review][Decision] RESOLVED → **accept + monitor** (Andre). Loader stays best-effort (official close fires on overnight/pre-open/weekend runs; candle otherwise). Added `index-reconcile` as a non-critical final EOD step (drift monitor, warn-only; raises only on a ≥fail_bps break, never fails the night) so any candle-vs-official drift surfaces nightly. The `index_levels` latest-row `DO UPDATE` relaxation + the official-quote network call in the EOD path are accepted as scoped/justified.
- [x] [Review][Patch] Added tests: write-side official-close revision (overwrite latest = official, history = candle + DO NOTHING), the no-apply-when-date-mismatches case, and `official_quote` meta parsing (monkeypatched). [packages/sym/tests/test_benchmarks.py]
- [x] [Review][Patch] Picking a date equal to `latestDate` now keeps `asOf=""` (clean latest fetch, no redundant `?as_of_date=`); stale sort-test comment fixed. [apps/web/app/monitor/wei/page.tsx, __tests__/wei-page.test.tsx]
- [x] [Review][Defer] `levels_written` counts the no-op latest-row rewrite + the latest row is re-touched every run (cosmetic metric; the in-place revision is by design)
- Dismissed (6): mixed-type comparator (latent, type-stable cols); xref LIMIT 1 (one yahoo xref/index); chg_pct/chg at prev=0 (intentional); MSCI substring (MSCI-prefixed only); flat-52w sink (0/0 guard); duplicate-symbol collapse (invariant).

### Review Findings — round 3 (code-review of the Monitor arc, 2026-06-22)
- [x] [Review][Patch] The as-of SQL placeholder was `%(as_of)s` not the canonical `as_of_date` (the spec's Critical-conventions explicitly extends canonical naming to "SQL placeholder"; [[feedback-as-of-date-canonical-name]]). Renamed `params["as_of"]`/`%(as_of)s` → `%(as_of_date)s` in the as-of branch only (omitted/None path is untouched, byte-identical); reconciled the `test_indexes_route.py` string assertions. 11 api tests green [services/api/.../sym/gateway.py `index_board`; services/api/tests/test_indexes_route.py].
- Dismissed: round-1/round-2 items already patched/deferred (not re-litigated); the per-index 1900-day lookback caveat stays as deferred from round 1.

## Dev Notes

### Where this fits
One gateway signature change + one optional query param + a header control on an existing page. The math is
**already correct** — the trick is that `_trailing_returns`/`_period_return` anchor on `series[-1]`, so
feeding them a series clipped to `≤ as_of_date` re-bases every window with zero formula change. The only new
SQL is two `session_date <= as_of` predicates and swapping the `max(session_date)` window anchor for the
as-of bound. Sibling of `wei-world-equity-indices` (same board, anchor parameterised).

### Critical conventions (regressions if violated)
- **Canonical name is `as_of_date`** everywhere (param, var, SQL placeholder) — never asof/as_of/today/date
  [Source: memory feedback_as_of_date_canonical_name].
- **As-of resolution = last value with `date ≤ D`**, computed **per index** (per-market calendars,
  `freshness_per_market`) — never a single global "today", never a forward-fill past stored data.
- **Omitted `as_of_date` ⇒ today's exact behaviour** — the latest path must be provably unchanged (gate on
  the existing board test still passing untouched).
- **Immutable `index_levels`**, read-only API (`qrp_readonly`), no new dependency, SSR-safe + `react-hooks`
  newest-wins fetch guard, MSCI→NETR only, 52w range marker colour-coded like portfolio-live (emerald/rose/amber).
- **Verify via headless Chrome/CDP**; never `npm --prefix` [Source: memory feedback_minimize_dev_churn].
- **No Bloomberg IP** — functional reproduction only.

### Project Structure Notes
- Touch: `services/api/src/qrp_api/modules/sym/gateway.py` (`index_board` signature + SQL), `…/sym/router.py`
  (query param), `apps/web/app/monitor/wei/page.tsx` (date control), tests
  `services/api/tests/test_indexes_route.py` + `apps/web/__tests__/wei-page.test.tsx`.
- No migration, no new table, no new backend module. Monitor is a frontend view area; this is read-only over
  `index_levels`.

### References
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — `index_board()`, `_trailing_returns`,
  `_period_return`, the ranked-CTE + recent-levels queries (the anchor to parameterise).
- [Source: services/api/src/qrp_api/modules/sym/router.py] — `IndexBoardRow` + `/indexes/board`.
- [Source: apps/web/app/monitor/wei/page.tsx] — board UI, `boardDate`, fetch guard, `Range52`.
- [Source: _bmad-output/planning-artifacts/epics-fx.md#FR7-FR8] — canonical as-of resolution (`date ≤ D`).
- [Source: memory feedback_as_of_date_canonical_name, feedback_freshness_per_market, feedback_minimize_dev_churn].

## Open Questions (for Andre — defaults chosen, do not block)
1. **Control type:** default = a native `<input type="date">` (no dep, fast). Alt: a small calendar popover
   or quick presets (e.g. "1M ago / quarter-end / year-end"). Say if you want presets.
2. **Out-of-range date:** default = future/empty ⇒ latest; a date before all history ⇒ honest empty state.
   Alt: clamp to the earliest available session instead of empty.
3. **Scope:** this backdates the **WEI board** only. Want the same as-of control wired into the Heat map and
   the Indexes time-series page too (a shared monitor-wide as-of), or keep it WEI-only for now?
4. **URL state:** default = component state only. Want `?as_of_date=` reflected in the page URL so a backdated
   board is shareable/bookmarkable?

## Dev Agent Record

### Completion Notes
- The whole feature is one anchor parameterisation: clipping each index's level series to `≤ as_of_date`
  makes `_trailing_returns`/`_period_return` (which anchor on `series[-1]`) re-base every window with **zero
  formula change**. Only two SQL predicates + the window anchor changed.
- **Omitted path provably unchanged**: when `as_of_date is None` the gateway emits the exact prior SQL
  strings (the existing `test_index_board_chg_ytd_region_and_msci_net_only` passes untouched).
- Per-market as-of resolution: each index anchors on its own latest session `≤ as_of_date`; indices with no
  session on-or-before the date drop out via the inner JOIN (no fabricated row). EOD honesty preserved.
- Live-verified the math against real data (S&P at 2024-09-30 vs latest) and the 422 on a bad date.

### File List
- `services/api/src/qrp_api/modules/sym/gateway.py` (modified — `index_board(as_of_date=None)`)
- `services/api/src/qrp_api/modules/sym/router.py` (modified — `as_of_date` query param + `date` import)
- `apps/web/app/monitor/wei/page.tsx` (modified — as-of date control + as_of-dependent fetch)
- `services/api/tests/test_indexes_route.py` (modified — as-of gateway test + route 200/422 test)
- `apps/web/__tests__/wei-page.test.tsx` (modified — date-control refetch + reset test)

## Change Log
| Date | Change |
|---|---|
| 2026-06-21 | Dev complete → review. `index_board(as_of_date=None)` (per-index last session ≤ as-of + prior; windows/52w re-based by clipping the series; omitted ⇒ unchanged latest); `?as_of_date=` query param (422 on bad input); date control on `monitor/wei` with Latest reset + effective-date header. 152 api + 114 web tests green; ruff/tsc/eslint clean; live + real-Chrome CDP verified. |
| 2026-06-21 | Created story: backdate the WEI board to any `as_of_date`. Parameterise `index_board()` (per-index last session ≤ as-of + prior; windows/52w re-based by clipping the series to ≤ as-of and reusing `_trailing_returns`/`_period_return`); optional `?as_of_date=` query param; a date control on `monitor/wei` with a Latest default + effective-date header. Omitted ⇒ unchanged latest board. Read-only, no migration; canonical `as_of_date`, per-market as-of resolution, EOD honesty. Status → ready-for-dev. |
