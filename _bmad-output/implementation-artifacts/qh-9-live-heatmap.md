# Story QH.9: Live heatmap (live/delayed recolor over the EOD treemap)

Status: done

<!-- A genuine live SURFACE (the third, after QH.2's /quotes + live-PnL), not lifecycle-loop
churn — so it clears the QH.8 retro "stop rule". Deferred at QH.2 ("live heatmap"); now buildable
on QH.2's quote source + the QH.7 test harness. -->

## Story

As an **operator watching a universe on the QRP console**,
I want **a LIVE mode on the heat map that recolors the existing treemap by each issuer's live/delayed
return (live price vs prior close) instead of the EOD window return**,
so that **I can SEE intraday movement across a whole universe at a glance — honestly labelled
live/delayed, with uncovered names shown neutral, and never persisted**.

## Scope decision (read first)

The heat map today is **EOD-only**: `heatmap-view.tsx` fetches
`/api/sym/universes/{uid}/heatmap?window=…` → `fact_returns.pr`, and colors cells by that return.
QH.2 built a live quote source (`/api/sym/quotes`, Yahoo v8 chart, honest live/delayed, not
persisted) but **explicitly deferred the live heatmap**. This story adds a LIVE mode that reuses the
EOD heat map's exact constituent assembly (sector / market-cap sizing / share-class collapse) and the
QH.2 quote fetcher, swapping the cell return from EOD `pr` to a **live return = `live_price /
previousClose − 1`** (the quote's own previous close, the QH.2 convention — no extra sym price read).

**The genuinely new infrastructure is batched fan-out.** A universe can be hundreds of issuers
(S&P 500 ≈ 500 quotes per load); the QH.2 serial fetch (8 s timeout each) is unusable at that scale.
This story builds the **bounded `ThreadPoolExecutor` fan-out QH.2 deferred** — capped concurrency,
per-call timeout, an overall time budget — plus a guardrail for very large universes (and the
Yahoo-rate-limit risk is the headline caveat, see Key constraints).

**Hard boundary — nothing persisted.** No writes to `prices_raw` / `fact_returns` / any quote table;
the EOD heat map path is unchanged. Live cells are ephemeral, fetched on demand, returned, discarded.
Out of scope (defer): streaming/SSE auto-refresh, an intraday-history overlay, sparklines per cell.

## Acceptance Criteria

1. **LIVE mode on the heat map.** The window selector gains a **LIVE** option (alongside 1D/1W/…).
   In LIVE mode the console fetches a live endpoint and recolors the SAME treemap (same sizing by
   `market_cap_usd`, same sector grouping, same ±3% diverging scale) by each issuer's live return.
   Switching back to a window restores the EOD view unchanged.
2. **`GET /api/sym/universes/{uid}/heatmap/live` serves the live cells.** Same cell shape as the EOD
   heat map (`ticker, name, sector, industry, market_cap_usd, currency, price, ret`) where `ret` is
   the live return, PLUS per-cell `freshness ∈ {live,delayed,unavailable}`, and top-level
   `as_of` (oldest priced quote, ISO-8601 UTC), `freshness` (worst priced), `priced`/`total`
   coverage. Reuses the EOD constituent query (sector / mcap / issuer-collapse) — NOT a reimplementation.
3. **Batched, bounded fan-out.** Quotes for the universe's representative issuers are fetched via a
   bounded `ThreadPoolExecutor` (capped workers, the QH.2 `fetch_raw_quote` per call with its 8 s
   timeout, and an overall wall-clock budget). Sequential-per-name is NOT acceptable at universe scale.
4. **Honest degradation (reuse QH.2's two-tier pattern).** A per-issuer miss (unmapped MIC, no quote,
   HTTP 4xx) → that cell is `freshness:"unavailable"` with `ret:null` → renders **neutral** (the
   existing `rgbFor(null)` grey), never a fake 0%. A wholly-unreachable provider (every attempted
   symbol network-errors) → the spec'd **503 envelope** (`{error:{type:"unavailable",…}}`), and the
   console shows the badge/Retry, not a blank map. Writes nothing (grep-assert: no INSERT/UPDATE).
5. **Large-universe guardrail.** A bound on how many issuers a single live load will fetch (e.g.
   `LIVE_HEATMAP_MAX`); over-cap → a clear 422 (or a surfaced warning), never an unbounded fan-out
   that could trip Yahoo rate limits. The chosen bound + rationale documented.
6. **Console: honest live affordances.** LIVE mode shows a **live/delayed/unavailable badge**, the
   `as_of`, the `priced/total` coverage, a **refresh** button (O.4-style on-demand), and a "not
   stored" note — reusing the QH.2 analytics-panel badge idiom. `lib/api-types.ts` regenerated for the
   new response model.
7. **Topology-clean, tested, no regressions.** The gateway reuses `qrp_api.modules.sym.quotes` (no
   `sym` package import — the topology gate stays green; the suffix map is already replicated there).
   New tests on the QH.7 harness + the services/api suite: (a) live-heatmap assembly from a mock
   securities read + mock fetch (cell shape, share-class collapse preserved, per-cell freshness);
   (b) bounded fan-out (concurrency cap honored, partial coverage); (c) whole-source-down → 503,
   per-issuer miss → unavailable cell; (d) the LIVE-toggle / badge / neutral-uncovered-cell /
   503→badge-not-blank on the frontend. EOD heat map path unchanged; `test_topology_discipline.py`
   green; no new dependency (stdlib `concurrent.futures` + `urllib`).

## Tasks / Subtasks

- [x] **Task 1 — Batched quote fan-out** (AC: 3,4) — `fetch_quotes_batch(symbols)` in
  `modules/sym/quotes.py`: `ThreadPoolExecutor` (16 workers) + `concurrent.futures.wait` budget (20s),
  de-dupes input, per-symbol miss → None, EVERY completed symbol network-error → `QuoteSourceUnreachable`.
  Tests: partial+dedup, all-network→raise, empty.
- [x] **Task 2 — `DbSymGateway.live_heatmap(uid)`** (AC: 2,3,4,5) — reuses the EOD constituent shape
  (mcap sizing, GICS sector, ISIN issuer-collapse) but selects `s.mic` + keeps the representative figi,
  builds Yahoo symbols, fans out via Task 1, sets each cell `price`/`ret = live_return` + `freshness`;
  rolls up `as_of` (oldest priced) / worst `freshness` / `priced`-`total`; `LIVE_HEATMAP_MAX = 600`
  over-cap → ValueError; uncovered issuer → neutral (`ret` None). No writes (test-asserted).
- [x] **Task 3 — Route + types** (AC: 2,6) — `GET /api/sym/universes/{uid}/heatmap/live` +
  `LiveHeatmap`/`LiveHeatmapCell` models in `router.py`; 404 / 422 / 503 mapping (503 → the app-wide
  `{error:{type:"unavailable"}}` envelope, as QH.2). `gen:types` deferred — it needs the running API,
  and `heatmap-view.tsx` uses LOCAL types (not generated `Schemas`), so nothing consumes it; ledgered
  as a pre-deploy step.
- [x] **Task 4 — Console LIVE mode** (AC: 1,6) — `heatmap-view.tsx`: `● LIVE` option in the window
  selector; LIVE fetches `/heatmap/live` (a refresh nonce re-fetches without changing uni/win);
  recolors by live `ret` (the existing `rgbFor(null)` renders uncovered cells neutral); freshness badge
  + as_of + `priced/total` + refresh + "not stored"; 503 → the existing error block (selectors stay).
- [x] **Task 5 — Tests + verify** (AC: 7) — `test_sym_quotes.py` (+3 batch) + `test_sym_live_heatmap.py`
  (8: recolor/collapse/rollup, writes-nothing, 404/422/503, whole-source). `apps/web/__tests__/heatmap-view.test.tsx`
  (2: LIVE toggle+badge+coverage, 503→error-not-blank). `uv run pytest` **89** (incl. topology gate),
  `npm test` **27**, `eslint .` 0/0, `tsc` clean, `next build` 18/18. Deferrals ledgered.

## Dev Notes

### Current state of files being touched

- **`services/api/src/qrp_api/modules/sym/gateway.py`** (UPDATE) — `heatmap(universe_id, window_code)`
  (lines ~125-228) builds cells from `universe_member_resolution` joined to fundamentals (mcap),
  `gics_scd` (sector/industry), `security_names`, `security_symbology` (ticker/isin), latest
  `prices_raw.close`, and `fact_returns.pr` (the EOD return). It **collapses share classes to one tile
  per issuer** (ISIN chars 3-8, largest-cap class as representative). `live_heatmap` reuses this
  assembly but swaps `fr.pr` for a live return and needs the representative's **`s.mic`** (already a
  column on `securities`) to build the Yahoo symbol. `quotes()` (QH.2) is the existing figi→symbol→fetch
  precedent to mirror.
- **`services/api/src/qrp_api/modules/sym/quotes.py`** (UPDATE) — QH.2 fetcher: `fetch_raw_quote`,
  `yahoo_symbol_for`, `live_return`, `classify_freshness`, `YAHOO_SUFFIX` (replicated, NOT imported).
  Add `fetch_quotes_batch` (the bounded fan-out QH.2 deferred). stdlib only.
- **`services/api/src/qrp_api/modules/sym/router.py`** (UPDATE) — add the `LiveHeatmap` model + the
  `/heatmap/live` route; map `LookupError`→404, over-cap→422, `QuoteSourceUnreachable`→503 (the global
  `http_exception_envelope` already produces the `{error:{type:"unavailable"}}` shape — see QH.2).
- **`apps/web/components/heatmap-view.tsx`** (UPDATE) — treemap (d3-hierarchy); `rgbFor(ret, isDark)`
  already renders `ret==null` as neutral grey (so uncovered live cells need no new color path); `win`/
  `setWin` window selector + `?window=` fetch. Add the LIVE option, the live fetch, and the badge.

### Key constraints

- **Yahoo rate-limit is the headline risk.** ~500 requests per live load of a large universe can trip
  Yahoo throttling. Mitigations in scope: bounded concurrency (Task 1), `LIVE_HEATMAP_MAX` (AC5), and
  — decide during dev — a small **process-local in-memory TTL cache** (the QH.2-deferred dedupe; a few
  seconds, keyed by yahoo_symbol, dies with the process; **never a DB table**, per the QH.2 caching
  decision). If the cache isn't added, ledger it.
- **Live return base = the quote's own `previousClose`** (QH.2 convention) — keeps it a pure ratio
  (FX-naive, like EOD `pr`) and avoids a sym price read / read-surface change. `px.close` is already in
  the query if a sym-close base is ever preferred, but default to the quote's previousClose.
- **No persistence, no new dependency** (`concurrent.futures` + `urllib` are stdlib). EOD heat map
  path, `prices_raw`, `fact_returns` all untouched. Topology gate: reuse `quotes.py`, no `sym` import.
- **Honest labelling:** per-cell freshness from `regularMarketTime`; the map-level badge is the worst
  priced cell; uncovered names are neutral, never a fake 0%.

### References

- [Source: _bmad-output/implementation-artifacts/qh-2-live-quote-source.md] — the quote source, the
  two-tier degradation, the not-persisted boundary, and the `live_heatmap` deferral.
- [Source: services/api/src/qrp_api/modules/sym/gateway.py#heatmap] — the constituent assembly + issuer-collapse to reuse.
- [Source: services/api/src/qrp_api/modules/sym/quotes.py] — `fetch_raw_quote`/`live_return`/`yahoo_symbol_for` to reuse; add `fetch_quotes_batch`.
- [Source: apps/web/components/heatmap-view.tsx#rgbFor, win selector] — null→neutral coloring + where the LIVE option/badge go.
- [Source: deferred-work.md — QH.2 ledger] — "live heatmap" + "ThreadPool fan-out" + "in-memory TTL cache", all consumed/decided here.
- [Source: epic-qh-retro-2026-06-16b.md] — the stop rule (this is a feature surface, not loop churn → in scope).

### Project Structure Notes

- New: `live_heatmap()` gateway method + `fetch_quotes_batch()` + a `LiveHeatmap` model/route; UPDATE
  the heat map component. No migration. `api-types.ts` regenerated. New tests on the QH.7 harness +
  services/api.
- Deferred (ledger): SSE/auto-refresh of the live heat map, intraday-history overlay, per-cell
  sparklines, multi-provider fallback.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- `uv run pytest` (`services/api`, `QRP_ENABLED_MODULES=sym`) → **89 passed** (+11: 3 batch + 5 live_heatmap gateway + 3 route), incl. `test_topology_discipline.py`. `ruff check` clean.
- `npm test` → **27 passed** (+2: LIVE toggle/badge/coverage, 503→error-not-blank). `eslint .` 0/0, `tsc --noEmit` clean, `next build` 18/18.
- One test fix: keyed the unavailable-cell assertion on the ticker (`XYZ`) not the name (`NoMap`).

### Completion Notes List

- **Batched fan-out is the new infra.** `fetch_quotes_batch` (sym-only; the analytics twin doesn't need it) uses `ThreadPoolExecutor(16)` + a `wait(timeout=20s)` budget; symbols not done in budget read as `unavailable` (honest). It mirrors QH.2's two-tier contract — per-symbol miss = None, all-completed-network-error = `QuoteSourceUnreachable` → 503.
- **`live_heatmap` reuses the EOD assembly, not a reimplementation** — same mcap sizing / GICS sector / ISIN issuer-collapse (largest-cap class), swapping `fact_returns.pr` for `live_return(price, previousClose)` from the quote's own previous close (QH.2 convention; FX-naive ratio, no sym price read). Uncovered issuers → `ret` None → the existing `rgbFor(null)` neutral grey, never a fake 0%.
- **Rate-limit guardrail:** `LIVE_HEATMAP_MAX = 600` (S&P 500 fits) → over-cap is a 422, never an unbounded fan-out. The in-memory TTL cache (QH.2-deferred) was NOT added — bounded concurrency + the cap suffice at owner scale; ledgered if request volume grows.
- **Not persisted, no new dependency** (`concurrent.futures` + `urllib` are stdlib). EOD heatmap path, `prices_raw`, `fact_returns` untouched. Topology-clean: the gateway reuses `quotes.py` (no `sym` import); the gate stays green.
- **`gen:types` not run** — it requires the live API (`openapi-typescript` hits `127.0.0.1:8001`), and `heatmap-view.tsx` uses local `Heatmap`/`Cell` types, so nothing consumes the generated `LiveHeatmap`. Pre-deploy step, ledgered.
- **Deferred (ledger):** SSE/auto-refresh (the heatmap is pull-mark-discard, not streamed), intraday-history overlay, per-cell sparklines, multi-provider fallback, in-memory TTL cache, `api-types.ts` regen.

### File List

- `services/api/src/qrp_api/modules/sym/quotes.py` (UPDATE) — `fetch_quotes_batch` + bounded-fan-out constants; `concurrent.futures` import.
- `services/api/src/qrp_api/modules/sym/gateway.py` (UPDATE) — `live_heatmap()` + `LIVE_HEATMAP_MAX`.
- `services/api/src/qrp_api/modules/sym/router.py` (UPDATE) — `LiveHeatmap`/`LiveHeatmapCell` models + `GET /universes/{uid}/heatmap/live`.
- `apps/web/components/heatmap-view.tsx` (UPDATE) — LIVE window option, live fetch + refresh nonce, freshness badge/coverage/as_of.
- `services/api/tests/test_sym_quotes.py` (UPDATE) — +3 batch tests.
- `services/api/tests/test_sym_live_heatmap.py` (NEW) — 8 tests (gateway + route).
- `apps/web/__tests__/heatmap-view.test.tsx` (NEW) — 2 tests (LIVE mode).

### Change Log

- 2026-06-16 — Implemented QH.9: live heatmap. `GET /api/sym/universes/{uid}/heatmap/live` reuses the
  EOD constituent assembly with live returns from the QH.2 quote source via a new bounded
  `ThreadPoolExecutor` fan-out (`LIVE_HEATMAP_MAX` guardrail); console LIVE window mode recolors the
  treemap + shows a live/delayed/unavailable badge + coverage + refresh; uncovered issuers neutral;
  not persisted; two-tier degradation (per-issuer unavailable / whole-source 503). 89 api + 27 console
  tests, eslint 0/0, tsc + build green. Status → review.
- 2026-06-16 — Code review (3 layers; Auditor confirmed AC1–AC5/AC7 met): 2 patches applied — the
  fan-out budget is now actually enforced (`shutdown(wait=False, cancel_futures=True)` + tightened the
  503 to all-symbols-errored, with a budget test), and the live badge is gated on `!loading` (no stale
  cross-universe coverage). 6 deferred, 5 dismissed. `uv run pytest` 90, `npm test` 27, eslint 0/0,
  tsc + build green. Status → done.

## Review Findings (code review 2026-06-16)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor). Auditor confirmed AC1–AC5 + AC7 met; the two real defects are below.

### Patch (unchecked = open)

- [x] [Review][Patch] Fan-out wall-clock budget is NOT enforced — `with ThreadPoolExecutor()` exit blocks on all futures [services/api/src/qrp_api/modules/sym/quotes.py fetch_quotes_batch] — FIXED: replaced the `with` block with explicit `shutdown(wait=False, cancel_futures=True)` in a `finally`, so `wait(timeout=budget)` actually bounds the response; tightened the 503 to `net_errors == len(syms)`. Added `test_fetch_quotes_batch_honors_budget` (a hung fake future → returns at ~budget, slow symbol None) — fails pre-fix. — `wait(timeout=budget)` returns, but leaving the `with` calls `shutdown(wait=True)`, blocking until EVERY submitted task finishes; a hung provider stalls the request for ~8 s × ceil(N/16), not 20 s. Fix: `shutdown(wait=False, cancel_futures=True)` (don't rely on the context-manager exit), and tighten the 503 raise to `net_errors == len(syms)` (all symbols network-errored — avoids a spurious 503 from a biased small completed-sample under budget pressure). Add a budget-enforcement test (a slow fake future → returns within budget, slow symbol → None). Both Blind + Edge flagged HIGH.
- [x] [Review][Patch] Stale live badge on universe switch — previous universe's freshness/coverage/as_of shows during the refetch [apps/web/components/heatmap-view.tsx badge block] — FIXED: the badge is now gated on `!loading`, so it hides during the refetch and never attributes the old universe's coverage to the new one. — `data` isn't cleared on a uni/win change, so the LIVE badge attributes the OLD universe's `priced/total`/`freshness`/`as_of` to the new one until the (multi-second) fan-out resolves. Fix: gate the badge on `!loading` so it hides during the refetch.

### Deferred (beyond-AC / minor — ledgered)

- [x] [Review][Defer] No AbortController on the heatmap fetch — the per-run `alive` guard already prevents the stale-STATE overwrite (newest-wins holds); AbortController would only CANCEL the in-flight network request (efficiency), so it's an optimization, not a correctness fix [heatmap-view.tsx].
- [x] [Review][Defer] `new Date(as_of)` has no invalid-date guard (backend emits ISO-8601; defensive only) [heatmap-view.tsx] — same low-pri class dismissed in QH.7/QH.8.
- [x] [Review][Defer] EOD footer momentarily reads "colored by LIVE return" during a LIVE→EOD toggle (stale `data.window` until refetch) — cosmetic [heatmap-view.tsx].
- [x] [Review][Defer] `id(rep)` keying of the symbol map works (reps held live throughout) but is a footgun vs an index/inline key [gateway.py live_heatmap].
- [x] [Review][Defer] ↻ refresh isn't disabled while loading — overlapping fetches are state-safe via `alive`, just sloppy UX [heatmap-view.tsx].
- [x] [Review][Defer] `gen:types` not run / `lib/api-types.ts` not regenerated (AC6) — needs the running API; `heatmap-view.tsx` uses LOCAL types so nothing consumes the generated `LiveHeatmap`. Pre-deploy step (also in QH.9 completion notes).

### Dismissed

- AC7 "topology gate stays green" is vacuous for `services/api`'s sym module (the gate scopes `packages/` consumers, deliberately excluding the sym owner's serving surface) — the no-`sym`-import property still holds by inspection (gateway imports only `quotes`/`freshness`); framing nuance, not a defect.
- `as_of` = oldest priced quote labelled "as of {time}" — intentional worst-case labelling (documented).
- budget-expired symbol (None) indistinguishable from a real miss — documented in the fetcher docstring; both render neutral honestly.
- "writes nothing" test scans `conn.seen` for INSERT/UPDATE — weak but documents intent; the live path is provably SELECT-only + an external GET.
- over-cap test doesn't assert "422 before fan-out" — the ordering is correct by inspection (raise precedes `fetch_quotes_batch`).
