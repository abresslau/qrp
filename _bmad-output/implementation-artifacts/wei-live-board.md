# Story: WEI board — LIVE mode (intraday index quotes)

Status: review

<!-- Created via bmad-create-story 2026-06-22 (Andre: "I want my wei page to also be able to show
Live data"). This is the follow-up the `wei-world-equity-indices` story explicitly flagged (Open
Q#3): "v1 is EOD; a live index board (intraday via the Yahoo chart REST for ^GSPC etc., like QH.2
quotes) is a clear follow-up." -->

## Story

As a markets analyst,
I want a **LIVE toggle on the World Equity Indices board** so it can show intraday index levels and
today's move (not just the prior EOD close),
so that I can watch world markets in real time from the same board — the way a Bloomberg WEI screen
updates live during the session.

## Background / current state (read before coding)

- **The WEI board is EOD today.** `index_board(as_of_date=None)` (`services/api/.../sym/gateway.py`) →
  `GET /api/sym/indexes/board` → `apps/web/app/monitor/wei/page.tsx`. Each row = last vs prior session
  over the immutable `index_levels`, plus 5D/MTD/1M/3M/6M/YTD/1Y/2Y/3Y/5Y, a 52w range, a 30-pt spark.
  Equity-only (the `category_for != "equity"` filter keeps VIX off — see `indexes-add-vix`). It already
  has an `as_of_date` backdate control + per-market staleness markers.
- **Live-quote machinery already exists (REUSE — do NOT reinvent):**
  - **QH.2 `services/api/.../sym/quotes.py`**: `fetch_raw_quote` / `fetch_quotes_batch(symbols, …)`
    (bounded `ThreadPoolExecutor` + wall-clock budget), `RawQuote(price, prev_close, currency,
    quote_epoch)`, `classify_freshness(epoch, now) → (live|delayed, age)` (≤120s ⇒ live),
    `live_return(price, prev_close)`. Source: the **Yahoo v8 chart REST** (`/v8/finance/chart/{sym}`,
    no auth, re-probed reachable). **Never persisted.** Two-tier error contract: per-symbol miss → None;
    whole-source unreachable → `QuoteSourceUnreachable` (→503).
  - **QH.9 `live_heatmap` (`gateway.py:447`)** is the precedent for "EOD surface + LIVE overlay":
    fan-out quotes via `fetch_quotes_batch`, per-cell `freshness`, map-level `as_of` (most-recent
    priced) + worst `freshness` + `priced`/`total` coverage, a `LIVE_HEATMAP_MAX` fan-out cap, and the
    `LookupError`/`ValueError`/`QuoteSourceUnreachable` → 404/422/503 mapping. Mirror this shape.
  - **Index symbols work on the chart endpoint** — `YahooIndexLevelSource.official_quote`
    (`packages/sym/.../benchmarks/levels.py`) already fetches `^BVSP`/etc.'s `regularMarketPrice` via the
    same v8 chart URL. Index instruments carry a **`yahoo` xref** (`^GSPC`, `^FTSE`, `^N225`, …) in
    `instrument_xref` — the live board fetches that symbol DIRECTLY (an index symbol IS the Yahoo symbol;
    `quotes.yahoo_symbol_for(ticker, mic)` is the EQUITY ticker+MIC path and is NOT what indexes use).
- **The backdate re-base trick (`wei-backdate-as-of-date`):** `_trailing_returns`/`_period_return`
  anchor on `series[-1]`, so feeding a different latest point re-bases every window for free. LIVE is the
  same idea: substitute the **live price** as the latest point and the windows re-base to the live mark
  with no formula change.
- **Env note:** live quotes are reachable here, but the sim clock makes freshness read **`delayed`**
  (sim-"now" − Yahoo's real timestamp is huge) regardless — the data DOES update each fetch; in
  production (real clock) the same code reads `live`. Documented in `nasdaq100-universe.md` + QH.2.

## Acceptance Criteria

1. **A live board endpoint.** `GET /api/sym/indexes/board/live` returns the SAME row shape as
   `/indexes/board` (so the page reuses its rendering) PLUS per-row live fields: `freshness`
   (`live|delayed|unavailable`), `quote_time` (ISO-8601 or null), and a board-level rollup (`as_of` =
   most-recent priced quote, worst `freshness`, `priced`/`total` coverage) — mirroring `LiveHeatmap`.
   Equity-only (same `category` filter). Read-only; quotes fetched externally, **never persisted**.
2. **Live last + live 1D, honestly based.** For each index, `last` = the live price; `chg`/`chg_pct`
   (the **1D** column) = live price vs the index's **latest stored EOD close** (the `index_levels`
   most-recent close — "today's move vs the prior session"), NOT the EOD prior-prior session. An index
   with no usable quote keeps its EOD values and is marked `unavailable` (never a fabricated live mark).
3. **Trailing windows re-base to the live mark.** 5D/MTD/1M/3M/6M/YTD/1Y/2Y/3Y/5Y + the 52w-range marker
   are recomputed against the live `last` by feeding it as the latest point to the existing
   `_trailing_returns`/`_period_return` helpers (the backdate re-base trick) — no formula change. The
   sparkline appends the live point. (If a quote is unavailable for an index, it shows its EOD windows.)
4. **LIVE / EOD toggle on the page.** `/monitor/wei` gets a LIVE⟷EOD toggle (mirror the QH.9 heatmap
   LIVE mode). EOD (default) = today's behaviour, untouched. LIVE = fetch `/board/live`, show a live
   badge with the worst freshness + the `as_of`, and a manual ↻ refresh; per-index `live|delayed|
   unavailable` is marked (reuse/extend the existing per-market staleness ● idiom). The as-of backdate
   control is EOD-only (LIVE is "now" — disable/hide backdating in LIVE mode). SSR-safe, newest-wins
   fetch (AbortController, per QH.8), no new dependency.
5. **Honest freshness + colour.** Up/down colour unchanged (emerald/rose). A `delayed`/`unavailable`
   index is visibly marked; a market that's closed shows its last quote as `delayed` (its live 1D ≈ its
   last session's move) — never implied to be live. The board never blanks on one bad index (partial
   coverage is honest, per the `fetch_quotes_batch` contract). The sim-env "always delayed" artifact is
   noted in the UI copy/footnote.
6. **Bounded + safe fan-out.** Reuse `fetch_quotes_batch` (bounded workers + wall-clock budget). The
   board is ~25 indexes (well under any cap), but a wholly-unreachable provider → 503 (surface an honest
   error, keep the EOD board reachable). No N+1 per-index fetches.
7. **No regression.** The EOD board (`index_board` + `/indexes/board`), backdating, `index_levels`
   immutability, the equity-only filter, the Indexes page, and the macro/quote machinery stay green.
   `ruff`/`tsc`/`eslint`/`vitest` clean.
8. **Tests.** (a) gateway `index_board_live()` from fakes: live last + live 1D vs latest EOD close,
   windows re-based to the live mark, an unavailable-quote index falls back to EOD + `unavailable`,
   freshness rollup (`as_of`/worst/coverage), equity-only; (b) route exists + shape + 503 on a wholly
   unreachable provider (monkeypatch `fetch_quotes_batch` to raise); (c) web: the LIVE toggle fetches
   `/board/live`, renders the live badge + a per-index freshness mark, and the EOD path is unchanged
   (vitest, SSR-safe).

## Tasks / Subtasks

- [x] Task 1: Gateway `index_board_live(now=None)` (AC: #1, #2, #3, #6) — reuses `index_board()`
  wholesale for the EOD rows, then overlays live quotes: reads each equity index's `yahoo` xref,
  `fetch_quotes_batch` the symbols, and **re-bases each window by scaling the endpoint** (`r_live =
  (1+r_eod)·f − 1`, `f = live/eod_last`) — exact, no series/date surgery. Live 1D = live / latest EOD
  close; per-row `freshness` + board rollup (`as_of`/worst/`priced`/`total`); unavailable ⇒ EOD
  fallback. 52w extended to include the live mark, spark appends it.
- [x] Task 2: Route `GET /api/sym/indexes/board/live` (AC: #1, #8b) — `IndexBoardLiveRow`
  (extends `IndexBoardRow` + `freshness`/`quote_time`) + `IndexBoardLive` envelope; reuses the existing
  `QuoteSourceUnreachable`→503 handler. Registered after `/indexes/board` (no `{sym_id}` collision).
- [x] Task 3: WEI page LIVE/EOD toggle (AC: #4, #5) — EOD⟷LIVE segmented toggle; LIVE shows a badge
  (worst freshness + `priced/total` + `as_of`) + a manual ↻ refresh; per-row delayed/unavailable marks
  (extending the EOD stale-● idiom); backdate control is EOD-only; newest-wins AbortController fetch;
  mode-aware footnote incl. the sim-env "delayed" note. EOD path untouched.
- [x] Task 4: Verify (AC: #7, #8) — 160 api + 133 web green, tsc/eslint clean. Live API: `/board/live`
  returned 17/23 priced (EURO STOXX −0.06%, US 0% as the sim chart price == the EOD close), freshness
  `delayed` (sim-clock), 6 honest `unavailable`. Real-Chrome CDP `/monitor/wei`: LIVE toggle → badge
  "LIVE · delayed · 17/23 priced", delayed + unavailable row marks present, board intact, "never stored"
  footnote; EOD unchanged.

## Dev Notes

### Critical conventions (regressions if violated)
- **Live quotes are NEVER persisted** — second data class, off the immutable `index_levels` (QH.2 rule).
- **Reuse QH.2 `quotes.py` + the QH.9 `live_heatmap` shape** — do NOT write a new quote fetcher or a new
  freshness scheme. Index symbols come from the `yahoo` xref directly (not `yahoo_symbol_for`).
- **EOD path must be provably unchanged** — LIVE is additive (new endpoint + toggle); `/indexes/board`
  and its tests stay byte-identical. Factor the shared EOD row-build rather than fork it.
- **Honest freshness** — per-index `live|delayed|unavailable`; closed markets read `delayed`; partial
  coverage renders (never blank the board); never fabricate a live mark. EOD honesty + per-market
  staleness idioms carry over ([[feedback_freshness_per_market]]).
- **Equity-only** — the live board reuses the `category_for == "equity"` filter (VIX et al. stay off).
- Read-only API, no new dependency, SSR-safe + `react-hooks` newest-wins fetch (QH.8), canonical
  `as_of_date` (EOD only). Verify via headless Chrome/CDP, never `npm --prefix`
  ([[feedback_minimize_dev_churn]], [[feedback_headless_chrome_cleanup]]). No Bloomberg IP.

### References
- [Source: services/api/.../sym/quotes.py] — `fetch_quotes_batch`, `classify_freshness`, `live_return`, `RawQuote` (QH.2).
- [Source: services/api/.../sym/gateway.py] — `index_board()` (the EOD board to share), `live_heatmap()` (the LIVE-overlay precedent, line ~447), `_trailing_returns`/`_period_return`.
- [Source: services/api/.../sym/router.py] — `/indexes/board`, `IndexBoardRow`, `LiveHeatmap`/`LiveHeatmapCell` envelope + the `QuoteSourceUnreachable`→503 handler.
- [Source: apps/web/app/monitor/wei/page.tsx] — the board page (add the toggle), the per-market staleness idiom.
- [Source: apps/web/components/heatmap-view.tsx] — the QH.9 LIVE-mode toggle + live-badge UI to mirror.
- [Source: packages/sym/.../benchmarks/levels.py] — `YahooIndexLevelSource.official_quote` (proof index symbols quote on the chart endpoint) + the `yahoo` benchmark xref.
- Sibling stories: `wei-world-equity-indices` (the board), `wei-backdate-as-of-date` (the re-base trick), `qh-2-live-quote-source`, `qh-9-live-heatmap`.

## Open Questions (for Andre — defaults chosen, do not block)
1. **Auto-refresh in LIVE:** default = on-toggle fetch + a manual ↻ button. Want a polling auto-refresh
   (e.g. every 20–30s) or SSE while LIVE? (Heatmap LIVE is pull-mark-discard; same default here.)
2. **Window re-basing:** default = re-base ALL windows on the live mark (5D…5Y + 52w + spark), so the
   whole row moves live. Alt: keep only `last` + 1D live and leave the longer windows EOD-anchored
   (less "alive" but arguably less noisy). Say which you prefer.
3. **1D base:** default = live price vs the latest stored EOD close ("today's move"). Alt: the quote's
   own `previousClose` (QH.2's equity choice) — can differ slightly from the sym close.
4. **Scope:** LIVE on the WEI board only. The Indexes page (`/sym/indexes`) and the FX matrix could get
   the same treatment later — separate stories.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes
- The cleanest re-base turned out to be **endpoint-scaling**, not series surgery: each EOD window's base
  (N periods ago) is unchanged, so `r_live = (1+r_eod)·(live/eod_last) − 1` moves only the endpoint to the
  live mark — exact, and it sidesteps the sim-clock date-anchoring trap entirely. `index_board_live`
  therefore reuses `index_board()` wholesale (EOD rows) + a tiny `yahoo`-xref query + the QH.2/QH.9 quote
  fan-out, so EOD and LIVE can never diverge.
- **Index symbols quote fine** — `^GSPC`-style symbols work on the v8 chart endpoint (no URL-encoding
  needed); live verify showed 17/23 priced. US indices read +0.00% because the sim chart price equals the
  EOD close; EURO STOXX showed a real −0.06% — the mechanism is correct, the magnitude is just the data.
- **Honesty preserved** — freshness reads `delayed` in this env (sim clock; documented), unavailable rows
  keep their EOD values + a grey mark, the board never blanks on a partial miss, nothing is persisted.
- One lint note: `setLoading(true)` could not sit in the effect body (`react-hooks/set-state-in-effect`,
  the rule QH.7 cleared) — moved it into the ↻ refresh handler.

### File List
- `services/api/src/qrp_api/modules/sym/gateway.py` (modified — `index_board_live()`)
- `services/api/src/qrp_api/modules/sym/router.py` (modified — `IndexBoardLiveRow`/`IndexBoardLive` + `/indexes/board/live` route)
- `services/api/tests/test_indexes_route.py` (modified — live re-base + 503 tests)
- `apps/web/app/monitor/wei/page.tsx` (modified — EOD/LIVE toggle, live badge, per-row freshness, mode-aware footnote)
- `apps/web/__tests__/wei-page.test.tsx` (modified — LIVE toggle test)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story). Add a LIVE mode to the WEI board: new `GET /api/sym/indexes/board/live` (live last + live 1D vs latest EOD close + windows re-based to the live mark + per-index freshness + board rollup, equity-only, never persisted) reusing QH.2 `quotes.py` + the QH.9 `live_heatmap` pattern + the backdate re-base trick; a LIVE/EOD toggle + live badge on `/monitor/wei`. The follow-up flagged by `wei-world-equity-indices` Open Q#3. Status → ready-for-dev. |
| 2026-06-22 | Dev complete → review. `index_board_live()` (reuses `index_board()` + endpoint-scaling re-base + QH.2/QH.9 quote fan-out over the `yahoo` xref) + `GET /api/sym/indexes/board/live` (`IndexBoardLive`/`IndexBoardLiveRow`, 503 on a dead provider) + a LIVE/EOD toggle + live badge + per-row freshness on `/monitor/wei`. 160 api + 133 web tests green; tsc/eslint clean; live API (17/23 priced) + real-Chrome CDP toggle verified. Status → review. |
