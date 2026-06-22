# Story: FX cross-rate matrix — LIVE mode (intraday spot quotes)

Status: done

<!-- Created via bmad-create-story 2026-06-22 (Andre: "I also want my FX matrix to be live similar to
wei page"). This is the follow-up the `wei-live-board` story explicitly flagged (Open Q#4): "LIVE on
the WEI board only. The Indexes page and the FX matrix could get the same treatment later — separate
stories." This IS the FX one — apply the proven WEI LIVE pattern to /monitor/fx. -->

## Story

As a markets analyst,
I want a **LIVE toggle on the FX cross-rate matrix** so it can show intraday spot crosses and today's
move (not just the prior EOD fixings),
so that I can watch the FX grid update in real time from the same matrix — the way a Bloomberg FXC
screen ticks live during the session.

## Background / current state (read before coding)

- **The FX matrix is EOD today.** `fx_matrix(currencies=None, as_of_date=None)`
  (`services/api/.../sym/gateway.py:1277`) → `GET /api/sym/fx/matrix` → `apps/web/app/monitor/fx/page.tsx`.
  It resolves a USD-base per-currency rate for each of 16 currencies (`DEFAULT_FX_MATRIX`: EUR, JPY, GBP,
  CHF, CAD, AUD, NZD, SEK, NOK, DKK, HKD, SGD, MXN, CNY, BRL, USD) via `sym.fx.resolve.fx_rate`
  (currency-per-USD, as-of ≤ date, staleness policy), takes the prior observation per currency for the
  day's move, then builds the **N×N grid by division**: `cell(base, quote).rate = res[quote].rate /
  res[base].rate` (diagonal 1.0), `cell.chg` = the cross's day-on-day move via `cross_chg`, `cell.stale`
  = either leg carried-forward, `cell.pair` = the conventional market direction. Per-currency `meta`
  carries `status` (ok|stale|no_data), `observed_date`, `days_stale`, `quote_rank`. It already has an
  `as_of_date` backdate control, a Base-currency / Sorting / Base-axis layout, drag-to-reorder (persisted),
  and two stacked grids (Spot rate + Spot daily-% heat).
- **Live-quote machinery already exists (REUSE — do NOT reinvent):**
  - **QH.2 `services/api/.../sym/quotes.py`**: `fetch_quotes_batch(symbols, …)` (bounded
    `ThreadPoolExecutor` + wall-clock budget; **input is symbol strings — source-agnostic**),
    `RawQuote(price, prev_close, currency, quote_epoch)`, `classify_freshness(epoch, now) →
    (live|delayed, age)` (≤120s ⇒ live), `now_epoch()`. Source: the **Yahoo v8 chart REST**
    (`/v8/finance/chart/{sym}`, no auth, re-probed reachable 2026-06-22). **Never persisted.** Two-tier
    error contract: per-symbol miss → None; whole-source unreachable → `QuoteSourceUnreachable` (→503).
  - **`index_board_live` (`gateway.py:1192`) is the precedent for "EOD surface + LIVE overlay"** — it
    reuses the EOD board wholesale, fans out quotes via `fetch_quotes_batch`, marks per-row `freshness` +
    `quote_time`, rolls up `as_of` (most-recent priced) / worst `freshness` / `priced`/`total`, degrades
    the rollup to `delayed` under partial coverage, falls back to EOD on an unavailable quote, and raises
    `QuoteSourceUnreachable`→503 only when the provider is wholly dead. **Mirror this shape exactly.**
  - **`live_heatmap` (`gateway.py:447`)** is the same shape for a 2-D surface — its `as_of`/worst-freshness/
    `priced`/`total` rollup and the `LiveHeatmap` envelope in `router.py` are the model to copy.
- **The live FX rate source — PROBED IN-ENV 2026-06-22 (the [[feedback_name_the_probe_retest]] rule):**
  `USD{CCY}=X` on the v8 chart endpoint returns **units of CCY per 1 USD — exactly the `fx_rate`
  USD-base convention.** Verified live: `USDJPY=X`→161.73 (JPY/USD), `USDEUR=X`→0.8725 (EUR/USD),
  `USDBRL=X`→5.15, `USDCNY=X`→6.76, `USDGBP=X`→0.7545, `USDSEK=X`→9.59 — all with a `regularMarketTime`
  epoch + `previousClose`. So the live per-USD rate for a currency = the `USD{CCY}=X` quote price; **USD
  itself = 1.0** (no fetch). This is NOT `quotes.yahoo_symbol_for` (that's the equity ticker+MIC path)
  and NOT the index `yahoo` xref — it's a synthetic FX symbol built per currency: `f"USD{ccy}=X"`.
- **The re-derivation is cleaner than the WEI per-row scaling.** The matrix is N crosses derived from N
  per-USD leg rates, so LIVE just **substitutes each currency's live per-USD rate** for its EOD rate and
  re-runs the SAME grid derivation (`quote_rate / base_rate`). No per-cell scaling. The cell's live `chg`
  (1D) = the live cross vs the **latest EOD cross** (today's move) — i.e. `(live_q/live_b)/(eod_q/eod_b) − 1`
  — mirroring `index_board_live`'s "live vs latest stored close". Factor the shared grid build so EOD and
  LIVE can't diverge.
- **Env note:** live FX quotes are reachable here, but the sim clock makes freshness read **`delayed`**
  (sim-"now" − Yahoo's real timestamp is huge) regardless — the data DOES update each fetch; in production
  (real clock) the same code reads `live`. Same artifact documented in `wei-live-board` + QH.2.

## Acceptance Criteria

1. **A live matrix endpoint.** `GET /api/sym/fx/matrix/live` returns the SAME envelope shape as
   `/fx/matrix` (`currencies`, `meta`, `rows[].base`, `rows[].cells[]` with `rate`/`chg`/`stale`/`pair`)
   so the page reuses its rendering, PLUS live fields: per-currency `freshness` (`live|delayed|
   unavailable`) + `quote_time` (ISO-8601 or null) on `meta`, and a matrix-level rollup (`as_of` =
   most-recent priced quote, worst `freshness`, `priced`/`total` currency coverage) — mirroring
   `IndexBoardLive`/`LiveHeatmap`. Read-only; quotes fetched externally, **never persisted**. (LIVE is
   "now" — it takes no `as_of_date`.)
2. **Live legs, honestly sourced.** For each currency, the live per-USD rate = the `USD{CCY}=X` quote
   price (USD = 1.0, no fetch). A currency whose quote is unavailable (or non-positive) **keeps its EOD
   resolved rate** and is marked `unavailable` on its `meta` (never a fabricated live leg) — exactly the
   `index_board_live` EOD-fallback rule.
3. **Live crosses + live 1D, re-derived not scaled.** Each cell's `rate` = `live_quote / live_base`
   (the same division as EOD, over the substituted live legs; diagonal 1.0). Each cell's `chg` (the heat
   driver / the % grid) = the live cross vs the **latest EOD cross**: `(live_q/live_b)/(eod_q/eod_b) − 1`,
   null when either EOD leg is missing. A cell touching an `unavailable` leg falls back to the EOD
   cross + carries the leg's `stale`/`unavailable` flag (the matrix never blanks on one bad leg).
4. **LIVE / EOD toggle on the page.** `/monitor/fx` gets a LIVE⟷EOD segmented toggle (mirror the WEI
   page). EOD (default) = today's behaviour, untouched. LIVE = fetch `/fx/matrix/live`, show a live badge
   with the worst freshness + `priced/total` + `as_of`, a manual ↻ refresh, AND a polling auto-refresh
   (`autoSec` interval, floored at 3s, off by default, paused when offline via `useOnline`) — the same
   controls Andre added to the WEI page. The `as_of_date` backdate control + Latest button are EOD-only
   (hidden/disabled in LIVE). Base-currency / Sorting / Base-axis / drag-reorder all keep working in LIVE.
   SSR-safe, newest-wins fetch (AbortController, per QH.8), no new dependency.
5. **Honest freshness on the grid.** The per-currency axis-header marker (`headerMarker`, today ok/stale/
   no_data ●) becomes the **freshness marker in LIVE** (live = none/emerald, delayed = amber, unavailable
   = muted ●), reusing the WEI `LIVE_TONE` idiom; tooltips say "delayed quote · as of HH:MM:SS" or
   "no live quote — showing EOD rate". The heat scale + up/down semantics are unchanged. The sim-env
   "always delayed" artifact is noted in the page footnote (mode-aware copy).
6. **Bounded + safe fan-out.** Reuse `fetch_quotes_batch` (bounded workers + wall-clock budget) over the
   ≤15 non-USD `USD{CCY}=X` symbols (well under any cap; no N+1). A wholly-unreachable provider → 503
   (honest error; the EOD matrix stays reachable). De-dupe currencies first (same `dict.fromkeys` guard
   the EOD path got in review).
7. **No regression.** The EOD matrix (`fx_matrix` + `/fx/matrix`), backdating, the `fx_rate` resolver,
   `fx_rate`-star immutability, the page's layout/drag/persistence, and the macro/quote machinery stay
   green. `ruff`/`tsc`/`eslint`/`vitest` clean. The EOD `fx_matrix` output is byte-identical (factor the
   shared grid build rather than fork it).
8. **Tests.** (a) gateway `fx_matrix_live()` from fakes (monkeypatch `fetch_quotes_batch`): live legs
   substituted + crosses re-derived, live `chg` = live-cross vs latest-EOD-cross, an unavailable-quote
   currency falls back to its EOD rate + `unavailable` meta (and its row/column cells stay populated from
   EOD), USD pinned to 1.0, freshness rollup (`as_of`/worst/`priced`/`total`), currency de-dupe; (b) route
   exists + shape + 503 on a wholly unreachable provider (monkeypatch to raise); (c) web: the LIVE toggle
   fetches `/fx/matrix/live`, renders the live badge + a per-currency freshness mark, the auto-refresh
   control is LIVE-only + the as-of control is EOD-only, and the EOD path is unchanged (vitest, SSR-safe).

## Tasks / Subtasks

- [x] Task 1: Factor the shared grid build out of `fx_matrix` (AC: #7) — extracted module-level
  `_fx_grid(ccys, rate, prior, stale)` (the `cross_chg` + `rows`/`cells` loop). `fx_matrix` now builds
  three per-currency maps (resolved rate, prior-session rate, `is_filled`) and calls it. EOD output is
  byte-identical — the existing `test_fx_matrix_cross_diagonal_and_stale` passes unchanged.
- [x] Task 2: Gateway `fx_matrix_live(currencies=None, now=None)` (AC: #1, #2, #3, #6) — computes the EOD
  `res` anchor (latest FX date, de-duped ccys), fans out `USD{ccy}=X` via `fetch_quotes_batch`, overlays
  each leg's live per-USD rate as FLOAT (USD pinned 1.0; miss/non-positive → keep EOD rate + `unavailable`),
  calls `_fx_grid` with `prior` = the EOD legs so `chg` = live-cross vs latest-EOD-cross. Per-currency
  `freshness`/`quote_time` on `meta` + rollup (`as_of`/worst/`priced`/`total`, degraded to `delayed` under
  partial coverage). `QuoteSourceUnreachable` propagates (→503) only on a wholly-dead provider.
- [x] Task 3: Route `GET /api/sym/fx/matrix/live` (AC: #1, #8b) — `FxCurrencyMetaLive` (extends
  `FxCurrencyMeta` + `freshness`/`quote_time`) + `FxMatrixLive` envelope (no `as_of_date`; +
  `as_of`/`freshness`/`priced`/`total`); reuses the `QuoteSourceUnreachable`→503 handler. Registered after
  `/fx/matrix` (no shadow).
- [x] Task 4: FX page LIVE/EOD toggle + auto-refresh (AC: #4, #5) — EOD⟷LIVE segmented toggle; LIVE shows
  the live badge (worst freshness + `priced/total` + `as_of` + `refreshedAt`) + ↻ refresh + `autoSec`
  auto-refresh (3s floor, off by default, `useOnline`-paused); the per-currency `headerMarker` is now
  freshness-aware in LIVE (`LIVE_TONE`); backdate control + Latest are EOD-only; newest-wins
  `AbortController` fetch; mode-aware footnote. EOD path (layout/drag/persistence/backdating) untouched.
- [x] Task 5: Verify (AC: #7, #8) — API 163 + web 135 green; ruff/tsc/eslint clean. Live API
  `/fx/matrix/live` = 16/16 priced (read `live`, then `delayed` minutes later as quotes aged — honest);
  EOD `/fx/matrix` unchanged (16 ccys/rows). Real-Chrome CDP `/monitor/fx`: EOD shows the as-of control +
  no auto; LIVE shows badge "● LIVE · delayed · 16/16 priced · as of … · refreshed …", as-of hidden,
  auto-refresh shown, both grids re-derived (real cross values), correct footnote; toggle back restores EOD.
  api-types regenerated (new `/fx/matrix/live` path); CDP cleaned up.

## Review Findings (code-review 2026-06-22 — Blind Hunter / Edge Case Hunter / Acceptance Auditor)

Acceptance Auditor: **all 8 ACs + all 6 critical conventions PASS**, no High/Med. The Blind Hunter's two
"High" items both dismissed on inspection (see below). Three patches identified (honesty + coverage):

- [x] [Review][Patch] **LIVE `chg` is misleading on a cell touching a stale/unavailable leg** [services/api/.../sym/gateway.py `fx_matrix_live`] — a cell between two unavailable (EOD-fallback) legs had `cur == prior` for both → `chg = 0.00%`, which reads as "flat today" rather than "no live data"; a one-live/one-stale cell showed a half-true partial move. APPLIED: set `prior[ccy] = None` for an unavailable leg so `_fx_grid` yields a **null `chg`** for any cell touching it (the heat map now colours only fully-live crosses; the EOD-fallback rate still shows). Test asserts both the column (`EUR/JPY`) and base (`JPY/EUR`) directions are null + stale. (blind+edge)
- [x] [Review][Patch] **LIVE freshness rollup can never read "unavailable" + inflated coverage** [services/api/.../sym/gateway.py `fx_matrix_live`] — USD (the exact pivot) was auto-counted toward `priced`, so an all-miss board read "delayed · 1/16" instead of "unavailable", diverging from the `index_board_live` sibling. APPLIED: exclude USD from `priced`/`total` (`priced` = legs with a real live quote; `total` = non-USD currencies), with a `total == 0` guard so a USD-only matrix stays `live`. Restores the honest `unavailable` state; live API now reads `15/15` not `16/16`. (edge)
- [x] [Review][Patch] **Test gaps for the rollup boundaries** [services/api/tests/test_fx_matrix_route.py] — APPLIED: added `test_fx_matrix_live_all_unavailable_reads_unavailable` (priced 0 → `unavailable`, EOD-fallback rates with null chg) + `test_fx_matrix_live_all_priced_reads_live` (priced == total → `live`) + the JPY-as-base assertion; reconciled `priced`/`total` (now 1/3) in the partial-coverage test. (edge+auditor)

Dismissed (key ones): **zero/negative-rate divide in `cross_chg`** (blind, "High") — not reachable: FX rates are strictly positive and the live path enforces `price > 0`; identical structure to the pre-existing EOD code. **`setLoading(false)` on an aborted fetch / shared loading paths** (blind, "Med") — matches the post-review WEI sibling exactly (that review *added* this to fix a stuck spinner; the alternative reintroduces the worse bug). **`as_of` null while "live" via a timeless quote** (blind, "Med") — `classify_freshness(None)` returns `delayed`, so a quote with no epoch downgrades the rollup; not reachable. **`useOnline` doesn't cancel an in-flight fetch / TS-union `boardDate`** (blind, Low) — by-design + cosmetic, mirrors WEI. **sim-env footnote omitted** (auditor, Low) — intentional + documented (FX genuinely reads `live`). EOD `_fx_grid` refactor independently **verified byte-identical** (edge) and confirmed by the unchanged `test_fx_matrix_cross_diagonal_and_stale` (6 passed).

## Dev Notes

### Critical conventions (regressions if violated)
- **Live quotes are NEVER persisted** — second data class, off the immutable `fx_rate` star (QH.2 rule).
- **Reuse QH.2 `quotes.py` + the `index_board_live`/`live_heatmap` shape** — do NOT write a new quote
  fetcher or a new freshness scheme. `fetch_quotes_batch` takes plain symbol strings, so the synthetic
  `USD{CCY}=X` FX symbols work with no change to `quotes.py`.
- **The live leg source is `USD{CCY}=X` (probed) = currency-per-USD = the `fx_rate` convention** — USD is
  pinned to 1.0 (no fetch). Don't use `yahoo_symbol_for` (equity path) or the index `yahoo` xref.
- **EOD path must be provably unchanged** — LIVE is additive (new endpoint + toggle). Factor the shared
  grid build; `/fx/matrix` and its tests stay byte-identical.
- **Honest freshness** — per-currency `live|delayed|unavailable`; an unavailable leg falls back to its EOD
  rate (cells stay populated, flagged); partial coverage renders (never blank the grid); the rollup never
  reads fully-"live" while a leg is stale (degrade to `delayed` under partial coverage). Never fabricate a
  live leg. EOD/as-of honesty + per-market staleness idioms carry over ([[feedback_freshness_per_market]],
  [[project_freshness_per_market]]).
- **Canonical `as_of_date`** ([[feedback_as_of_date_canonical_name]]) — EOD only; LIVE takes no date.
- Read-only API, no new dependency, SSR-safe + `react-hooks` newest-wins fetch (QH.8). No Bloomberg IP
  (functional reproduction only — the `monitor-fx-cross-matrix` posture).

### Design decisions (defaults chosen — see Open Questions to override)
- **1D base in LIVE = live cross vs latest EOD cross** (today's move), mirroring `index_board_live`. Not
  the quote's own per-leg `previousClose` (would be a leg-wise prior, not the cross's prior session).
- **Per-currency (leg-level) freshness, not per-cell** — the live rate is per currency; a cell's effective
  freshness is the worse of its two legs, surfaced via the axis-header markers. Simpler + truthful.
- **Both grids go live** — the Spot-rate grid re-derives from live legs; the Spot-%-change grid shows the
  live 1D move. (The page already renders both from the same `cells`.)

### References
- [Source: services/api/.../sym/gateway.py] — `fx_matrix()` (the EOD matrix to share, line ~1277),
  `index_board_live()` (the LIVE-overlay precedent, ~1192), `live_heatmap()` (2-D rollup precedent, ~447).
- [Source: services/api/.../sym/quotes.py] — `fetch_quotes_batch`, `classify_freshness`, `now_epoch`, `RawQuote` (QH.2).
- [Source: services/api/.../sym/router.py] — `/fx/matrix`, `FxMatrix`/`FxCell`/`FxMatrixRow`/`FxCurrencyMeta`,
  `IndexBoardLive`/`LiveHeatmap` envelopes + the `QuoteSourceUnreachable`→503 handler.
- [Source: packages/sym/.../fx/resolve.py] — `fx_rate` (USD-base, currency-per-USD, as-of + staleness).
- [Source: packages/sym/.../fx/convention.py] — `conventional_pair`, `quote_rank` (unchanged in LIVE).
- [Source: apps/web/app/monitor/fx/page.tsx] — the matrix page (add the toggle; `headerMarker`, the two `MatrixCard`s, the `useSyncExternalStore` layout stores, drag-reorder).
- [Source: apps/web/app/monitor/wei/page.tsx] — the LIVE/EOD toggle + live-badge + `autoSec` auto-refresh + `useOnline` UI to mirror.
- Sibling stories: `wei-live-board` (the pattern this copies — its Open Q#4 flagged this story), `monitor-fx-cross-matrix` (the EOD matrix), `qh-2-live-quote-source`, `qh-9-live-heatmap`.

## Open Questions (for Andre — defaults chosen, do not block)
1. **1D base:** default = live cross vs the latest EOD cross ("today's move"). Alt: each leg's own
   `previousClose` from the quote payload (a leg-wise prior). Say if you prefer the latter.
2. **Auto-refresh default:** mirrors WEI — off by default, floored at 3s, `useOnline`-paused. Keep, or
   default it on at some interval?
3. **Coverage of the rollup:** `priced/total` counts CURRENCIES (legs), not cells. Fine, or would you
   rather see a cell-level coverage number?
4. **Scope:** LIVE on `/monitor/fx` only. The Indexes page (`/sym/indices`) single-index charts could get
   a live mark too — a separate story if wanted.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (Claude Code), 2026-06-22

### Completion Notes
- **Re-derive, don't scale.** Because the matrix is N legs (not N per-row series), LIVE just substitutes
  each currency's live USD-base leg and re-runs the SAME `_fx_grid` division — much simpler than the WEI
  per-row endpoint scaling. Factoring `_fx_grid` means EOD and LIVE share one cross-derivation, so they
  can't diverge (the untouched EOD test is the guard).
- **The probe paid off.** `USD{ccy}=X` returns currency-per-USD exactly — no inversion needed; the live
  leg drops straight into the `fx_rate` per-USD slot. USD is the exact pivot (1.0, counts as priced, never
  marked). One subtlety: all rates within a `_fx_grid` call must be ONE numeric type — EOD passes Decimal,
  LIVE casts every leg (incl. the EOD fallbacks) to float, so division never mixes Decimal/float.
- **`chg` = live cross vs latest EOD cross** (`prior` = the EOD leg rates), i.e. "today's move" — mirrors
  `index_board_live`. A cell touching an unavailable (fallback) leg still shows the EOD cross + a stale ●.
- **FX reads `live`, unlike the WEI indices.** FX trades ~24h so quote epochs are fresh → the rollup read
  `live` (16/16) on the first pull and `delayed` minutes later as the same quotes aged past the 120s
  threshold — both honest. I corrected the footnote (the WEI "always delayed" note doesn't apply to FX).
- Verified end-to-end via real-Chrome CDP (clicked the toggle, not just dump-dom): EOD↔LIVE controls swap,
  the badge + per-currency freshness marks render, both grids re-derive. No new dependency; read-only;
  nothing persisted.

### File List
- `services/api/src/qrp_api/modules/sym/gateway.py` (modified — `_fx_grid` shared helper, `fx_matrix` refactor, `fx_matrix_live()`)
- `services/api/src/qrp_api/modules/sym/router.py` (modified — `FxCurrencyMetaLive`/`FxMatrixLive` + `/fx/matrix/live` route)
- `services/api/tests/test_fx_matrix_route.py` (modified — live re-derive + fallback + rollup + 503 tests)
- `apps/web/app/monitor/fx/page.tsx` (modified — EOD/LIVE toggle, live badge, auto-refresh, per-currency freshness markers, mode-aware footnote)
- `apps/web/__tests__/fx-matrix-page.test.tsx` (modified — LIVE toggle test)
- `apps/web/lib/api-types.ts` (regenerated — new `/fx/matrix/live` path)

## Change Log
| Date | Change |
|---|---|
| 2026-06-22 | Created (bmad-create-story, Andre: "I also want my FX matrix to be live similar to wei page"). Apply the proven `wei-live-board` LIVE pattern to the FX matrix: new `GET /api/sym/fx/matrix/live` (live legs from `USD{CCY}=X` quotes — probed in-env = currency-per-USD; USD=1.0; crosses re-derived; live 1D vs latest EOD cross; per-currency freshness + matrix rollup; EOD fallback on a missing leg; never persisted) reusing QH.2 `quotes.py` + the `index_board_live`/`live_heatmap` shape; a LIVE/EOD toggle + live badge + `autoSec` auto-refresh on `/monitor/fx`. The follow-up `wei-live-board` Open Q#4 flagged. Status → ready-for-dev. |
| 2026-06-22 | Dev complete → review. Factored `_fx_grid` (shared EOD/LIVE cross-derivation; EOD byte-identical) + `fx_matrix_live()` (USD{ccy}=X live legs as float, USD=1.0, EOD fallback + `unavailable`, `chg` = live-cross vs latest-EOD-cross, per-currency freshness + rollup) + `GET /api/sym/fx/matrix/live` (`FxMatrixLive`/`FxCurrencyMetaLive`, 503 on a dead provider) + a LIVE/EOD toggle + live badge + per-currency freshness markers + `autoSec` auto-refresh on `/monitor/fx`. 163 api + 135 web green; ruff/tsc/eslint clean; api-types regenerated. Live API 16/16 priced; real-Chrome CDP verified the toggle, badge, freshness marks, grid re-derive, and EOD↔LIVE control swap. Status → review. |
| 2026-06-22 | Code-reviewed (3 adversarial layers) → done. Auditor: all 8 ACs + 6 conventions PASS, no High/Med. 3 patches applied: (1) null `chg` on any cell touching a stale/unavailable leg (`prior=None`) — kills the misleading `0.00%`/half-true move; (2) exclude USD from `priced`/`total` so an all-miss board reads `unavailable` (not `delayed 1/16`), with a `total==0` guard; (3) added all-unavailable→`unavailable` + all-priced→`live` + JPY-as-base tests, reconciled counts. 165 api green; ruff clean; live API now `15/15`. Both Blind-Hunter "High"s dismissed (zero-divide unreachable — FX rates strictly positive; spinner/abort matches the reviewed WEI sibling). Status → done. |
