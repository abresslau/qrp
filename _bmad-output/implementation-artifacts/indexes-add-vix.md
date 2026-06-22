# Story: Add VIX to the Indexes page

Status: ready-for-dev

<!-- Created via bmad-create-story 2026-06-22 (Andre: "add VIX to the indexes page"). Surfaces the
CBOE Volatility Index on the sym Indexes page. VIX is ALREADY ingested in the `macro` module
(`MKT:VIX`, ~6,657 obs, ^VIX via yfinance) but is NOT in the sym index spine (`index_levels` /
benchmark registry) that feeds the Indexes page + WEI board — this adds it there natively. -->

## Story

As a markets analyst,
I want the **CBOE Volatility Index (VIX)** to appear on the sym **Indexes page** alongside the equity
indices, with its level time-series chart,
so that I can track the market's "fear gauge" from the same index surface I use for the equity boards.

## Background / current state (read before coding)

- **The Indexes page is data-driven off the benchmark registry.** `apps/web/app/sym/indexes/page.tsx`
  lists every instrument from `GET /api/sym/indexes` and, for the selected one, draws a level
  time-series chart + trailing returns + a monthly calendar-returns table from
  `GET /api/sym/indexes/{sym_id}/levels`. **No page or API code is needed for the basic add** — an
  instrument with levels appears automatically.
- **The registry** (`packages/sym/src/sym/benchmarks/levels.py`): `BENCHMARKS: tuple[Benchmark, …]`.
  `Benchmark(name, currency, yahoo_symbol=None, msci_code=None, variant=None, region=None)`. Yahoo-symbol
  entries (e.g. `^GSPC`, `^FTSE`) load levels via yfinance through `load_index_levels(conn,
  YahooIndexLevelSource())`, driven by the **`sym benchmarks` CLI** (`_cmd_benchmarks`: ensures the
  instrument + xrefs, loads levels, attaches index FIGIs, links universes, recomputes index returns).
- **`^VIX` is reachable in this environment** — the `macro` markets feed already pulls it
  (`packages/macro/src/macro/ingest.py:78` → `("^VIX","MKT:VIX","Volatility index (VIX)","index","US","markets")`,
  ~6,657 obs as of the 2026-06-22 refresh). So no source probe is needed; the same `^VIX` yfinance
  symbol feeds this.
- **The WEI board** (`index_board()` gateway → `/monitor/wei` page) renders EVERY index instrument
  grouped by region with up/down (emerald/rose) colour on net-chg/%chg/YTD. Adding VIX to `BENCHMARKS`
  would place it there too — see the critical design notes.

## Acceptance Criteria

1. **VIX is in the benchmark registry + `index_levels`.** A `Benchmark` entry for the CBOE Volatility
   Index (`yahoo_symbol="^VIX"`) is added to `BENCHMARKS`; running `sym benchmarks` loads its level
   history into `index_levels` (immutable EOD levels keyed on its own `sym_id`, yahoo xref `^VIX`),
   and `sym benchmarks` stays idempotent (re-run = no dup instrument, no dup levels).
2. **VIX appears on the Indexes page.** `GET /api/sym/indexes` lists VIX (name, currency, n_levels,
   first/last date, last_level); selecting it draws its level time-series chart and stats. Verified
   real-Chrome CDP at `/sym/indexes`.
3. **VIX return framing is honest — it is a LEVEL index, not an investable return.** The trailing
   metrics the page computes (YTD / 1Y / **annualised CAGR** / since-inception / monthly calendar
   returns) are mathematically % level-changes but are **semantically meaningless as investment
   returns** for a mean-reverting volatility index. Do NOT present VIX with the same
   "annualised CAGR" investment framing as the equity indices. Minimum bar: a clear on-page note /
   label that VIX figures are **level changes, not total returns**, and suppress or relabel the
   multi-year **CAGR/annualised** cards for it (a level change annualised as CAGR is nonsense). The
   level chart + absolute level + 1D/period **% level change** are the honest, useful surfaces.
4. **VIX does NOT pollute the WEI equity board (default).** The WEI board (`index_board()` /
   `/monitor/wei`) is an **equity** board with up=good/emerald, down=bad/rose colour — semantics that
   **invert** for VIX (VIX up = market fear). VIX must be **excluded from the WEI board** by default
   via a clean, sourced mechanism (e.g. an `asset_class`/`category` field on `Benchmark` —
   `"equity"` default vs `"volatility"` — with `index_board()` filtering to equity), NOT a hardcoded
   name check in the React page. (If Andre later wants a dedicated volatility tile, that's a separate
   story — see Open Questions.)
5. **No regression.** Existing 25 equity indices, the Indexes page, the WEI board + backdating, the
   `index_levels` immutability, `index-reconcile`, and the macro `MKT:VIX` series are all unaffected.
   sym + api + web suites green; `ruff`/`tsc`/`eslint`/`vitest` clean.
6. **Tests.** (a) registry: VIX entry present, has `^VIX` yahoo xref, and its `category` excludes it
   from the equity set; (b) gateway: `index_board()` does NOT include VIX (equity-only filter) while
   `indexes()` (the Indexes-page list) DOES; (c) web: the Indexes page renders VIX with the
   level-not-return labelling and without an annualised-CAGR investment card.

## Tasks / Subtasks

- [ ] Task 1: Registry entry + asset-class field (AC: #1, #4, #6a) — add a `category`/`asset_class`
  field to `Benchmark` (default `"equity"`); add `Benchmark("CBOE Volatility Index (VIX)", "USD",
  yahoo_symbol="^VIX", region="Americas", category="volatility")`. (Currency `"USD"` is a convention —
  VIX is unitless index points; document the white lie in a comment. Region `"Americas"` for the
  registry derivation even though it's excluded from the board.)
- [ ] Task 2: Exclude non-equity from the WEI board (AC: #4, #6b) — `index_board()` filters to
  `category="equity"` (or excludes `"volatility"`); `indexes()` (the Indexes-page list) keeps ALL.
  Mirror the existing MSCI-NETR-only filtering idiom; data-driven, no React name-check.
- [ ] Task 3: Honest VIX framing on the Indexes page (AC: #3, #6c) — when the selected instrument is
  a volatility index, label its figures "level change (not total return)" and suppress/relabel the
  multi-year annualised-CAGR cards. Keep the level chart + absolute level + period % change.
- [ ] Task 4: Load + verify (AC: #1, #2, #5) — `sym benchmarks` to pull `^VIX` levels into
  `index_levels` + recompute index returns; verify `/api/sym/indexes` lists VIX and `/levels` returns
  its series; real-Chrome CDP `/sym/indexes` shows VIX with the honest framing and `/monitor/wei` does
  NOT show VIX. Run suites + lint.

## Dev Notes

### Where this fits
A registry entry + one small `Benchmark` field + a board filter + an Indexes-page labelling tweak +
a data load. The instrument-identity, level-load, xref, and return-recompute machinery all already
exist (the equity indices use them); VIX rides the SAME `sym benchmarks` path as `^GSPC`/`^FTSE`.

### Critical conventions (regressions if violated)
- **VIX is a LEVEL, not a return** — never present its multi-year figures as annualised CAGR
  investment returns (semantically false for a mean-reverting volatility index). Honest labelling is
  AC#3, not polish.
- **Keep VIX off the equity WEI board by default** via a sourced `category` field, never a React-side
  name check (the project's data-driven-region rule, [[feedback-responsive-density-two-tier]] sibling
  principle: derivations live in the warehouse layer).
- **Immutable `index_levels`**, read-only API, idempotent `sym benchmarks`, no new dependency,
  SSR-safe, canonical `as_of_date`. Verify via headless Chrome/CDP, never `npm --prefix`
  ([[feedback-minimize-dev-churn]], [[feedback-headless-chrome-cleanup]]).
- **Duplication with macro is acceptable + intentional** — VIX levels will live in BOTH
  `macro.observation` (`MKT:VIX`, the time-series browser) and `index_levels` (the index spine). They
  share the `^VIX` source but serve different surfaces and different keyspaces; do NOT try to unify
  them. Note it; don't fight it.

### References
- [Source: packages/sym/src/sym/benchmarks/levels.py] — `Benchmark` dataclass + `BENCHMARKS` + `region_for`; `load_index_levels`/`YahooIndexLevelSource`.
- [Source: packages/sym/src/sym/cli.py] — `_cmd_benchmarks` (`sym benchmarks`: load levels + recompute returns).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py] — `indexes()` (Indexes-page list), `index_board()` (WEI board — add the equity-only filter), `_trailing_returns`.
- [Source: apps/web/app/sym/indexes/page.tsx] — the Indexes page (chart + trailing + monthly returns; add VIX framing).
- [Source: apps/web/app/monitor/wei/page.tsx] — the WEI board (must NOT show VIX).
- [Source: packages/macro/src/macro/ingest.py:78] — the existing `MKT:VIX` markets feed (`^VIX`, reachable).
- Sibling stories: `indexes-msci-eod-pull-and-page` (built the Indexes page + level load), `wei-world-equity-indices` (the board + region field).

## Open Questions (for Andre — defaults chosen, do not block)
1. **WEI board:** default = **exclude** VIX (volatility ≠ equity, colour semantics invert). Alt: show
   it in a dedicated "Volatility" tile/section on `/monitor` (separate story). Say if you want it on a board.
2. **Return framing:** default = label VIX figures "level change, not total return" + drop the
   annualised-CAGR cards for it. Alt: hide trailing returns entirely for VIX and show level + % change only.
3. **More volatility indices?** VIX term-structure cousins (VIX9D/VIX3M/VVIX) or VSTOXX could ride the
   same `category="volatility"` path if wanted — flag and I'll add them in this story.

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story). Surface VIX on the sym Indexes page via a benchmark-registry entry (`^VIX`) + `index_levels` load; add a `category` field so the WEI **equity** board excludes it; label VIX honestly as a level (not a CAGR return). VIX is already in `macro` (`MKT:VIX`) — this adds it to the index spine. Status → ready-for-dev. |
