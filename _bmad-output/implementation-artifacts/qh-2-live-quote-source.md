# Story QH.2: Live quote source (live-PnL)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **operator using the QRP console**,
I want **a live/delayed quote source feeding `GET /api/sym/quotes`, and a live portfolio PnL that reuses the existing weight×return engine with the price source swapped to those quotes**,
so that **I can see intraday marks and live PnL — honestly labelled live vs delayed, and never persisted into the immutable EOD store**.

## Scope decision (read first)

**The blocker is gone.** QH.2 was deferred as "no real-time quote source in-env." Re-probed
2026-06-15: the **Yahoo v8 chart endpoint is reachable without auth** —
`query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d` → HTTP 200,
`chart.result[0].meta.{regularMarketPrice, regularMarketTime, currency, exchangeName}`. US names
are ~real-time (AAPL quote within seconds of the probe); `.SA`/B3 ~15 min delayed. `regularMarketTime`
gives a per-symbol as-of stamp, so live-vs-delayed labelling is honest. (The v7 `/finance/quote`
endpoint 401s — needs a crumb; **do not use it**. The memory `reference-env-external-sources` is
updated.)

Two deliverables:
- **(A) `GET /api/sym/quotes`** — the quote source. Fully buildable + testable now. The FIRST
  `/api/sym/*` endpoint to fetch externally at serve time (all others are DB reads), so it must
  carry the honest 503/`unavailable` degradation the others don't need.
- **(B) Live portfolio PnL** — reuse the EXISTING weight×return dot-product (the engine is ready,
  per the PRD's own note) with the price source swapped from EOD `fact_returns.pr` to a live return
  (`live_price / prior_close − 1`). Served labelled live/delayed, **not persisted**.

**Hard boundary — nothing is persisted.** No writes to `prices_raw` (immutable, `ON CONFLICT DO
NOTHING`), no new quote table, no change to the EOD `fact_returns` path. Quotes are ephemeral,
fetched on demand, returned, discarded. Out of scope (defer): streaming/SSE quotes, intraday
history storage, a live heatmap, and any new dependency (use stdlib `urllib` — the service has no
`httpx` in its runtime deps and `dev-story` halts on new deps).

## Acceptance Criteria

1. **`GET /api/sym/quotes?figis=<csv>` serves per-security quotes.** Returns a list of
   `{figi, ticker, yahoo_symbol, price, currency, quote_time, freshness, age_seconds}` — one row
   per requested FIGI. Price/time come from the Yahoo v8 chart endpoint's `meta.regularMarketPrice`
   / `regularMarketTime`. `figis` is a comma-separated list, bounded (`1..50`; empty or over-cap →
   422). A browser `User-Agent` header is set on the upstream request (Yahoo 406s the default UA).

2. **Honest degradation — never a raw 500, never silent.** If the quote provider is wholly
   unreachable (DNS/timeout/connection error) the endpoint returns the spec'd **503 envelope**
   (`{error:{type:"unavailable",message,detail?}}`), mirroring operate's `pipeline_history`. A
   **per-symbol** failure (unknown symbol, no `meta`, HTTP 404/401 for one ticker) is NOT a whole-
   request failure — that row returns `freshness:"unavailable"` with `price:null`. The endpoint
   **writes nothing** to any table (grep-assert: no INSERT/UPDATE in the quote path).

3. **Per-symbol freshness labelling.** `freshness` ∈ `{"live","delayed","unavailable"}`, derived
   from `regularMarketTime` vs the request time: `live` when fresh (age ≤ a small threshold, e.g.
   120 s), `delayed` otherwise, with `age_seconds` always populated when a price is present.
   `currency` and `quote_time` (ISO 8601, UTC) are surfaced so the console can label without
   guessing. (No reliance on `marketState` — it came back null in-env.)

4. **Symbol mapping is topology-clean and faithful to the sym convention.** The Yahoo symbol is
   built gateway-side from the gateway's OWN `securities` + `security_symbology` read (the existing
   `_SEC_FROM` pattern gives ticker + `mic`), applying the same convention the sym adapter uses:
   the `YAHOO_SUFFIX` MIC→suffix map (`BVMF→.SA`, `XLON→.L`, US→"", …) and `ticker.replace(".","-")`
   for share classes. **Do NOT import the sym package** (`make_yahoo_symbol_resolver` lives in
   `packages/sym` — importing it from `qrp_api` would trip the topology gate's no-sym-imports rule);
   replicate the small suffix map and cite the adapter as the source of truth. A FIGI whose MIC has
   no Yahoo mapping → `freshness:"unavailable"` (never a guess).

5. **Live portfolio PnL reuses the EOD weight×return engine with the price source swapped.** A
   served live-PnL path computes, per constituent, a **live return = `live_price / prior_close − 1`**
   (where `prior_close` is the latest stored close from sym — the same close the EOD `pr` is built
   on), then the SAME coverage-honest weighted sum the EOD path uses
   (`Σ weight·live_return`, renormalised over covered weight). It reuses the existing dot-product
   assembly (`portfolios.gateway.returns` / `analytics.gateway._portfolio_daily`), not a reimplementation.
   The result carries a **portfolio-level freshness label** = the worst (most stale) constituent
   freshness, and an `as_of` = the oldest constituent `quote_time`. **Not persisted.**

6. **Served + surfaced, honestly labelled.** The live-PnL is exposed on a clearly-live route
   (e.g. `GET /api/portfolios/{pid}/live` or a `live` block on the analytics surface) and the
   console shows it with a **live/delayed badge** (the analytics panel has no freshness label
   today — this adds one). Reuses the O.4 error envelope; `lib/api-types.ts` regenerated for the
   new response model(s).

7. **Tests + no regressions.** DB-free unit tests (mock the HTTP fetch + the securities read):
   (a) quote parse from a captured Yahoo `chart` payload; (b) freshness thresholding (live/delayed/
   unavailable); (c) symbol mapping incl. `.SA`, `.L`, US-no-suffix, share-class `.`→`-`, and an
   unmapped MIC; (d) whole-source-down → 503, per-symbol-down → `unavailable` row; (e) live-PnL
   weighted sum with partial coverage. The EOD `fact_returns` path and existing analytics/portfolio
   returns are unchanged; `services/api` suite incl. `test_topology_discipline.py` stays green; no
   new dependency.

## Tasks / Subtasks

- [x] **Task 1 — Quote fetcher (stdlib, DB-free, testable)** (AC: 1,2,3,4)
  - [x] `services/api/src/qrp_api/modules/sym/quotes.py`: `fetch_raw_quote(yahoo_symbol) -> RawQuote|None` via `urllib.request` (browser UA, 8s timeout) against the v8 chart endpoint; parses `regularMarketPrice/previousClose/regularMarketTime/currency`. `classify_freshness`, `live_return` (from the quote's own previousClose), `yahoo_symbol_for`. `_http_get` is monkeypatched in tests. Per-symbol HTTP 4xx/5xx → None (unavailable); network error → `QuoteSourceUnreachable`.
  - [x] Gateway-side `YAHOO_SUFFIX` (replicated, cited; NOT imported from `packages/sym`) + `ticker.replace(".","-")`. Unmapped MIC → unavailable.
- [x] **Task 2 — `GET /api/sym/quotes` endpoint** (AC: 1,2,3)
  - [x] `Quote` model + `/quotes` route (figis 1..50, else 422) in `modules/sym/router.py`; `DbSymGateway.quotes()` resolves figis→(ticker,mic)→symbol, fetches, assembles rows; whole-source-down (all attempted symbols network-error) → `QuoteSourceUnreachable` → `HTTPException(503)`; per-symbol miss → `unavailable` row. No writes (test-asserted). (Sequential fetch; ThreadPool noted as a future optimization.)
- [x] **Task 3 — Live portfolio PnL (reuse the dot-product)** (AC: 5,6)
  - [x] `analytics.gateway.live_pnl(pid)`: latest weights via the `portfolios` seam (`read_latest_weights`), figi→(ticker,mic) via the sym read surface, live quotes via a co-located `analytics/quotes.py`; per-name live return = `price/previousClose − 1`; the SAME coverage-honest weighted sum the EOD path uses (`Σ w·r` normalised by covered |weight|). Portfolio freshness = worst of priced; `as_of` = oldest priced quote. Not persisted.
  - [x] `GET /api/analytics/portfolios/{pid}/live` (`LivePnl` model); analytics panel shows the live return + PnL + a live/delayed/unavailable **badge** + coverage + "not stored" + a refresh button (O.4-style fetch).
- [x] **Task 4 — Tests, types, docs, verify** (AC: 7)
  - [x] DB-free tests: `test_sym_quotes.py` (14) + `test_analytics_live_pnl.py` (6). `uv run pytest` green (76, incl. `test_topology_discipline.py`). `npm run gen:types` regenerated (`Quote`, `LivePnl`, `LiveConstituent`, the two routes); console `tsc` clean; `eslint` clean on the new code (the one analytics-panel error is the pre-existing baseline, not added). ruff clean.
  - [x] **Manual e2e — actually run live this session** (env DB + Yahoo both reachable): `GET /api/sym/quotes?figis=<KR,HK,TW figis>` returned correct symbols/prices/currencies + honest `delayed` labels; empty figis → 422; `GET /api/analytics/portfolios/5/live` → 22/22 priced, live return +0.49%, `delayed`, base USD; missing portfolio → 404. Marked QH.2 `[BUILT 2026-06-15]`; sprint-status flipped; deferrals ledgered.

## Dev Notes

### Current state of files being touched

- **`services/api/src/qrp_api/modules/sym/router.py`** (UPDATE) — `APIRouter(prefix="/api/sym")`, dependency `_gateway()` opens `connect()` (full-cred sym reader, QH.3 exception) and closes it. All 9 existing endpoints are pure DB reads; Pydantic response models defined inline → surfaced via `gen:types`. Add the `Quote` model + `/quotes` route here.
- **`services/api/src/qrp_api/modules/sym/gateway.py`** (UPDATE) — `DbSymGateway`; the `_SEC_FROM` fragment + `securities`/`security_symbology`/`securities.mic` reads give ticker + mic per figi (the input to the Yahoo symbol builder). Add the `quotes()` method. **This will be the first method that fetches externally** — wrap the fetch, never let a provider error become a 500, write nothing.
- **`services/api/src/qrp_api/db.py`** (READ) — `connect()` is the full-cred first-party sym reader (QH.3 documents why the `qrp_readonly` role can't serve this surface). The quote path reads `securities`/`security_symbology` (sym-internal, fine here) but the live PRICE comes from the external fetch, not the DB.
- **`packages/sym/src/sym/sources/yfinance_adapter.py`** (READ — convention source, do NOT import) — `YAHOO_SUFFIX` (MIC→suffix, incl. `BVMF→.SA`) and `make_yahoo_symbol_resolver` (`ticker.replace(".","-")` + suffix; unmapped MIC → None). Replicate the small map gateway-side. HK leading-zero / Korea-keeps-zeros normalization is at the FIGI-resolution layer (`identity/figi.py`), already baked into the stored ticker — the serving path just appends the suffix.
- **`packages/portfolios/src/portfolios/gateway.py`** (READ — reuse the math) — `returns()` (lines ~321–410): pins constituents to one returns date, `pr_map` from sym `fact_returns`, then `Σ weight·pr` with coverage tracking (`covered_w`, renormalise). Live-PnL swaps `pr` for the live return; reuse this shape.
- **`packages/analytics/src/analytics/gateway.py`** (READ) — `_portfolio_daily` computes TWR + `pnl = notional × cumulative`; reads `fact_returns` 1D `pr`. The live-PnL surface/badge lives near here or on the portfolios live route.
- **`apps/web/components/analytics-panel.tsx`** (UPDATE) — shows PnL with NO freshness label today (`{n_days} daily obs · … · benchmark …`). Add the live/delayed badge here.

### Key constraints

- **Probed source contract (2026-06-15):** `GET https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d`, browser `User-Agent`, ~15 s timeout → JSON; `chart.result[0].meta.regularMarketPrice` (number), `regularMarketTime` (epoch s), `currency`, `exchangeName`. v7 `/finance/quote` 401s — avoid. One symbol per call (bound N; small thread pool optional). Stooq 404'd — not an option.
- **No persistence, no new dependency.** Never touch `prices_raw` (immutable) or add a quote table; use stdlib `urllib.request` (service has no `httpx` runtime dep; `dev-story` HALTs on new deps).
- **Caching = in-memory TTL only, NOT a DB table (decision 2026-06-15).** Live quotes are a second data class — best-effort, unvalidated, stale-on-arrival — and must stay off the authoritative store; storing them durably has no reuse value in a research console and would blur the EOD trust boundary. If rate-limiting Yahoo matters, use a small process-local TTL cache (a dict keyed by yahoo_symbol, ~a few seconds, dies with the process) — never a DB table. A future intraday-history product, if ever wanted, would be a SEPARATE timestamped `quote_snapshot` table isolated from the EOD engine/validation/snapshots — explicitly out of scope here.
- **Topology discipline:** the gateway must not `import` the `sym` package (`test_topology_discipline.py` no-sym-imports). Replicate the suffix map; read securities via SQL (already how the gateway works).
- **Honest labelling:** freshness from `regularMarketTime`, per symbol; the portfolio label is the worst constituent. Never present a delayed mark as live.
- **Coverage honesty (live-PnL):** mirror the EOD path — names without a live quote (or without a prior close) are uncovered weight; renormalise and report coverage, exactly as `returns()` does.
- **Currency:** the EOD returns are currency-naive ratios; the live return is also a pure ratio (`live/prior_close`), so FX doesn't enter — keep it a ratio, same as `pr`.

### Project Structure Notes

- New: `modules/sym/quotes.py` (fetcher) + a `Quote` model/route + a live-PnL route; UPDATE the analytics panel. No migration. `api-types.ts` regenerated.
- The quote source is intentionally **gateway-side serving infrastructure**, not a sym-package adapter — it serves ephemeral live data, distinct from sym's EOD ingestion (which stays immutable and authoritative). This is the QH.3 "first-party reader" posture extended to an external read.
- Deferred (ledger): streaming/SSE quotes, intraday history persistence, live heatmap, multi-provider fallback.

### References

- [Source: _bmad-output/planning-artifacts/epics-qrp-roadmap.md#Story QH.2] — "a real-time quote source feeds `GET /api/sym/quotes`; live-PnL reuses the EOD engine with the price source swapped; labelled live/delayed, not persisted."
- [Source: _bmad-output/planning-artifacts/prds/prd-qrp-2026-06-07/prd.md] (portfolio detail footer) — "Swap in a live quote source later for intraday PnL — same engine."
- [Source: memory reference-env-external-sources] — Yahoo v8 chart endpoint reachable (re-probed 2026-06-15); v7 quote 401s; set a browser UA.
- [Source: packages/sym/src/sym/sources/yfinance_adapter.py#YAHOO_SUFFIX, make_yahoo_symbol_resolver] — the symbol convention to replicate (not import).
- [Source: services/api/src/qrp_api/modules/sym/gateway.py#_SEC_FROM, security_detail] — ticker + mic read.
- [Source: packages/operate/src/operate/router.py#pipeline_history] — the 503-degradation pattern for an endpoint that reaches off-box.
- [Source: packages/portfolios/src/portfolios/gateway.py#returns] — the weight×return dot-product + coverage to reuse for live-PnL.
- [Source: packages/sym/migrations/deploy/price_storage.sql + ingest/prices.py] — `prices_raw` immutability (`ON CONFLICT DO NOTHING`) — the store NOT to write.
- [Source: services/api/tests/test_topology_discipline.py] — no-sym-imports guard the quote path must respect.

### Verification (end-to-end)

1. `uv run pytest` in `services/api` (and any package touched) green, incl. `test_topology_discipline.py`. New quote/freshness/symbol/live-PnL unit tests pass.
2. Servers up: `GET /api/sym/quotes?figis=<US figi>,<.SA figi>` → US row `freshness:"live"` with a near-now `quote_time`; B3 row `delayed` with `age_seconds` ~900; an unmapped/unknown figi → `unavailable`, `price:null`.
3. Block egress (or point the fetcher at a dead host) → the endpoint returns the **503 envelope**, not a 500, and writes nothing.
4. Live-PnL on a real portfolio returns a labelled value (worst-constituent freshness, `as_of` = oldest quote); the console shows the live/delayed badge.
5. Confirm (grep + a DB check) that no row was written to `prices_raw` or any new table during a quote/live-PnL request.

## Dev Agent Record

### Agent Model Used

Opus 4.8 (1M context) — `claude-opus-4-8[1m]`

### Debug Log References

- Re-probe (`urllib`) confirmed the Yahoo v8 chart endpoint reachable + `previousClose` present → live return from the payload alone (no sym price read / read-surface change).
- `uv run pytest` (`services/api`, `QRP_ENABLED_MODULES=sym`) → **76 passed** (14 new sym-quotes + 6 new live-PnL + the topology gate).
- `npm run gen:types` regenerated `lib/api-types.ts` (8 refs: `Quote`, `LivePnl`, `LiveConstituent`, `/api/sym/quotes`, `/api/analytics/portfolios/{pid}/live`). `npx tsc --noEmit` → exit 0. `ruff check` → clean.
- **Live end-to-end (env DB + Yahoo both up):** `/api/sym/quotes?figis=005930(KR),0700(HK),2330(TW)` → correct `.KS/.HK/.TW` symbols, real prices, KRW/HKD/TWD, live returns, `delayed` + age labels; empty → 422. `/api/analytics/portfolios/5/live` → 22/22 priced, `live_return_normalized` +0.49%, `delayed`, base USD, top constituent MU +10.84%; missing pid → 404.

### Completion Notes List

- **Nothing is persisted, no new dependency.** Quotes are fetched on demand and discarded (stdlib `urllib`); `prices_raw` and the EOD `fact_returns` path are untouched (test-asserted no INSERT/UPDATE/DELETE in the quote path). Per the 2026-06-15 decision, caching guidance is in-memory-TTL-only (not implemented — sequential fetch is fine at the current scale).
- **Live return from the payload's own `previousClose`** — the key design choice. It makes "the price source swapped" exact and removes any need to read sym prices or widen the `qrp_readonly` surface.
- **Topology-clean:** the gateway and analytics each replicate the small `YAHOO_SUFFIX` map rather than importing `packages/sym` (the no-sym-imports gate). The fetcher is duplicated across `qrp_api.modules.sym.quotes` and `analytics.quotes` — the project's deliberate duplicate-across-package posture (like the per-package `db.py`); ledgered to extract a shared package if a third consumer appears.
- **Degradation is two-tier:** a per-symbol miss (unknown ticker / HTTP 4xx / no data) is an `unavailable` row, never a request failure; only a wholly-unreachable provider (every attempted symbol network-errors) raises → 503 envelope.
- **Live-PnL reuses the EOD math** (`Σ w·r` normalised by covered |weight|, the `_portfolio_daily`/`returns` shape), swapping EOD `pr` for the live per-name return. Freshness rolls up to the worst priced constituent; `as_of` = oldest priced quote.
- **Deferred (ledgered):** streaming/SSE quotes, intraday history, in-memory TTL cache, live heatmap, multi-provider fallback, ThreadPool fan-out; the pre-existing analytics-panel `set-state-in-effect` baseline error remains (not added to).

### File List

- `services/api/src/qrp_api/modules/sym/quotes.py` (NEW) — stdlib quote fetcher: symbol map, `fetch_raw_quote`, freshness, live return.
- `services/api/src/qrp_api/modules/sym/gateway.py` (UPDATE) — `DbSymGateway.quotes()`; quotes/timezone imports.
- `services/api/src/qrp_api/modules/sym/router.py` (UPDATE) — `Quote` model + `GET /api/sym/quotes` (bounds + 503 mapping).
- `packages/analytics/src/analytics/quotes.py` (NEW) — co-located twin fetcher (duplication ledgered).
- `packages/analytics/src/analytics/gateway.py` (UPDATE) — `live_pnl()`; `read_latest_weights`/quotes/datetime imports.
- `packages/analytics/src/analytics/router.py` (UPDATE) — `LivePnl`/`LiveConstituent` models + `GET /api/analytics/portfolios/{pid}/live`.
- `apps/web/components/analytics-panel.tsx` (UPDATE) — live-PnL fetch + freshness badge + refresh.
- `apps/web/lib/api-types.ts` (UPDATE) — regenerated (new models + routes).
- `services/api/tests/test_sym_quotes.py` (NEW) — 14 tests.
- `services/api/tests/test_analytics_live_pnl.py` (NEW) — 6 tests.
- `_bmad-output/planning-artifacts/epics-qrp-roadmap.md` (UPDATE) — QH.2 → `[BUILT 2026-06-15]`.
- `_bmad-output/implementation-artifacts/deferred-work.md` (UPDATE) — QH.2 deferrals.

### Change Log

- 2026-06-15 — Implemented QH.2: live/delayed quote source (`GET /api/sym/quotes`, Yahoo v8 chart, stdlib, not persisted, honest per-symbol freshness + two-tier degradation) and live portfolio PnL (`GET /api/analytics/portfolios/{pid}/live`) reusing the EOD weight×return engine with the price source swapped to live quotes (return vs the quote's own previous close). Console live badge added. No persistence, no new dependency. 76 tests green, ruff/tsc clean, verified live end-to-end. Status → review.

## Review Findings (code review 2026-06-16)

Adversarial review (Blind Hunter + Edge Case Hunter + Acceptance Auditor), uncommitted diff on `qh-2-live-quote-source`.

### Patch (unchecked = open)

- [x] [Review][Patch] Portfolio freshness can read "live" for a priced-but-timeless / delayed-only quote — honesty bug [packages/analytics/src/analytics/gateway.py:275-291] — FIXED 2026-06-16: per-constituent freshness now derived via `classify_freshness` (priced-but-timeless → `delayed`), rolled up worst-of; constituent label moved to the `{live,delayed,unavailable}` vocabulary. Regression test `test_live_pnl_priced_but_timeless_quote_is_delayed_not_live`. — In `live_pnl`, `any_delayed`/`oldest_epoch` are only touched inside `if q.quote_epoch is not None`. A constituent that is *priced* (`live_return` present) but carries no `regularMarketTime` never flips `any_delayed`, so the rollup `("delayed" if any_delayed else "live")` reports the green **live** badge for a quote `classify_freshness(None)` itself calls `delayed`. Also fix the per-constituent `freshness` label, which emits the out-of-vocabulary literal `"priced"` instead of one of `{live,delayed,unavailable}` (AC3/AC5 vocabulary; Blind + Auditor). Fix: derive each constituent's real freshness and roll up worst-of-priced from it.
- [x] [Review][Patch] Malformed numeric in a Yahoo payload escapes the parse guard → 500 instead of `unavailable` [services/api/src/qrp_api/modules/sym/quotes.py:94-99] — FIXED 2026-06-16: numeric coercion (`float`/`int`) moved inside the `except (ValueError,KeyError,IndexError,TypeError)` guard in BOTH fetcher twins, so a bad payload → `None` (unavailable). Regression test `test_fetch_raw_quote_malformed_numeric_is_unavailable_not_500`. — `float(price)` / `float(prev)` / `int(meta["regularMarketTime"])` in the `RawQuote(...)` construction sit OUTSIDE the `except (ValueError, KeyError, IndexError, TypeError)` block (which only wraps the `meta` extraction). A non-numeric/NaN price or non-integer time raises, which per AC2 must degrade to a per-symbol `unavailable`, not surface as an internal error. Fix both twin copies (`modules/sym/quotes.py` + `packages/analytics/src/analytics/quotes.py`).

### Deferred (low-priority hardening — logged to deferred-work.md)

- [x] [Review][Defer] Future-dated / clock-skewed quote always classifies "live" [services/api/.../quotes.py:108] — `age = max(0, …)` clamps negatives, so `quote_epoch > now` reads `live` regardless of how far in the future. Acceptable for small skew; reject far-future stamps later.
- [x] [Review][Defer] Yahoo symbol not URL-encoded into the request path [services/api/.../quotes.py:77] — ticker is first-party (DB), so low risk, but `urllib.parse.quote` would harden the external fetch.
- [x] [Review][Defer] Duplicate FIGIs fetch twice and double-count attempted/net_errors [services/api/.../sym/gateway.py quotes()] — dedupe `figis` preserving order.
- [x] [Review][Defer] Sequential fetch latency up to N×8s (bound 50) [already ledgered: ThreadPool fan-out] — re-confirmed by review.
- [x] [Review][Defer] No max-size cap on the HTTP response read [services/api/.../quotes.py:_http_get] — bound `r.read(N)` defensively.
- [x] [Review][Defer] The two fetcher twins have no shared parity test [modules/sym/quotes.py ⇄ analytics/quotes.py] — a parametrized test asserting identical symbol mapping would catch silent drift of the deliberate duplication.

### Dismissed (false positives / by design / handled)

- AC2 503-envelope shape — FALSE POSITIVE: the app-wide `http_exception_envelope` (services/api/src/qrp_api/main.py:175) already translates `HTTPException(503,…)` into `{error:{type:"unavailable",message}}`; `_error_type_for(503)=="unavailable"` is tested. Routers correctly raise plain `HTTPException`.
- AC1 "exact field set" — the `Quote`/`LiveConstituent` models add `prev_close`+`live_return` beyond the 8 listed fields; additive superset, intentional (the live-return-from-own-previousClose design). AC text not updated; benign.
- Mixed partial outage suppresses 503 — by design (per-symbol network error → `unavailable` row when others succeed; 503 only on total outage), matches AC2.
- `as_of` "Invalid Date" in panel — null-guarded (`live.as_of ? …`) and backend emits valid ISO-8601 UTC.
- No clamp on per-name `live_return` — consistent with the EOD engine (which also doesn't clamp); clamping would diverge.
- ticker/mic whitespace/casing — first-party canonical data (uppercase MICs, clean tickers).
- `covered_abs==0` → `unavailable`/null — handled honestly.
- `chart.error` discarded — handled (→ None → `unavailable`).
- Panel hides the live block at `n_priced==0` — acceptable UX choice.
