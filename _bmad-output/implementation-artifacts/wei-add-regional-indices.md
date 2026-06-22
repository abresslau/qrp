# Story: Add regional/global indices to the WEI + Indexes surface

Status: review

<!-- Created via bmad-create-story 2026-06-22 (Andre: "add new indices to wei page" — Hang Seng, CSI 300,
STOXX Europe 600, FTSE All-World, MSCI Emerging Markets, FTSE Emerging). This is the "seed more regional
indices" follow-up flagged by wei-world-equity-indices Open Q#4. Both the WEI board (/monitor/wei) and the
Indexes page (/sym/indexes) are data-driven off index_levels, so adding an instrument with levels surfaces
it on BOTH automatically — exactly the indexes-add-vix pattern. -->

## Story

As a markets analyst,
I want Hong Kong, mainland-China, pan-European, and broad global/emerging-market index benchmarks on the
World Equity Indices board (and the Indexes page),
so that the board covers Asia-Pacific and the global/EM aggregates, not just the US/Europe/Japan/Brazil
headline set it has today.

## Reframe (investigation 2026-06-22 — read before scoping)

The 6 requested indices split by data source — and two are **already covered or redundant**:

| # | Requested | Source / status | Region | Action |
|---|---|---|---|---|
| 1 | **Hang Seng** | Yahoo `^HSI` (HKD) | Asia-Pacific | **ADD** (pending yfinance probe) |
| 2 | **CSI 300** | Yahoo `000300.SS` (CNY) — symbol uncertain in-env | Asia-Pacific | **ADD** (probe the symbol first) |
| 3 | **STOXX Europe 600** | Yahoo `^STOXX` (EUR) | EMEA | **ADD** (pending yfinance probe) |
| 4 | **FTSE All-World** | FTSE Russell — **no free EOD index series** (Yahoo/MSCI don't carry it) | Global | **PROBE → likely DEFER** |
| 5 | **MSCI Emerging Markets** | **ALREADY SEEDED** — `MSCI EM Net (USD)` (msci 891800 NETR) | Global | **CONFIRM only** (on the board today) |
| 6 | **FTSE Emerging** | FTSE Russell — **no free EOD index series** | Global | **PROBE → likely DEFER** |

Critical notes:
- **#5 MSCI EM is already on the board** (`/api/sym/indexes` lists `MSCI EM Net (USD)`; MSCI → region Global,
  NETR-only → shown on WEI). No work beyond confirming it renders.
- **#4/#6 (FTSE All-World / FTSE Emerging) are FTSE Russell** indices. Our two free index sources are
  **Yahoo (chart REST)** and **MSCI (`sym msci-pull`)** — neither serves FTSE Russell index *levels* (the
  Yahoo-listed FTSE proxies are *ETFs* like VWRL/VWO, NOT the index; an ETF NAV ≠ the index, and we
  derive-don't-proxy). They also **largely duplicate** indices already present: **MSCI ACWI Net** (already
  seeded) is the all-world benchmark and **MSCI EM Net** (already seeded) is the EM benchmark. So unless a
  free FTSE Russell EOD source is found (probe says no today), these should be **deferred** with that note
  — the analytical need is already met by the MSCI globals.

## What QRP already has (reuse — do NOT reinvent)

- **The benchmark registry** (`packages/sym/src/sym/benchmarks/levels.py`): `BENCHMARKS: tuple[Benchmark,…]`.
  `Benchmark(name, currency_code, yahoo_symbol=None, msci_code=None, variant=None, region=None, category="equity")`.
  A yahoo-symbol entry loads levels via `sym benchmarks` (yfinance); an MSCI entry is seeded via
  `sym msci-pull`. Region per entry (Asia-Pacific / EMEA / Americas / Global); `category="equity"` (default)
  so it shows on the equity WEI board.
- **`sym benchmarks` CLI** (`_cmd_benchmarks`): ensures the instrument + xrefs, loads yahoo levels, attaches
  index FIGIs, links universes, recomputes index returns. Idempotent (immutable `index_levels`). This is the
  exact path `indexes-add-vix` used for `^VIX`.
- **`sym msci-pull --msci-code <code> --variant <NR|PR|GR> --currency USD --name "<name>"`** — the MSCI free
  `getLevelDataForGraph` endpoint (history floor 1997; reachable in-env). Used to seed the MSCI globals
  (ACWI/EAFE/EM/Europe/USA).
- **Data-driven surfacing**: `indexes()` (Indexes page list) + `index_board()` (WEI board) read `index_levels`
  + `region_for(name, currency)` + `category_for(name)`. **No API/page code is needed** — an instrument with
  levels appears on both automatically. `region_for`'s currency fallback already maps HKD/CNY→Asia-Pacific,
  EUR→EMEA, but set `region` explicitly on each entry (data-driven, the project rule).
- **Reachability rule** ([[reference_env_external_sources]]): yfinance EOD is reachable in this sim env, but
  **probe each new symbol before committing** — the mock may not serve every ticker (e.g. CSI 300's
  `000300.SS`). The dev must confirm `sym benchmarks` actually loaded levels for each new symbol.

## Acceptance Criteria

1. **Hang Seng, CSI 300, STOXX Europe 600 added + loaded.** A `Benchmark` entry for each
   (`^HSI`/HKD/Asia-Pacific, the verified CSI-300 Yahoo symbol/CNY/Asia-Pacific, `^STOXX`/EUR/EMEA,
   `category="equity"`) is added to `BENCHMARKS`; `sym benchmarks` loads each one's level history into
   `index_levels` (immutable, keyed on its own `sym_id`, yahoo xref). Idempotent re-run.
2. **They appear on BOTH surfaces.** Each new index shows on `/sym/indexes` (list + level chart + trailing
   returns) and on the WEI board `/monitor/wei` under its region (Hang Seng + CSI 300 → Asia-Pacific, STOXX
   Europe 600 → EMEA), with EOD 1D/windows + sparkline + 52w + correct up/down colour. Verified real-Chrome CDP.
3. **Symbol reachability is proven, not assumed.** Before adding an entry, the dev probes the Yahoo symbol via
   yfinance in-env; a symbol that returns no data is reported and the index is skipped (not added as an empty
   instrument). The CSI-300 symbol in particular is verified (`000300.SS` vs an alternative) — document the one used.
4. **MSCI Emerging Markets confirmed (no new work).** Verify `MSCI EM Net (USD)` already renders on the WEI
   board (region Global) and the Indexes page — it is the requested "MSCI Emerging Markets" benchmark. Document
   that it was already seeded (no duplicate instrument created).
5. **FTSE All-World / FTSE Emerging: probe then decide.** Probe for a FREE EOD source of the FTSE Russell
   *index levels* (not an ETF proxy). If none exists (expected), **defer** them with the honest reason and note
   that **MSCI ACWI Net** (all-world) and **MSCI EM Net** (emerging) — both already present — cover the same
   need; do NOT add an ETF as a stand-in for the index (derive-don't-proxy). If a free source is found, add via
   the same registry pattern.
6. **No regression.** The existing 26 indices, the Indexes page, the WEI board (+ backdating + LIVE), the
   equity-only filter, `index_levels` immutability, and the macro/quote machinery stay green. `ruff`/`tsc`/
   `eslint`/`vitest` clean.
7. **Tests.** (a) registry: each added benchmark present with its yahoo xref + region + `category="equity"`,
   and `region_for`/`category_for` resolve as expected (Hang Seng → Asia-Pacific, STOXX 600 → EMEA, etc.);
   (b) the existing benchmark/region tests stay green (no new API/page tests needed — the surfaces are
   data-driven and already tested).

## Tasks / Subtasks

- [x] Task 1: Probed the Yahoo symbols in-env (AC: #3) — `^HSI` (113 pts), `000300.SS` (110 pts) and
  `399300.SZ` (only 1 pt → rejected), `^STOXX` (116 pts); `^STOXX600` empty. Working symbols: `^HSI`,
  `000300.SS` (Shanghai), `^STOXX`.
- [x] Task 2: Registry entries (AC: #1, #7a) — added `Benchmark("Hang Seng Index","HKD",^HSI,Asia-Pacific)`,
  `Benchmark("CSI 300","CNY",000300.SS,Asia-Pacific)`, `Benchmark("STOXX Europe 600","EUR",^STOXX,EMEA)` (all
  `category="equity"`). Added `test_regional_indices_in_registry_with_region_and_yahoo_xref` (xref + region +
  category + `region_for`). 15 benchmark tests green.
- [x] Task 3: Load + recompute (AC: #1) — `sym benchmarks` → 22 instruments, +15,861 levels, index returns
  recomputed. Per-index: Hang Seng 8,997 / CSI 300 1,278 / STOXX 600 5,568 levels, sane last levels.
- [x] Task 4: FTSE probe + MSCI EM confirm (AC: #4, #5) — `MSCI EM Net (USD)` confirmed already on the board
  (region Global) = the requested MSCI Emerging Markets; no duplicate created. No free FTSE Russell index-level
  source (Yahoo carries only FTSE *ETFs*; MSCI-pull is MSCI-only) → FTSE All-World / FTSE Emerging **deferred**
  with that reason; MSCI ACWI Net (all-world) + MSCI EM Net (emerging), both present, cover the need. No ETF
  proxy added (derive-don't-store).
- [x] Task 5: Verify (AC: #2, #6) — `/api/sym/indexes` lists 29 (incl. the 3 new); `/indexes/board` places
  Hang Seng + CSI 300 → Asia-Pacific, STOXX Europe 600 → EMEA, MSCI EM → Global, all with real 1D/YTD.
  Real-Chrome CDP dump-dom: all 3 render on both `/monitor/wei` and `/sym/indexes`. 841 sym tests green
  (api/web code untouched — surfaces are data-driven).

## Dev Notes

### Critical conventions (regressions if violated)
- **Probe before adding** — never add a `Benchmark` whose Yahoo symbol doesn't resolve in-env (an empty
  instrument is worse than an absent one). [[reference_env_external_sources]], [[reference_yfinance_raw_prices]].
- **Derive-don't-proxy** — do NOT substitute an ETF (VWRL/VWO/etc.) for a FTSE *index*; an ETF NAV is a
  different series. If there's no free index source, defer honestly.
- **Region is data-driven** — set `region` on each `Benchmark`; never hardcode a region in the React page.
  `category="equity"` so the index shows on the equity WEI board (not excluded like the VIX).
- **Immutable `index_levels`**, idempotent `sym benchmarks`, read-only API, no new dependency. The new indices
  ride the daily EOD `benchmarks` step automatically (no separate maintenance plan — that rule is for universe
  membership, not benchmark index levels). Verify via headless Chrome/CDP, never `npm --prefix`
  ([[feedback_minimize_dev_churn]], [[feedback_headless_chrome_cleanup]]). No Bloomberg/index-provider IP —
  functional reproduction over our own warehouse.

### References
- [Source: packages/sym/src/sym/benchmarks/levels.py] — `Benchmark` + `BENCHMARKS` + `region_for`/`category_for`; `load_index_levels`/`YahooIndexLevelSource`.
- [Source: packages/sym/src/sym/cli.py] — `_cmd_benchmarks` (`sym benchmarks`), `_cmd_msci_pull` (`sym msci-pull`).
- [Source: services/api/.../sym/gateway.py] — `indexes()` / `index_board()` (data-driven; no change needed).
- Sibling stories: `indexes-add-vix` (the exact add-a-benchmark pattern), `indexes-msci-eod-pull-and-page` (MSCI-pull seeding of ACWI/EAFE/EM/…), `wei-world-equity-indices` (the board + region, Open Q#4 flagged this).

## Open Questions (for Andre — defaults chosen, do not block)
1. **CSI 300 symbol:** default = probe `000300.SS` (Shanghai); fall back to `399300.SZ` if the mock doesn't
   serve it. If neither resolves in-env, CSI 300 is skipped (documented) — say if you have a preferred source.
2. **FTSE All-World / FTSE Emerging:** default = **defer** (no free FTSE Russell index source; MSCI ACWI Net +
   MSCI EM Net already cover all-world + EM). Accept the MSCI equivalents, or do you have a licensed FTSE feed
   to wire? An ETF proxy is explicitly out (derive-don't-proxy).
3. **More Asia-Pacific while here?** KOSPI (`^KS11`), ASX 200 (`^AXJO`), TSX (`^GSPTSE`), Sensex (`^BSESN`) are
   the other Open-Q#4 candidates — easy Yahoo adds if you want them in the same pass.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes
- Pure registry + data, no API/page code — both surfaces are data-driven, so 3 `Benchmark` entries + a
  `sym benchmarks` load surfaced the indices on the Indexes page AND the WEI board automatically (the
  `indexes-add-vix` pattern). Probe-before-ingest held: `000300.SS` is the usable CSI-300 series (399300.SZ
  returned one point), and the 3 symbols were verified reachable before being added.
- **The reframe stuck**: MSCI Emerging Markets was already seeded (`MSCI EM Net`) — confirmed on the board,
  no work. FTSE All-World / FTSE Emerging deferred — no free FTSE Russell *index* source (Yahoo only has the
  ETFs; derive-don't-store bars an ETF stand-in) and they duplicate the present MSCI ACWI / MSCI EM.
- region_for resolved each correctly (Hang Seng/CSI 300 → Asia-Pacific, STOXX 600 → EMEA), and they ride the
  daily EOD `benchmarks` step from here on (no separate maintenance plan — that's a universe-membership rule).

### File List
- `packages/sym/src/sym/benchmarks/levels.py` (modified — 3 `Benchmark` entries: Hang Seng, CSI 300, STOXX Europe 600)
- `packages/sym/tests/test_benchmarks.py` (modified — regional-indices registry test)
- Data: `^HSI` / `000300.SS` / `^STOXX` levels loaded into `index_levels` via `sym benchmarks` — live in the sym DB.

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story). Add Hang Seng (`^HSI`), CSI 300, STOXX Europe 600 (`^STOXX`) to the benchmark registry → loaded via `sym benchmarks` → auto-surface on the Indexes page + WEI board (data-driven). MSCI Emerging Markets already seeded (`MSCI EM Net`) — confirm only. FTSE All-World / FTSE Emerging deferred (no free FTSE Russell index source; duplicate the present MSCI ACWI/EM). The `wei-world-equity-indices` Open Q#4 follow-up. Status → ready-for-dev. |
| 2026-06-22 | Dev complete → review. Probed + added Hang Seng (`^HSI`/HKD), CSI 300 (`000300.SS`/CNY), STOXX Europe 600 (`^STOXX`/EUR) to `BENCHMARKS` (region/category set); `sym benchmarks` loaded 8,997/1,278/5,568 levels. MSCI EM confirmed already present; FTSE pair deferred (no free index source). 29 indexes now; real-Chrome CDP shows all 3 on `/monitor/wei` + `/sym/indexes` in the right regions. 841 sym tests + 15 benchmark tests green. Status → review. |
