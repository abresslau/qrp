
## Deferred from: code review of portfolios-live-autorefresh-parity (2026-06-29) — RESOLVED same day

- **[RESOLVED 2026-06-29] Non-finite auto-refresh interval drives a zero-delay poll loop — shared across all live boards** (`apps/web/app/monitor/fx/page.tsx`, `apps/web/app/monitor/wei/page.tsx`, `apps/web/components/heatmap-view.tsx`) — the `onChange` handler computed `Math.max(0, Math.floor(Number(e.target.value) || 0))`; an over-large numeric literal (e.g. `1e400`) overflowed to `Infinity`, so `setInterval(…, Math.max(3, Infinity)*1000)` passed a non-finite delay that browsers clamp to 0 → a max-rate fetch loop. The portfolio live cockpit copy was patched during the review; the three sibling boards were swept with the identical `Number.isFinite(v) ? Math.max(0, Math.floor(v)) : 0` guard immediately after (same branch/commit). No remaining occurrences.

## Deferred from: code review of the Monitor arc (2026-06-22)

Adversarial 3-layer review (Blind / Edge / Acceptance) of the 4 Monitor stories (wei-world-equity-indices, wei-backdate-as-of-date, monitor-fx-cross-matrix, portfolios-live-header-pnl-declutter). 4 patches applied (FX `ccys` dedupe, WEI stale-tooltip honesty, canonical `as_of_date` SQL placeholder, live-page test-masking). Deferred:

- **WEI "1D" change can span a multi-day/year gap for a dormant/sparse index** (`services/api/.../sym/gateway.py` `index_board`) — `prev` is the 2nd-newest session ≤ anchor regardless of how far back it is; such a row is also stale-flagged with empty spark/52w. Real indices are daily, so practical risk is nil; gate `prev` to an adjacent session if a sparse index is ever seeded.
- **WEI pre-history as-of date shows the "Seed indices with sym msci-pull" empty state** (`apps/web/app/monitor/wei/page.tsx`) — implies the warehouse is empty when it just has no data on-or-before the picked date. Recoverable via the Latest button; copy-only fix (distinguish "no data at this date" from "warehouse empty").
- **WEI MSCI single-country names resolve region/country → "Global"** (`packages/sym/src/sym/benchmarks/levels.py` `region_for`/`country_for`) — only USA/Europe are special-cased among MSCI names. Latent (only MSCI World Net is seeded); matters only if a single-country MSCI index is added.
- **WEI `d5` uses 7 calendar days** so it drifts from "5 trading sessions" across holiday weeks; **`compareRows` sinks nulls regardless of sort direction** while the active-column arrow flips (cosmetic; null-descending path untested). Both `gateway.py` / `monitor/wei/page.tsx`.
- **FX matrix has no leg-spread guard like `convert.triangulate`'s `WEEKEND_SPAN_DAYS`** (`services/api/.../sym/gateway.py` `fx_matrix`) — when a leg is `is_filled` (carried-forward within the 7-day cap), the cross rate AND the daily `chg` are built from two legs observed on different dates (a stale-vs-stale "daily" move). The cell is flagged stale (●), so the user is warned, but the value is date-mismatched. Apply the triangulate spread guard (or null the rate beyond the weekend span) when picked up.
- **FX persisted `baseCcy` not in the returned currency set → uncontrolled `<select>` + blank selector** (`apps/web/app/monitor/fx/page.tsx`) — `order` is reconciled into `sequence`, but `baseCcy` is not reconciled to a valid default.
- **FX future `as_of_date` blanks the whole matrix server-side** (`services/api/.../sym/gateway.py` `fx_matrix`) — the page bounds the picker with `max=latestDate`, but the raw API is unguarded; every leg goes stale → all-null cells. Clamp to the latest FX date if the API is consumed directly.
- **Live header title block lacks `min-w-0`/`truncate`** (`apps/web/app/portfolios/[id]/live/page.tsx`) — a pathological long unbroken portfolio name can force horizontal header overflow (normal names wrap fine). Truncate the name when picked up.
- **Live `pct(null) → "—"` placeholder path is now uncovered in the strip suite** (`apps/web/__tests__/portfolio-pnl-strip.test.tsx`) — removing the old numeric-returns case dropped the only `—`-rendering assertion; the strip renders with null returns on every pre-comp-load. Add a placeholder assertion.

## Deferred from: code review of 3.2-ext-price-extremes-52w (2026-06-20)

- **Gateway shows a silently-stale 52w window when the latest extremes row is gated** (`packages/analytics/src/analytics/gateway.py`) — `SELECT DISTINCT ON (composite_figi) … WHERE NOT gated ORDER BY as_of_date DESC` returns an *older* non-gated row when today's row is gated (unreviewed flag), with no recency floor or staleness signal in the UI. Deferred (Decision 2): belongs with the surfacing follow-up's range-bar polish, not this calc-layer story. Fix when picked up: bound recency or render "—" on a gated-latest row.
- **Index path has no orphan DELETE for `fact_index_extremes`** (`packages/sym/src/sym/benchmarks/returns.py`) — `recompute_index_returns` is UPSERT-only with no DELETE for either `fact_index_returns` (pre-existing) or the new `fact_index_extremes`. A removed/corrected index level date leaves a stale extreme row. Deferred: fixing it consistently means adding orphan-delete to the index-returns sibling too (broader than this story); index levels are append-mostly so practical risk is low. AC#5 delete-orphan parity is satisfied on the equity path it specifies.
- **Anti-orphan / dirty-set tests are source-string assertions, not behavioral DB tests** (`packages/sym/tests/test_loader.py`) — the new tests grep the loader source for the two-table DELETE loop and the dirty-set WHERE rather than exercising a DB round-trip. Matches the repo's DB-free unit convention (`test_v_prices_adjusted_does_not_join_securities_status`). A behavioral test against a transient DB would be stronger but is out of the DB-free scope.

## Deferred from: code review of the registry refactor (2026-06-17b)

- **No `_cmd_classify` loop-integration test:** the registry units (`run_fill_pass` run/skip/error/empty paths) + the live `sym classify`/`--llm` smoke cover behavior, but nothing tests the CLI's `[run_fill_pass(...) for spec in fill_specs(...)]` loop + the uniform report-printing branches (skipped/error/empty/success, stderr vs stdout) end to end. A full integration test needs a DB or heavy `_cmd_classify` mock; the loop is simple + live-verified, so deferred.
- **No output-equivalence/snapshot regression test:** there is no golden snapshot pinning the per-pass report lines, so a future wording change (like the empty-scope "— not queried" drift this review caught) wouldn't be caught automatically. A snapshot of a representative run's report lines would guard it.

## Deferred from: FMP classification source (2026-06-17)

- **~~AC1 self-registering classifier registry — TRIGGERED (6th source)~~ — ✅ DONE (2026-06-17):**
  built `sym/classification/registry.py` (`FillSpec` + `fill_specs(llm_enabled)` precedence-ordered +
  `run_fill_pass`; per-source `render` closures; import-time order/coverage assertion vs
  `SOURCE_PRECEDENCE`). `_cmd_classify`'s five pass+report blocks collapse to one
  `run_fill_pass`-over-`fill_specs` loop + a uniform report loop; the CLI no longer imports any
  fill-source class (the primary financedatabase stays the explicit anchor). Behavior-preserving
  (byte-identical live output). AC1-as-written is now met for the fill chain. 9 registry tests; 730 green.
- **FMP international symbol format unverified:** `fmp_symbol_for_identity` reuses `YAHOO_SUFFIX`
  (`.L`/`.PA`/…) since no `FMP_API_KEY` was available to probe FMP's exact non-US symbol scheme. US
  (bare ticker, FMP's strongest coverage) is exact; non-US is a best-guess and should be spot-checked
  against the live API once a key exists.

## Deferred from: code review of classification-multisource (2026-06-17)

- **~~AC5 precedence-upgrade-closes-lower not implemented~~ — ✅ DONE (2026-06-17):** built exactly the precedence-aware re-classification path described here. `SOURCE_PRECEDENCE` + `outranks()` + `read_classifiable_identities(conn, source=...)` (unclassified + strictly-lower-held scope) + a precedence-aware `apply_classifications` (supersede close+insert on differing levels; in-place provenance upgrade on same levels; non-outranking different source = no-op; unknown/legacy rows preserved). Cross-run feature — clean no-op on stable data, fires when a higher source's data later covers a lower-held name. 8 unit tests. See `classification-multisource.md` → "AC5 precedence-upgrade built". This also closes AC8's "source upgrade closes+inserts" test gap.
- **~~AC6 cadence / daily-maintenance hook not wired~~ — ✅ DONE (2026-06-17b):** added `classify` to `sym/eod.py` `DAILY_STEPS` (non-critical, after `map`, before `validate`), running the shared `registry.run_classification_chain` (unattended → `llm_enabled=False`). It rides the existing `lineage/schedules.py:sym_eod_daily` schedule (`execution_timezone="America/New_York"` already set), so no new schedule + the timezone rule is satisfied. Verified `sym eod --steps classify` green. See `classification-multisource.md` → "AC6 cadence hook built".
- **Yahoo assetProfile has no circuit-breaker on a 401-storm / total outage:** the source degrades gracefully per-symbol (records `last_errors`, re-establishes the crumb once) but on a sustained Yahoo outage it walks all N residual names at ~1.2s each (throttle + 2 host attempts + re-establish) instead of failing the pass fast after K consecutive errors. Owner-scale residual is small today; add a consecutive-failure short-circuit if the residual grows.
- **SEC `company_tickers.json` "first listing wins" CIK dedup:** `HttpSecClient.company_ciks` keeps the first directory row per ticker (`setdefault`), assuming no duplicate tickers across CIKs — but SEC can carry the same ticker for two CIKs after a ticker reassignment (old delisted filer + new filer), so a stale CIK's SIC could be attributed. Rare + the sector mapping is coarse enough to usually agree; harden with a recency/active-filer preference if it ever misclassifies.

## Deferred from: code review of qh-9-live-heatmap (2026-06-16)

- **Heatmap live fetch has no AbortController** — the per-run `alive` guard prevents the stale-state overwrite (newest-wins holds), so this is an efficiency nicety (cancel the in-flight network on uni/win change), not a correctness gap.
- **`new Date(as_of)` invalid-date guard** on the live badge (backend emits ISO-8601; defensive only).
- **EOD footer momentarily reads "colored by LIVE return"** during a LIVE→EOD toggle (stale `data.window`); cosmetic.
- **`id(rep)` keying** of the symbol map in `live_heatmap` — works (reps held live) but an index/inline key is cleaner.
- **↻ refresh not disabled while loading** — overlapping fetches are state-safe; UX nicety.
- **`lib/api-types.ts` regen for `LiveHeatmap`** — needs the running API; `heatmap-view.tsx` uses local types so nothing consumes it. Pre-deploy step.
- **In-memory TTL cache for live quotes** (QH.2-deferred, re-confirmed) — bounded concurrency + `LIVE_HEATMAP_MAX` suffice at owner scale; add if request volume on repeated symbols grows.
- **SSE/auto-refresh of the live heatmap** — it's pull-mark-discard (not streamed); an auto-ticking heatmap would poll/stream the live endpoint.

## Deferred from: code review of qh-8-console-fetch-hardening (2026-06-16)

Beyond QH.8's ACs or no React-19 impact — candidates for a follow-up console pass:
- **~~Palette reopen-before-run-resolves still navigates~~ — ✅ DONE (2026-06-17, console hardening):** added a `genRef` run-session token bumped on every open; a read-only op captures its session at launch and acts only if `openRef.current && genRef.current === runGen` (a `live()` guard) — so a run resolving after close→reopen is recognized as stale and ignored, leaving the new session untouched. Tested (close+reopen → no navigate).
- **~~`analytics-panel` manual-refresh controller not aborted on unmount~~ — ✅ DONE (2026-06-17, console hardening):** the cleanup now aborts `liveAbort.current` (read in the teardown — refs are stable, no exhaustive-deps issue) instead of a captured mount-time snapshot, so a manual refresh in flight at unmount is cancelled. Tested (manual-refresh signal aborted on unmount).
- **~~`portfolios` retry/create double-fetch race~~ — ✅ DONE (2026-06-17, console hardening):** added a `genRef` generation token to `fetchData` — each call bumps + captures it, and applies its result (success or failure) only if still the latest, so a slow stale load can't clobber a newer one. Tested (slow mount failure resolving after a successful create does not clobber the rows).
- **~~`portfolios` create paths ignore `r.ok` / no try-catch~~ — ✅ DONE (2026-06-17, console hardening):** both creates go through a `postJson` helper that checks `r.ok` and catches network errors, surfacing the reason in a `role="alert"` line and keeping the form populated (no silent clear+reload, no unhandled rejection). Tested.
- **Palette `setOps`/`setAsyncScreens` lack an unmount guard** (React-19 no-op; asymmetric with the benchmarks alive-guard) and the submenu loop has **no in-flight dedupe** (rapid ⌘K toggling fires concurrent `load()` for one key, last-resolver-wins).

## Deferred from: code review of qh-7-console-test-harness (2026-06-16)

Pre-existing component issues surfaced by the QH.7 review (NOT introduced by it — QH.7 only added tests + lint fixes). Candidates for a future console-hardening pass:
- **~~`analytics-panel.loadLive` + benchmarks effects lack an `alive`/pid guard~~ — ✅ DONE:** `loadLive` is newest-wins via an AbortController (aborted-check before setState — the pid-guard equivalent, QH.8) and the benchmarks effect has an `alive` guard (QH.8); the last gap (manual-refresh controller not aborted on unmount) was closed 2026-06-17.
- **`command-palette` `loadedRef` latches on ops-fetch success**, so a FAILED async submenu (macro categories) never retries for the session — asymmetric with the sidebar, which retries on route change.
- **~~`command-palette` op-run resolution has no open/alive guard~~ — ✅ DONE:** the `openRef` close-guard (QH.8) + the run-session token (2026-06-17 console hardening) together make a `/run` resolving after close, or after close→reopen, a no-op.
- **`heatmap` tooltip clamp reads a captured `pos.w`** that goes stale on a window/container resize without an intervening mousemove (cosmetic; replaced a ref-read-during-render that the lint rule forbade).
- **`sidebar` empty-but-successful async submenu is latched** — categories populated later in the same session don't appear without a reload (documented trade-off in the component).
- **`sidebar.loadSub` doesn't catch a SYNCHRONOUS throw from `p.load()`** (only the returned promise's rejection) — theoretical; the sole fetch provider is `async`.
- **`portfolios` mount-fetch `.catch` swallows errors silently** — an empty list is indistinguishable from a load failure; no error surfaced, no retry.

## Deferred from: code review of qh-2-live-quote-source (2026-06-16)

- **Future-dated / clock-skewed quote always reads "live" (Edge, Low):** `classify_freshness` does `age = max(0, int(now - quote_epoch))`, so a `quote_epoch` in the future clamps to age 0 and classifies `live` regardless of how far ahead. Fine for small skew; reject far-future stamps (e.g. `> now + SKEW → delayed`) if bad payloads appear.
- **Yahoo symbol not URL-encoded into the request path (Edge, Low):** `_CHART_URL.format(sym=yahoo_symbol)` interpolates the symbol raw. Ticker is first-party DB data so SSRF/param-injection risk is low, but `urllib.parse.quote(sym, safe='')` would harden the external fetch.
- **Duplicate FIGIs fetch twice + double-count (Edge, Low):** `DbSymGateway.quotes()` doesn't dedupe `figis`, so a repeated FIGI triggers a second network call and inflates the `attempted`/`net_errors` outage tally. Dedupe preserving order (`dict.fromkeys`).
- **No max-size cap on the HTTP response body (Edge, Low):** `_http_get` does `r.read()` unbounded; a pathological response is fully buffered. Cap with `r.read(MAX_BYTES)`.
- **No shared parity test for the two fetcher twins (Edge, Low):** `modules/sym/quotes.py` and `analytics/quotes.py` are intentionally duplicated; a parametrized test asserting identical `yahoo_symbol_for` output across both would catch silent drift.

## Deferred from: Story QH.2 live quote source + live-PnL (2026-06-15)

- **Quote-fetcher duplication across packages:** `qrp_api.modules.sym.quotes` and `analytics.quotes` are near-identical (symbol map + fetch/parse). Deliberate (standalone packages can't share without coupling; the no-sym-imports gate + the project's per-package `db.py` precedent) — extract a shared package only when a THIRD consumer of live quotes appears.
- **In-memory TTL cache not implemented:** the 2026-06-15 decision allows a small process-local TTL cache to rate-limit Yahoo, but the current sequential on-demand fetch is fine at owner-operated scale. Add the cache (never a DB table) if request volume on the same symbols grows.
- **No fan-out / streaming / history:** the chart endpoint is one-symbol-per-call and fetched sequentially; a bounded `ThreadPoolExecutor` would speed large baskets. SSE/streaming live quotes, intraday persistence (a separate timestamped `quote_snapshot` table, never `prices_raw`), a live heatmap, and a multi-provider fallback are all out of scope — separate stories if wanted.
- **Freshness threshold is a flat 120s + no market-calendar awareness:** `marketState` came back null in-env, so "live vs delayed" is purely quote-age. A name quoting during its session but >120s stale reads `delayed` (honest, but conservative for thin names). A session-aware label would need exchange-hours data.
- **`previousClose` is the live-return base, not the sym EOD close:** the live return uses Yahoo's own previous close, which can differ slightly from sym's adjusted close (corporate-action timing, vendor differences). Acceptable for an intraday directional mark; a sym-close-based base would re-introduce the read-surface/price-access question deliberately avoided here.
- **~~Pre-existing analytics-panel `set-state-in-effect` lint error remains~~ — ✅ DONE (QH.7, commit `5f08d24`, 2026-06-16):** the `setLoading(true)`-in-effect error in `analytics-panel` (and the rest of the C.1 baseline) was fixed for real (no suppressions) by the QH.7 pass. See the C.1-ledger entry. Eslint green as of 2026-06-19.

## Deferred from: code review of qh-6-generic-module-framework-palette (2026-06-15)

- **~~Command-palette accessibility pass (Blind+Edge, Med)~~ — ✅ DONE (2026-06-17, console hardening):** added the focus trap (Tab/Shift+Tab cycle within the dialog), focus restoration on close (capture `document.activeElement` on open, restore in the effect cleanup — no longer orphaned to `<body>`), body scroll-lock (`document.body.style.overflow='hidden'` while open, prior value restored on close), and selected-item `scrollIntoView({block:"nearest"})` so ↑/↓ past the `max-h-80` fold keeps the highlight visible (guarded for jsdom). `role="dialog"`/`aria-modal`/`aria-label` were already present. 4 new a11y/session tests; tsc + eslint + `next build` green.
- **Async-provider screens still reload on each palette open until ops succeeds:** the palette's load-on-open is gated by a single `loadedRef` that now latches only after a successful `/api/operate/ops` fetch — so while ops is failing, each reopen re-runs the async submenu providers (e.g. macro categories) too. Harmless (cheap, idempotent) and only in the ops-down case; a per-source loaded sentinel would tidy it.

## Deferred from: Story QH.6 generic module framework + command palette (2026-06-15)

- **Palette entity search (FR-2 "or entity"):** the palette navigates to areas + screens and launches FR-7 ops, but does NOT search entities (securities, universes, series). FR-2's *testable* consequences require only areas + actions, so this is out of the acceptance bar; adding it means live per-module search queries (e.g. `/api/sym/securities?q=`, universes, macro series) federated into the palette result list with debounce. A clean follow-up when entity jump-to is wanted.
- **Write-op actuation inside the palette:** selecting a writer/arg-taking op routes to `/sym/operate` rather than actuating, because the confirm + universe/scope guard UX lives there and must not be duplicated/weakened. If in-palette actuation is ever wanted, it needs the guard affordance (confirm + arg pickers) reproduced in the palette — deliberately not done.
- **Console UI test infrastructure still absent:** QH.6 is the largest frontend-only story to date and there is still no jest/vitest/playwright/testing-library in `apps/web` — verification was `tsc --noEmit` + `eslint` (clean on touched files) + `next build` + manual. The registry state machine (fail-safe retry) and the palette keyboard/filter logic are exactly the kind of logic unit tests would guard. Standing up a console test harness (and backfilling tests for the palette + sidebar registry) is its own decision/story; flagged again here because the surface that would benefit just grew.
- **~~`react-hooks/set-state-in-effect` baseline still RED (pre-existing, untouched)~~ — ✅ DONE (QH.7, commit `5f08d24`, 2026-06-16):** the 12-error baseline in the other console files was cleared with real fixes (no suppressions) by the QH.7 console-test-harness pass. See the C.1-ledger entry below for the detail. Eslint is green as of 2026-06-19.
- **Async-provider screens in the palette load on first open:** a module with a `fetch` submenu provider (macro) only contributes its screens to the palette after the palette has been opened once (lazy load, cached). First-ever open shows macro areas but not yet its category screens until the load resolves (sub-second). Acceptable; a shell-level prefetch of async providers would close the gap if it ever matters.

## Deferred from: code review of qh-4-operate-sse-progress (2026-06-15)

- **Per-tick `_repair_orphans` write + one Starlette threadpool worker per active SSE stream:** the stream calls `gw.list()` every active tick (~1s), which fires an orphan-repair `UPDATE` then a SELECT off the event loop via `run_in_threadpool`. This matches the pre-existing `/jobs` polling (which also repaired per poll) and AC1 mandates reusing `list()` verbatim, so it's not a regression — but with many concurrent consoles it's N×1Hz writes on the ledger and N threadpool workers (default ~40) consumed in bursts, which could contend with other sync routes. Owner-operated → low concurrency today. The hardening if multi-console use ever lands: a read-only stream read path (move orphan-repair out of the per-tick read, e.g. to the executor) + a concurrent-stream cap.
- **Up to ~5s post-disconnect linger:** `job_event_stream` checks `request.is_disconnected()` once at the top of the loop, then sleeps the idle interval (5s). A client that leaves right after the check holds its ledger connection + threadpool slot until the next iteration — at most one idle interval. Acceptable here; the fix (if it matters) is a mid-sleep disconnect re-check or a shorter idle cap.
- **Live console end-to-end verification (Network-tab, real Next proxy) is still the operator step:** the SSE wiring, framing, 503-at-open, disconnect teardown, and headers are all unit-verified, and `StreamingResponse` through Starlette `TestClient` hangs on teardown (infinite generator never receives a disconnect under TestClient), so the live incremental-flush-through-the-proxy check is left to the operator/this code review's manual pass per the story's Verification section.

## Deferred from: Story Q8.5 Kinea/Brazil central-bank macro feeders (2026-06-14)

- **Done in the overnight continuation:** commodities + markets + FX (yfinance), US BLS
  (CPI/unemployment/payrolls), +9 BCB series, +6 World Bank indicators. See the Q8.5 story.
- **Still not wired (reachable):** IPEADATA (OData4 aggregator — but its EMBI+ country-risk
  series `JPM366_EMBI366` ends 2024-07 in-env, so it's STALE on a current board; find a fresh
  code before wiring), full BCB Focus (annual IPCA/Selic by reference-year + Top-5; only the
  smoothed 12m-ahead IPCA is wired), SECEX/MDIC trade balance (the BCB SGS trade codes
  22704/22705 were REJECTED — magnitudes didn't reconcile; use SECEX directly), CAGED formal
  employment, ANBIMA NTN-B real yields, B3 DI curve.
- **IBGE PIM/PMC (industrial production / retail) needs code discovery:** guessed SIDRA tables
  (8888/8880) returned zero rows and the `/agregados` catalog endpoint returned non-JSON; pull
  the right (table, variable, classification) from `servicodados .../metadados` before wiring.
- **US BEA (PCE/GDP) still missing** — needs a (free) BEA API key; FRED stays BLOCKED. BLS
  history is ~3yr only (the keyless v1 ignores the year range; a registered key gives 20yr).
- **BCB SGS code-correctness is by live probe, not a catalog contract:** the 15 wired codes were
  value-checked 2026-06-14, but SGS has no machine-readable units/validity feed — a code that the
  BCB retires or re-bases would silently drift. A periodic `--check` against expected ranges (the
  provision_readonly `--check` ethos) would catch it; not built.
- **Display: realised-vs-expected & forecasts:** the store holds only REALISED data, so the
  sell-side staple of a forecast column / fan chart isn't reproducible yet; a realised-vs-Focus
  overlay (IPCA actual vs BCB:FOCUS_IPCA_12M) is the cheap first step. Featured-chart hover
  tooltips and per-category "top movers" are further polish.
- **Refresh cadence:** ingestion is manual (`python -m macro.ingest` / gateway refresh). A
  Dagster schedule is the productionisation — MUST set `execution_timezone` (never UTC default).
- **`spark`/delta semantics:** deltas are ABSOLUTE (latest − prior), anchored to each series'
  own latest obs date; for a daily series "1m ago" is the nearest obs ≤30d back. This is honest
  but mixes pp (rates) and level (index/price) changes in one column — fine for a directional
  research table, but a unit-aware %-change variant is the refinement if it ever misleads.

## Deferred from: Story QH.3 read-only DB role for sym reads (2026-06-14)

- **Gateway first-party sym "See" module is a full-cred broad reader (post-merge correction, found by live smoke 2026-06-14):** QH.3 initially routed the gateway's `connect()` through `qrp_readonly`, which broke the WHOLE Q2 See surface — `modules/sym/gateway.py` reads sym-INTERNAL relations (`universe`, `prices_raw`, `gics_scd`, `price_gaps`, review/validation logs) that the surface-only role can't serve, so Overview 500'd. The See module is QRP's observability window into sym (read-only **by convention**), NOT a cross-package AR-R3 consumer — same posture as the `lineage` exception above. `services/api/db.py connect()` now uses full creds; the 8 cross-package consumers keep the physical `qrp_readonly` guarantee. **Follow-up:** a broad introspection-scoped read-only role (read-all-sym / write-nothing) would make this serving-path first-party reader physically write-incapable too — a bigger reader than offline lineage, so arguably the more deserving target of a future hardening story than lineage is.

- **`lineage` is a deliberate full-cred exception to the read-only-role discipline (code review 2026-06-14):** `packages/lineage/src/lineage/generate.py` connects to sym (and every package DB) with full `PGUSER` creds — NOT `qrp_readonly` — because it is an offline lineage/introspection generator that reads sym-INTERNAL relations and introspects `pg_catalog` across all DBs (`_combined_schema`/`_fk_referential`), which the surface-only, sym-only role cannot serve. It only ever SELECTs (read-only by convention) and the topology gate excludes it from `CONSUMER_PACKAGES`. To make lineage's sym reads physical-read-only too would need a *broader* introspection-scoped read-only role spanning all DBs + catalog access — a separate hardening story if wanted. Documented in `generate.py`; the QH.3 guarantee covers the **serving-path** consumers (gateway + the 8 packages), not this offline tool.
- **Per-target read-only role generalisation:** only **sym** reads are hardened to `qrp_readonly` now. Cross-module reads beyond sym — signals→macro (`fiscal_sens`) and signals→altdata (`wiki_attention`), both AR-R2 read-only-by-design — still use **full creds**. The clean generalisation is a read-only role (or a grant on the existing one) per cross-read target DB, routed by the same `connect(dbname != _OWN)` seam; premature today (only sym is read by more than its own writer). The `connect()` guard is deliberately sym-specific (`dbname == "sym"`), not `dbname != _OWN`, to avoid breaking those full-cred cross-module reads until their roles exist.
- **DuckDB serving path is still the federation successor:** QH.3 hardens the **app-side psycopg** reads (the current implementation); the `ATTACH READ_ONLY` federation path (QH.5 spike) remains the future story for cross-DB SQL. The two read-only guarantees are complementary, not redundant.
- **`SYM_READ_SURFACE` is now load-bearing for grants, not just the gate:** adding a relation to `qrp_api.sym_contract.SYM_READ_SURFACE` widens BOTH the discipline gate AND the role's physical grants on the next `provision_readonly` run. A consumer that reads a newly-surfaced relation must re-run the provisioner (or `deploy_all`) or it gets permission-denied — the honest failure, not a silent read. Noted in the contract module.
- **Provisioner reads the live relation set:** `GRANT SELECT` is applied only to surface relations that exist in the sym DB; any absent one is **named** in the output, never silently dropped (a fresh/partial sym would under-grant loudly).

## Deferred from: Story QH.5 migration finish-off (2026-06-11)

- **DuckDB serving-path adoption** is its own future story: the live-attach spike PASSED in-env (extension installs; native cross-DB joins correct; writes physically refused — `tools/duckdb_spike.py`, re-runnable), so the federation option is proven real; app-side psycopg assembly remains the implementation until a surface actually needs cross-DB SQL.
- **The root `db/` legacy project** (pre-split `qrp` monolith, project name `qrp`): DEPLOYED history in the sym database's sqitch registry, net-nil schema effect (create→relocate→drop). Deliberately unregistered in `tools/deploy_all.py`. Decision pending: delete the directory (losing the ability to re-verify that historical deploy) or keep as archaeology — either is fine; pick when it next annoys.
- **Verify scripts assert END-state shapes** (the Q8.3/Q5.2/QH.5 convention — QH.5's deploy-all first run caught 12 rotten ones): per-change verification (`sqitch deploy --verify`, `rebase`, `checkout`) on a fresh DB would fail mid-plan where later renames apply. `deploy_all.py`'s deploy-then-verify is end-state-consistent. A per-change-correct rebuild of every verify is unjustified until someone needs mid-plan verification.
- **Topology-gate honest limits** (stated in its docstring): regex not SQL-parser (dynamic composition evades — none exists); lowercase UNKNOWN-relation reads evade the vocabulary guard (known names are caught case-insensitively); file-scoped CTE exclusion; a consumer's own table named like a sym-internal relation would false-positive (no instance exists).

## Deferred from: Story Q7.3+Q7.4+Q9.4(optimiser) loop close (2026-06-11)

- **Sector caps + turnover constraints** (the FR-22 examples beyond the max-position archetype): sector needs a GICS-joined projection; turnover needs a prior-solution reference. The capped-simplex machinery is the extension point.
- **PIT universe selection for holdout solves:** `_select_names` uses current membership + latest mcap — a selection look-ahead into the holdout (stated as a served `selection_caveat` on every holdout block). The fix = `_select_names(as_of=train_end)` + a PIT mcap query.
- **max_sharpe λ-path winner is picked by realised Sharpe only** (tilt shapes each candidate but not the pick — documented in the engine docstring); a tilt-aware selection criterion is a design choice.
- **Saved-portfolio `base_currency` hardcoded USD** — the optimiser writer now shares the Q6.4/Q6.3 pattern; one fix covers all three call sites (derive from the universe's quote currency).

## Deferred from: Story Q6.3+Q9.4(backtest) strategy spec (2026-06-11)

- **Buy-and-hold drift variant:** the engine models holdings as DAILY-REBALANCED to target weights between rebalances (the original EW engine's semantics, now stated honestly in the docstring); a drifting buy-and-hold variant is a design option if turnover realism ever matters.
- **Saved paper portfolios hardcode `base_currency="USD"`** (pre-existing Q6.4 behavior) — wrong label for BRL-universe runs; harmless while notional stays unset.
- **Size-definition drift recorded:** signals' `_raw_size` filters `market_cap_usd > 0`, the deleted engine SQL didn't — 0 of 713,592 live rows affected; signals' definition kept (the better one).
- **Engine validation vocabulary split:** the run endpoint 422s on caller-shape errors (XOR, unknown factor, unsupported module) but returns 200 `ok:false` for engine refusals (coverage gate, unknown weighting) — the established envelope; revisit only if automation needs a single contract.
- **Q9.4 optimiser half** — signals as optimiser tilts → Q7.3/Q7.4 (next loop link).

## Deferred from: Story Q9.2 cross-module signals (2026-06-11)

- **B3-universe scoring is date-starved:** ibov/ibx membership is build-forward from 2026-06-08 but `fact_returns` max is 2026-06-05, so the PIT roster at the global default as-of is honestly EMPTY (all factors, pre-existing — the `_members` comment says so). A per-universe as-of (max member-return date ≥ the universe's first valid_from) in the `__main__` runner would let B3 universes score as soon as BVMF prices catch up; needs the next EOD run to matter.
- **`fiscal_sens` winsorisation ties at the caps:** the p1/p99 clip puts the extreme tail on a shared value (rank 1-3 all −3.54 live) — correct per the documented winsorisation, but rank within the tied cap group is arbitrary. A tie-aware rank (dense/average) is a design choice if tail ordering ever matters.
- **`signals.factors()` count fix rode along:** `count(*)` → `count(s.factor_key)` (a scoreless catalog row was counting 1 via the LEFT JOIN) — necessary for the new factors which exist before their first scores.
- **(review) Lineage `signals.score` deps are sym-only** — no altdata/macro edges despite the cross-module factors; extends the Q8.3 lineage-remap item (altdata's lineage assets are stale wholesale): one remap pass covers both.
- **(review) `fiscal_sens` estimation-noise choices:** per-name betas over different matched windows (only ≥60 days enforced — no common-date intersection) and multi-day debt deltas at calendar gaps matched to 1-day returns; tighten if the factor's precision ever matters.
- **(review) Skip attribution covers connections, not sources:** a reachable macro DB with an empty/missing UST:DEBT series reads as `scored: 0`, indistinguishable from gates-unmet; a source-presence pre-check is the fix when wanted.
- **(review) Stale B3 sym-factor scores from the pre-rebuild roster** are still stored/served (`_store` upserts, never retracts) — universes count 3 on the strength of rows whose roster is no longer PIT-valid; pairs with the date-starvation item above.

## Deferred from: Story Q5.2+Q4.5 TWR & weight history (2026-06-11)

- **Console notional affordance missing:** the analytics panel shows "no notional set" but no console form (create or detail) exposes the field — setting it requires an API PATCH. A small detail-page editor is the fix when wanted.
- **Analytics `as_of_date` response field semantics shifted** (now "newest stored vector's date"; the series blends the full history) — documented in the model comment; a rename (`latest_vector_date`) would be the clean fix but breaks the TS contract for cosmetics. Revisit if the field misleads.
- **Snapshot-attribution view still serves sym window returns against latest weights** (`portfolios.returns`, now honestly labelled `semantics: "snapshot_attribution"`) — a full attribution-over-history view (per-era contributions) would be the analytics-side successor if attribution ever needs to be time-faithful too.

## Deferred from: Story QH.1 Brazil GICS gap (2026-06-11)

- **~~Non-Brazil GICS gaps remain (134 FAIL rows)~~ — ✅ CLOSED (2026-06-22, `non-brazil-gics-surgical-close`):** the SIC→GICS source (`sec_sic`, 2026-06-17) + `yahoo_profile` + `wikidata` took global coverage to 99.1%, reducing the live-universe-member residual from 134 to **4 names**. Those 4 were then surgically closed: **FB** was a spurious ProShares-ETF member of sp500 (recycled "FB" ticker, PCLN-class) → `reverse_change`d out (502→501, META retained); **SMT/PCT/ALW** are FTSE-100 investment trusts (ICB/GICS Financials) that no automated source can reach in-env (yahoo `*.L` → 404, wikidata no-match) → closed via a new high-trust **`manual`** operator-asserted classification source (rank 1, fill-only, sector-only). Coverage 99.1→99.3%; ftse100+sp500 `universe_member_completeness` PASS; live-member unclassified residual = **0**. The remaining 15 unclassified actives are delisted legacy tickers in NO current universe (survivorship retention, not a gap).
- **B3 mapping is index-portfolio-scoped:** the source classifies only current IBOV/IBXX constituents — a BVMF name that leaves both indexes but stays active keeps its (stale-but-SCD-dated) classification; a newly-added constituent gets classified on the next `sym classify`. The B3 `CompanyCall` per-company endpoints would decouple classification from index membership if that ever matters.
- **B3 segment strings are abbreviated and could drift:** an unmapped new abbreviation surfaces loudly in the `sym classify` output (`unmapped B3 segment: ...`) — post-review this fires for EVERY constituent, classified or not — and the name stays unclassified until the mapping table gains the entry. The mapping needs an occasional glance after B3 rebalances (Jan/May/Sep).
- **`max(symbol_value)` ticker pick is alphabetically arbitrary** when a security carries multiple currently-effective ticker rows (multi-listing) — pre-existing Story-1.8 pattern in `read_active_identities`, shared by `read_unclassified_identities`; needs a listing-preference design if multi-listed names ever appear (pairs with the dual-listing representation item from 1.10's review).
- **Fill-pass failure never moves `sym classify`'s exit code** (fd-gate-only is deliberate — Constraint 3); automation that needs to distinguish a B3 outage from a clean fill needs a deliberate exit-code design (e.g. a distinct code for fill-pass failure).

## Deferred from: code review of Q8-3-broaden-altdata-sources (2026-06-11)

- **Lineage catalog still models the dropped `wiki_map`/`pageview`** (assets.py, generate.py recipe outputs, derived_lineage.py, field-flow.md) and not `altdata.series`/`observation` — needs its own remap pass. The QL-3 bare-name keyspace collision is now REAL: `altdata.series`/`observation` collide with `macro.series`/`observation` under the name-keyed lineage index — fix = key by (db, table) FIRST, then remap altdata's assets.
- **Console fetches don't check `r.ok`** (pre-existing A.1-found pattern, all pages) — Q8.3 adds live triggers on /altdata: a 404 if the sweep deletes a series between list-load and click, a 422 if params are dropped; the error envelope then crashes the detail render. A console-wide fetch-wrapper pass is the fix, not a per-page patch.
- **Concurrent altdata ingest runs can race the end-of-run sweep:** with autocommit, run A's `DELETE … NOT EXISTS(observation)` can remove run B's just-committed series row before B's first observation lands → FK violation aborts B mid-run. No concurrent runner exists today (manual CLI only); same pattern exists in macro. Revisit when any scheduler touches these ingests.
- **Sparkline is index-spaced** — for sparse filing series the chart implies continuity through unstored true-zero gaps (two filings months apart look adjacent); needs a time-scaled x-axis for the count archetype.
- **Window-anchor source list is SQL-literal:** the true-zero vs lag-shaped anchor split keys on `source = 'sec_edgar'` in the gateway SQL; a third source must extend the CASE (or promote the missing-day semantics to a `series` column — the cleaner fix when it happens).

## Deferred from: Story Q8.3 broaden alt-data sources (2026-06-11)

- **SIC codes ride along free in SEC submissions:** every submissions JSON carries `sic`/`sicDescription` — a candidate classification source for US-listed ADRs of Brazilian names (QH.1's IBOV GICS gap; PBR/VALE/etc. have ADR CIKs). Probe-verified contract in the Q8.3 story file.
- **EDGAR archive files for depth:** `filings.files[]` serves pre-`recent` history (AAPL: 1994→2015, verified 200) as flat dicts of the same parallel arrays (no `filings.recent` wrapper). A backfill story can extend filing-count depth without schema change.
- **Third source archetype unprobed:** job-board (Greenhouse/Lever), GitHub-activity and social endpoints were NOT reachability-probed (env policy denied the probe this session); GDELT/IMF/FRED remain blocked per Q8.4 probes. Re-probe before scoping any third archetype.
- **Revert drops non-wikipedia data by design:** `generic_series`'s revert script restores the wiki-shaped tables and discards EDGAR (and any future-source) series — stated in the script; re-deploy + re-ingest recovers them from source.
- **Amendments excluded from filing counts:** `4/A` / `8-K/A` are deliberately not counted (exact form match). If amendment-intensity ever matters it's a new metric (e.g. `filings_form4a`), not a change to the existing ones.

## Deferred from: code review of orchestration + lineage, chunk 5 of project-wide review (2026-06-10)

- Backup verification + rotation: no `pg_restore --list` sanity, no dump-size floor, no retention policy. (Partial-dump cleanup, numeric pg_dump version sort, and PGPASSWORD-via-env were fixed in-review.)
- `fact_index_returns` backup-exclusion review: recomputable like `fact_returns` but deliberately kept in the dump (small/conservative) — revisit if dump size matters.
- ~~QL-1 story-status housekeeping: still "in-progress" with delivered AC task boxes unchecked.~~ ✅ DONE (2026-06-22): AC10 delivered by QL-2, AC12/AC13 by QL-3; verified (code + 22 lineage tests) and QL-1 closed → done.
- Schedule evaluation knobs: the `sym_eod` op derives as_of_date from the scheduled tick now; finer control (skip-holidays, catch-up policy for missed ticks) undesigned.
- Yahoo symbol normalization asymmetry (carried from chunk 4's ledger; surfaced again here via the resolver): HK zero re-padding + indiscriminate '.'->'-'.

## Deferred from: code review of sym identity & integrity, chunk 4 of project-wide review (2026-06-10)

Backlogged by decision (D1/D2, accepted recommendations):

- **D1 — review-queue gating story — ✅ DONE (Story 1.9, 2026-06-10):** the queue gates `resolve_universe` (a seed any of whose input keys has an OPEN row is skipped — no OpenFIGI query, no assignment, counted on `skipped_queued`); `sym review list` / `sym review resolve <id> [--figi ...]` give the steward the close path (assignment via `write_security`; dismissal re-admits the input, the freed key re-queues a recurrence). Live: the 5 real queued names (TWTR/ATVI/LEHMQ/ENE/CSGN) now skip every run. Story 1.4 AC2/AC3 hold.
- **D2 — symbology SCD transition story — ✅ DONE (Story 1.10, 2026-06-10):** `write_security` now reconciles per identifier type — a rename CLOSES the old row at the new `valid_from` (same-day changes update in place per the SCD rule; collisions still refuse first); the §4 SQ→XYZ worked example is implemented behavior; the dropped V3 AC is restored as the `symbology_transitions` check (FAIL duplicate-open, WARN closed-without-successor). NEW scope-out recorded: a relisting transitions the ticker row but `securities.mic`/`currency_code` stay stale (price-currency cascade — needs its own design).

Deferred findings:

- V1 stricter coverage-over-membership-window clause (prices dimension is one-bar-ever).
- V2 unresolved-member "info" tier (no info tier exists in results.py).
- V6 per-universe readiness threshold (one global default, not CLI-exposed).
- EODHD second vendor (Story 2.7) — comparator ready, adapter never built; docstring made honest.
- GICS 4-level codes (labels-only at top-3, per recorded reconciliation).
- Epic-doc wording reconciliation: V4 off-calendar warn-downgrade and V5 pit-direction are deliberate per story changelogs but epics-validation.md still reads as the original.
- Calendar narrower-replacement guard: a re-snapshot covering a strictly narrower span can still demote a richer current version (the 20-yr-default fallback route is now closed; caller-window variation remains).
- Empty-frame vs unknown-symbol distinction in the yfinance adapter (Yahoo returns empty for both).
- Yahoo symbol normalization asymmetry: OpenFIGI strips HK leading zeros; the Yahoo resolver never re-pads (0700.HK) and applies '.'->'-' to all markets.
- `universe_member_completeness` historical rows for departed members are now purged at evaluate-time; a retention/audit copy (if wanted) needs a design.

Backlogged by decision (D1-D4, accepted recommendations):

- **D1 — U3-wire story — ✅ DONE (Story U3.5, 2026-06-10):** `run_monitor` derives leaves from source-declared snapshots (`last_snapshot_tokens` + `diff_identifier_sets`), routes ALL discoveries through `stage_and_promote` (`MONITOR_GATED` live), rebuild-after-append on confirm/reverse/promote, `sym universe accuracy` (with FIGI-level cross-scheme fallback — also closes the "FIGI-level accuracy comparison" deferred finding below) and `sym universe reverse` CLIs added. No accuracy schedule by design (monitor cadence + CLI suffice; a Dagster hook would need explicit `execution_timezone`). See `U3-5-wire-safety-machinery.md`.
- **D2 — snapshot-pin resolution watermark — ✅ DONE (Story U1.7, 2026-06-10):** a pin is now `(universe, as_of_date, log_version, resolved_through)`; the pinned query filters the resolution join by `resolved_at <= resolved_through` and the unresolved→resolved upgrade re-stamps `resolved_at` (without which the watermark was silently defeated). NO schema change was needed — `resolved_at` already existed; the ledger's "needs schema" premise was stale. `current_resolution_version` captures the watermark; `resolved_through=None` keeps legacy events-only pins readable. Caveat retired from `snapshot.py`.
- **D3 — provenance-aware `correct` events — ✅ DONE (Story U3.7, 2026-06-10):** correctives now TOMBSTONE exactly the event named by `provenance.reverses` + effective date (pure `pair_corrections` pre-pass in the projector); intervening events can no longer invert intent; the monitor's `_open_tokens` replays the SAME machine so the log-derived open set and the projection agree after a reversal (the U3.5 live asymmetry is gone). Legacy provenance-less correctives keep toggle behavior, counted on `ProjectionSummary`. Dedupe-key same-date limitation documented in `docs/data-conventions.md` §5, not solved (schema untouched by design).
- **D4 — maintenance plans — ✅ DONE (Story U3.6, 2026-06-10):** all 13 populated index universes documented in `docs/universe-maintenance.md` (incl. restating the stale "ibx not populated" section — it had 99 members and had NEVER been monitored); `config.calendar_mic` set on all 13 (session-snapping/alignment now live); ibx first monitor run recorded; rule enforced by the new `maintenance_plan_coverage` validate check (populated universe without a plan section FAILS). Remaining follow-up: wiring a reachable independent `accuracy_reference` per wikipedia-sourced universe (none configurable in this environment today).

Deferred findings:

- FIGI-level accuracy comparison: ✅ DONE in Story U3.5 — `run_configured_accuracy_check` resolves both sides to FIGIs when token schemes differ.
- Wikipedia revision-diff client (U2.3 AC2's "revision history" path): `revision_diff` is pure + tested but nothing fetches revisions.
- Monitor coverage for non-index kinds: `stale_monitors` defaults to `kinds=("index",)` — criteria universes can silently freeze out of the digest.
- ETF proxy provenance tagging (U2.2 AC3): `PROXY` marker is dead; events carry no proxy provenance jsonb.
- Criteria-universe evolution semantics: re-evaluation appends joins only — an evolving screen accumulates the union of snapshots (pairs with D1's leaver diff).
- FMP partial-fetch verification: no expected-vs-returned count check exists (docstring now says so honestly); a throttled partial list passes silently.

- Multi-flag review schema — ✅ DONE (Story S.1, 2026-06-10): `prices_review` PK is now `(figi, session_date, flag_type)` — audit and ingest flags coexist; neither writer overwrites `flag_type` on conflict; `pct_move`'s type-scoped semantics recorded in the column COMMENT; `resolve_review` can target one flag type; the returns gate reads DISTINCT dates.
- Run-log row written up-front (`status='running'`, finalized on completion) so a process death mid-run leaves a visible record instead of silently missing FR-8 history. Pairs with the Operate heartbeat backlog item.
- Persistent FX-rejection table — ✅ DONE (Story S.1, 2026-06-10): `fx_rate_review` (one OPEN row per (quote, date, source); re-runs refresh); `load_fx` persists both rejection kinds; `sym fx review` lists/accepts/rejects — ACCEPT inserts the rate into `fx_rate` (immutable discipline; typed refusal when the currency isn't in the reference table) which un-wedges the band on the next load; `fx_coverage` WARNs on open rejections. Live round-trip verified.
- `convert()` returns bare `None` — the legs' rich `FxResolution` status (stale vs no-data vs leg-spread) is discarded. Surface a reason (FX3b AC3's "+ flag").
- `sym audit` covers active securities only — a vendor's retroactive correction inside a recently-delisted name's trailing window is never detected.
- Data-level survivorship test (Story 3.7 AC3): compute returns for a known delisted figi through its delist date (needs DB-backed test infra; current guards are static source scans).
- Currency-redenomination history: `fx/restate.py` applies the security's CURRENT currency across all history (wrong across e.g. pre-euro changeovers). Needs an SCD currency table that doesn't exist yet.
- Read-side dirty-set for returns recompute (Story 3.6 efficiency intent): loader recomputes everything in range and skips only at the upsert.
- PR-vs-TR benchmark mixing: the `dax` link makes a TR index primary against PR member returns (amended B3 accepted variant-free storage; alpha consumers should get a variant-awareness pass under the index-maintenance plan).
- MSCI date-format ambiguity: `_DATE_FORMATS` tries day-first then month-first — `03/04/2025` parses day-first silently. Operator-controlled import; document the expected format or add a column/format hint.

## Deferred from: code review of QRP module layer, chunk 1 of project-wide review (2026-06-10)

Roadmap-depth FR gaps (spec'd, built to demo depth in the 2026-06-08 v1) + refactors that fold into the decided qrp/packages restructure:

- FR-15: ~~portfolio returns are a latest-weights × latest-returns dot product — not time-weighted, no PnL (money), weights history never consumed time-series-wise~~ **✅ RESOLVED by Story Q5.2+Q4.5 (2026-06-11):** analytics applies the then-effective vector per date (step function over the new `read_weight_history` seam); `returns` block = cumulative TWR + PnL (= optional notional × TWR); `portfolios.returns` kept as an honestly-labelled snapshot-attribution view (`semantics` field).
- FR-20: macro observations carry `source` but no release/vintage date — restatements indistinguishable [macro/ingest.py:38-55]. **✅ FOLDED into Story Q8.4 (2026-06-11):** `observation.last_changed_at` re-stamped only on value change + per-series `restated` count in the ingest summary. A full point-in-time vintage/revision table stays DEFERRED (no consumer needs pit macro yet; the column COMMENT says it is not a release date).
- FR-22: optimiser takes no constraints input (hardcoded long-only sum=1), never consumes `signals.score`, and has no save-solution-as-Portfolio path [optimiser/engine.py:101-111, router.py:50-55].
- FR-17: analytics benchmark picker lists only `instrument.kind='index'` — a sym Universe cannot be the benchmark [analytics/gateway.py:68-83].
- Gateway encapsulation: backtest router reaches into `gw._sym`; several gateways type `sym_conn: ... | None` then dereference unconditionally [backtest/router.py:89; analytics/gateway.py:70]. Fold into the qrp structure-target refactor.
- DRY: eight byte-identical `db.py` helpers (already drifted once — see analytics `_OWN` bug); fold into the decided qrp/packages restructure rather than patching eight copies.

Backlogged by decision (review 2026-06-10, D2/D4/D6/D7 accepted recommendations):

- **Operate architecture story (D2) — ✅ DONE (Story O.2, 2026-06-10):** ADR-1 FINALIZED (subprocess arm chosen for op execution; library-first scoped to data-access gateways — no reversal, the two are different layers); ADR-2 deviation recorded (lock per op+args, deliberately finer). `qrp.job.heartbeat_at` + Popen/poll/beat supervisor; stale beat → read-time `orphaned` (no reaper — advisory locks die with the connection); busy-check unwedges in 30s for dead running rows. `pipeline_run_log.triggered_by` (sym sqitch) stamped from `SYM_TRIGGERED_BY=qrp-job:<id>`; `GET /api/operate/history` (FR-6) serves the correlated run log. Allowlist 4 → 9 ops (eod, fx_load, load_fill w/ scope validation, universe_review, universe_accuracy). Live-verified end-to-end: job 4 → sym run 35 `triggered_by=qrp-job:4`.
- **API hardening (D4) — guard half ✅ DONE (Story O.3, 2026-06-10):** app-wide actuation origin guard in `qrp_api.main` — mutating methods with a FOREIGN Origin are 403'd before route logic; headless (no-Origin) clients pass; one shared origin list with the CORS config. Live-verified (forged 403 / console passes / curl passes / reads unaffected). **Engine relocation RE-DEFERRED with its dependency named:** moving backtest/run + optimiser/solve into Operate-style jobs changes the API contract (sync result → job_id + polling), requiring console (Next.js) changes — pair with the qrp/packages restructure; the O.2 executor is the hardened home waiting for it.
- **Error envelope rollout (D6) — ✅ DONE (Story O.4, 2026-06-10):** global exception handlers in `qrp_api.main` translate EVERY error path (router HTTPExceptions, framework 422s, the origin-guard 403 via the shared helper, unhandled 500s with class-name-only messages) into the spec'd `{error:{type,message,detail?}}` envelope; top-level `detail` mirror kept during the console migration; the one console consumer prefers `error.message`. Status-vocabulary deviation recorded (freshness's honest 3-state `unknown`).
- **analytics boundaries (D7) — parts 1-2 ✅ DONE (Story A.1, 2026-06-10):** analytics remounted under its OWN prefix (`/api/analytics/benchmarks` + `/api/analytics/portfolios/{pid}`; the `/api/portfolios/{pid}/analytics` squat is gone — route-table-tested); weights read through the owning package's new seam `portfolios.gateway.read_latest_weights` (zero `portfolio_weight` SQL left in analytics — grep-asserted); console panel + generated TS types updated. **Part 3 (effective-dated weighting): ✅ LANDED with FR-15 in Story Q5.2+Q4.5 (2026-06-11)** — they landed together as recorded.

## Deferred from: code review of 3.1-ext-return-window-expansion (2026-06-07)

- `base_date` assumes `asof` is a member of the calendar `sessions` list. Off-calendar price dates (known pre-1990 / vendor-phantom bars, already WARN-classified and inert to returns) make the SESSION-count and snap logic count from the insertion point — slightly off but harmless. Optional hardening: snap `asof` via `_last_on_or_before` before counting. Pre-existing (all base-date snapping shares this assumption).
- No test asserts the migration-seeded `return_window.kind` matches the `windows.py` spec. Low impact: `kind` is non-functional metadata (the engine computes from `windows.py` constants, never the DB column), so drift would be cosmetic. Could add a live consistency check.
- Migration revert scripts hardcode code-lists (`trailing_kind_prior_quarter`) and use `BETWEEN 21 AND 27` range deletes (`cumulative_multiyear_windows`) instead of structural inverses. Correct for the current window set; fragile if new windows are inserted in those id ranges later.
- Equity loader has no test for the since-inception day-one semantics (`SI`=0, `SI_ANN`=None on a single-session history); only the index side (`test_benchmark_returns`) covers it.
- No PQ (`period` kind) test against a sparse or real exchange calendar — current tests use dense weekday fixtures only.

## Deferred from: code review of QL-1-lineage-dagster-foundation (2026-06-09)

All deferred to the AC10 auto-feeder rollout (derive.py / sql_capture.py are a proven prototype; hardening belongs to productionization):

- derive_edges run-correlation is cartesian with no per-run or statement-order scoping → fabricates edges (every read→every VALUES write), incl. empty-key edges to metadata targets (solution/run/point) [derive.py:116-124].
- Multi-connection captures never combine: loaders read via one conn and write via another (e.g. optimiser sym_conn/opt_conn), each `CapturingConnection` has its own `.captured` → no cross-DB edge unless the lists are merged per run [sql_capture.py].
- CTE aliases counted as source tables via `find_all(exp.Table)` (`shares`,`px`,`latest`) → phantom upstream assets [derive.py:82].
- `pg_schema` output never passed as `schema=` to sqlglot → `SELECT *` / unqualified-join key tracing silently dropped (advertised capability unreachable) [derive.py:53].
- `%s`→`NULL` blind replace corrupts string literals containing `%s` and named `%(name)s` placeholders [derive.py:45-47].
- UPDATE/DELETE/MERGE not classified as writes; CTAS (`CREATE TABLE AS SELECT`) misclassified as a pure read [derive.py:59-85].
- `to_dagster_metadata` matches target by bare table name → collisions for generic names (run/weight/score/point) across packages [derive.py:141].
- Edge dedup key omits `keys` → non-deterministic key list when a table-pair recurs [derive.py:127-131].
- INSERT…SELECT computed-key passthrough dropped when the key isn't a literal source column [derive.py:110].
- sql_capture runtime semantics: statements from rolled-back txns retained; non-`autocommit` attribute sets land on the wrapper not the real conn; `row_factory`/`cursor_factory`/named cursors/COPY un-proxied; empty `executemany` records a phantom write [sql_capture.py].
- `pg_schema` collapses same table name across schemas — matters under the planned DuckDB federation [derive.py:39-41].

## Deferred from: code review of QL-2-auto-feeder-rollout (2026-06-09)

Low-reachability for current loaders (single-statement, no MERGE/CTAS/VIEW/string-placeholders) or future-topology — revisit in QL-3:

- CTAS branch also matches `CREATE VIEW … AS SELECT`; INSERT/CTAS where `tree.this` isn't a Schema/Table yields `target=None` → edge silently lost [derive.py:98-103].
- MERGE / `DELETE…USING` / `UPDATE…FROM` target extraction via `tree.find(exp.Table)` is AST-order-dependent — target/source could swap, inverting an edge [derive.py:105-107].
- `sqlglot.parse_one` keeps only the first statement of a semicolon-joined batch [derive.py:72].
- `_norm` rewrites `%%`/`%(name)s` even inside string literals (docstring "neutralize without corrupting" is overstated) [derive.py:50-55].
- `UPDATE…FROM` source tables are not seeded into `reads_before`, unlike INSERT…SELECT sources [derive.py:161-164].
- `_combined_schema` should key by (db, table) to remove the latent cross-DB same-name collapse (harmless today; matters under DuckDB federation) [generate.py:85-94].

## Deferred from: code review of QL-3-fk-referential-and-visual (2026-06-09)

- The whole lineage keyspace is **bare table name** (no DB qualification) — `_NAME_INDEX`, `FK_REFERENTIAL`, `edges()`, `key_tables` all collapse same-named tables across DBs. Harmless today (30 modeled names unique); a future cross-DB collision misattributes edges. Fix = key by (db, table). Pairs with the QL-2 `_combined_schema` deferral → DuckDB-federation era.
- `lineage/diagram.py` computes the output path via `Path(__file__).parents[2]`, assuming the `src/` layout — would write to the wrong place if the package is installed as a wheel.
- `analytics/metrics` (computed, schema-less) never appears in the Mermaid field-flow even though it has `composite_figi`-bearing deps — documented in the diagram caption; revisit if a computed-node view is wanted.
- `operate/job` asset carries `database="qrp"` but sits in group `operate` — cosmetic db-label mismatch; fold into the de-hub effort (#14).

## Deferred from: code review of B7-identity-key-bridge (2026-06-09)

- Add the cross-key bridge edge (securities.composite_figi → instrument_xref → instrument.sym_id) to the lineage DAG — the `instrument` asset only declares `securities` as a dep; the per-figi xref bridge is undocumented in the graph [lineage/assets.py].
- No warn/exempt tier for delisted/suspended securities in `equity_instrument_bridge` — any unmapped security is a hard FAIL with no graceful tier (other checks downgrade expected gaps to WARN). Steady-state consistent today (backfill maps all statuses); a single legacy unmapped delisted name would pin `sym validate` red [validate/instrument_bridge.py].
- CHAR(12)↔TEXT anti-join (`x.value = s.composite_figi`) is correct only because the figi `^[A-Z0-9]{12}$` CHECK forbids padding; no defensive `rtrim`/cast, and the dependency isn't noted. Latent false-negative/positive surface if the FIGI format is ever relaxed [validate/instrument_bridge.py:24].

## Deferred from: code review of 2-10-explicit-range-reload (2026-06-09)

- `reload_start`/`start` is not snapped to a trading session while `end` is (via `latest_session_for`). Benign today — `DELETE … BETWEEN` over non-session days removes nothing, and `expected_trading_days` only counts real sessions — but the asymmetry is a latent inconsistency. Optional: snap `reload_start` to the first session ≥ it [pipeline.py compute_window RELOAD branch].

## Deferred from: code review of U3-5-wire-safety-machinery round 2 (2026-06-10)

- Gated-streak alert: a universe whose monitor is churn-gated every run for weeks reads as ALIVE (liveness counts gated runs — correct) while its membership is silently frozen pending review; the only surface is the review digest's pending pane. A "gated N consecutive runs" alarm in `stale_monitors`/digest is a design follow-up.

## Deferred from: code review of U3-6-maintenance-plans (2026-06-10)

- Wikipedia membership completeness for ftse100 (92 of ~100), smi (19 of 20), estoxx50 (49 of 50): the plans note the shortfalls but no remediation exists — investigate whether the pages are genuinely short, the parser drops rows, or the indexes' real counts differ; until then the completeness check is the watchdog.

## Deferred from: code review of U3-7-provenance-aware-correct (2026-06-10)

- Exact-date re-assertion dead-end: after reversing an EXACT-dated event, the change cannot be re-asserted at its true date (the surviving original row blocks the dedupe key); the documented operator path (adjacent date) is a knowing misstatement for exact events. Proper fix = a dedupe-key nonce/sequence column on membership_event (schema change).

## Deferred from: code review of U1-7-resolution-watermark (2026-06-10)

- Sequence-based resolution watermark: the timestamp watermark's races (now() is transaction-START time so an in-flight resolution run committing after capture carries a pre-capture stamp; equal-timestamp boundary at the watermark; DB clock monotonicity) are documented capture-discipline preconditions, not enforced guarantees. If pins become load-bearing for backtests, replace with a monotonic bigint resolution-version column (the event-side event_id pattern) — schema change.

## Deferred from: stewarding the review queue (2026-06-10)

- Local-first resolution: a seed whose ticker+MIC already maps in `security_symbology` (e.g. steward-assigned via `sym review resolve --figi`) should count as assigned WITHOUT an OpenFIGI query — today the next `sym resolve` re-queries the four steward-assigned delisting names, gets no-match, and re-queues them once before the gate holds again. Pairs with the quota goal of Story 1.9.
- Delisting-fixture price histories: TWTR/ATVI/LEHMQ/CSGN now exist in `securities` (steward-assigned 2026-06-10) but have no prices — yfinance drops delisted tickers, so the terminated histories the survivorship fixtures exist for need the second-vendor adapter (EODHD, already on this ledger) or a manual import. Until then they surface in `unpriced_securities`. ENE (review #4) stays OPEN by design — the seed note marks it as the permanent queue-routing fixture; the gate makes it free.

## Deferred from: code review of 1-10-symbology-scd-transitions (2026-06-10)

- Dual-listing representation: a security legitimately fed under two listing MICs would ping-pong SCD transitions on alternating writes (composite FIGIs are country-level, so NYSE/NASDAQ dual-feeds are plausible). No alternating writer exists today (the bridge only creates missing securities); needs a representation design before one does. Pairs with the relisting securities.mic/currency scope-out above.

## Deferred from: code review of A-1-analytics-boundaries (2026-06-10)

- **Types freshness is not an enforced gate:** O.2's API surface (`/api/operate/history`, `heartbeat_at`, `takes_scope`) sat stale in the committed `lib/api-types.ts` until A.1's regen caught it up. The "CI freshness check" is a script with no runner (no remote/CI exists) — staleness is only caught when someone happens to regen. Candidate: a pre-commit hook or a `sym validate`-style local gate that diffs `gen:types` output against the committed file.
- **NaN weight hypothetical:** a NUMERIC `'NaN'` weight would slip analytics' `total_w <= 0` guard (NaN comparisons are False) and serialize NaN metrics. No writer produces NaN today (`upload_weights` takes floats from validated API input) — revisit only if a new weights writer appears.

## Deferred from: Story C.1 console submenus (2026-06-11)

- **~~Console lint baseline is RED (pre-existing)~~ — ✅ DONE (QH.7, commit `5f08d24`, 2026-06-16):** the 12-error RED baseline (`react-hooks/set-state-in-effect` in theme-toggle/analytics-panel/heatmap-view/3 pages, `react-hooks/refs` + `react/no-unescaped-entities`) was cleared with **real fixes, no suppressions** — `theme-toggle` → `useSyncExternalStore`, fetch effects rewritten as async-IIFE-with-lazy-`useState`-loading (so `setLoading` no longer fires synchronously in the effect body), the heatmap `pos.w` tooltip clamp, and apostrophe escapes. Re-verified 2026-06-19: `npx eslint .` is green (71 files, 0 errors / 0 warnings) with `react-hooks/set-state-in-effect` enabled as an error `[2]`.
- **Eurostat egress outage (2026-06-11 afternoon) — ✅ RESOLVED same day:** `ec.europa.eu` returned 307 "Network Error" HTML from the egress proxy for ~an hour mid-story, then recovered; a re-ingest categorised everything (zero NULL categories, 33/33). Kept as a note because the outage usefully exercised the designed failure path (per-series attributed errors, old data intact, NULL categories excluded from the submenu) — and because external-egress flaps of this kind WILL recur: the fix is always just rerunning `python -m macro.ingest`.
- **Submenu providers stay bespoke by design (NFR-10):** sym = static registry, macro = categories fetch, hardcoded in `sidebar.tsx`'s `subnavFor`. When a third module wants a submenu, extract the provider interface then — not before.

## Deferred from: code review of Q8-4-broaden-macro-coverage (2026-06-11)

- Mid-series partial failure understates committed state: macro ingest autocommits per row, so a DB error halfway through a series leaves rows persisted while the summary reports `obs: 0, ok: False` — the accounting can't see what was written before the death. Pairs with the "run-log row written up-front" ledger item (accounting-under-failure design).
- Quarterly/weekly SDMX periods (`2025-Q1`, `2025-W23`) are skipped as garbled by `_parse_period` — a misconfigured non-monthly dataset yields a silently-empty series (`ok: True, obs: 0`), indistinguishable from genuine no-data. Needs frequency-aware period parsing if a quarterly source is ever configured.

## Deferred from: Story Q8.4 broaden macro coverage (2026-06-11)

- **~~Pre-existing sym test breakage — INVOCATION-SPECIFIC~~ — ✅ DONE (2026-06-17):** `test_durable_reviews.py::test_fx_coverage_warns_on_open_rejections` did `from tests.test_fx_coverage import _Conn` (no `packages/sym/tests/__init__.py` → ModuleNotFoundError under `uv run pytest` from the package dir). Fixed via the one-liner — `from test_fx_coverage import _Conn` (the bare top-level module both invocations agree on). Full suite now 688 passed, 0 failed. Done as a classification-retro quick win.
- **OECD CPI Japan ends 2021-06** in the `DF_PRICES_ALL` flow (USA/GBR/BRA run to 2026) — served-as-is, not padded. If a current JPN CPI matters, find the successor OECD flow or another source.
- **World Bank euro-area CPI (`WB:FP.CPI.TOTL.ZG:EMU`) returns no data as of 2026-06-11** (the other 12 WB series fetch fine). The series never had observations (original "13 series" = 12 WB + ECB), so nothing is lost — but if euro-area CPI is wanted, `EU:HICP:EA` (Eurostat, monthly) now covers it better than the WB annual series would.
- **ECB MRR change-point compression can strand one stale row:** the stored series keeps a previous run's last-observation row that today's compression no longer re-emits (upsert never deletes). Real observed values, harmless drift (+1 row); a reconcile-and-prune pass would need a delete rule the loader deliberately doesn't have.
- **Eurostat `une_rt_m` has no euro-area aggregate** (EA/EA19/EA20 all return empty geo dimensions; probed 2026-06-11) — `EU27_2020` is configured instead; revisit if a true euro-area unemployment series appears.

## Deferred from: code review of portfolios-live-heatmap-and-pizza (2026-06-19)

- **Route `ValueError`→422 is over-broad** (`packages/analytics/src/analytics/router.py` `portfolio_composition`) — any unrelated `ValueError` on the path would be mislabeled an over-cap 422; only the `COMPOSITION_MAX` check raises `ValueError` today, so low risk. Narrow with a dedicated exception or a pre-check if the path grows.
- **`test_composition_writes_nothing` only inspects the sym conn** (`services/api/tests/test_portfolio_composition.py`) — the portfolios conn is a monkeypatched `object()`, so a hypothetical portfolios-side write wouldn't be caught. Code is SELECT-only so the property holds; strengthen the test with a recording portfolios conn if the gateway ever writes.
- **Pizza net center can render "−0.0%"** (`apps/web/components/portfolio-pizza.tsx`) — a tiny negative net that rounds to 0 prints `−0.0%`. Cosmetic; normalize the sign when the rounded magnitude is 0.
- **First-load 503 shows the error banner but no map** (`apps/web/app/portfolios/[id]/page.tsx`) — AC4 "map stays" only holds on a failed REFRESH after a good load (last-good `comp` retained); on a first-load failure there is no map to keep, and the refresh affordance is hidden when `n_holdings === 0`. Matches the heatmap-view last-good pattern; add a first-load retry button if wanted.

## Deferred from: code review of portfolios-live-grid-eod-returns (2026-06-20)

- **"Latest `as_of` per window" is not unit-tested** (`services/api/tests/test_portfolio_composition.py`) — the DB-free fake conn can't exercise the SQL `DISTINCT ON (composite_figi, window_id) … ORDER BY as_of_date DESC`; the unit test feeds pre-deduped rows. The query mirrors the proven Explorer security-detail template, but the "picks the most recent as_of" guarantee rests on code inspection. Add a DB integration test (or a fake conn that honors DISTINCT-ON ordering) to close it.

## Deferred from: code review of portfolios-grid-pivot-grouping (2026-06-20)

- Group weight % uses Σ|weight| over a signed `total_weight` denominator (`portfolio-pivot.tsx:427` group `.map`, `subtotalCell` `wt/gross`). Pre-existing — the old `SectorGroup` aggregated identically. Only diverges for long-short books (gross |weight| vs net signed total); harmless for long-only. Revisit if/when short positions land in the live grid.

## Deferred from: code review of portfolios-nested-grouping (2026-06-20)

- `labelSpan` floors at 1 (`portfolio-pivot.tsx`): when ALL leading non-aggregate columns are grouped (≥6-level nesting) — or an aggregate column is reordered to the front — the subtotal/grand-total WEIGHT % is subsumed under the label cell and not displayed. Column count stays aligned (colSpan preserves the other columns), and it matches the documented labelSpan fallback for "aggregate dragged to front". Only triggers at contrived deep nesting; realistic 2–3-level grouping (sector→country→ccy) keeps ticker/name/mic leading and is unaffected. Revisit if deep nesting becomes common — e.g. clamp the label to a visible non-agg column or render the weight total in a pinned cell.

## Deferred from: code review of indexes-msci-eod-pull-and-page (2026-06-21)

- `sym msci-pull` recomputes only a trailing 365-day `fact_index_returns` window (cli.py `_cmd_msci_pull`), identical to the B4 `sym msci-import` predecessor. A fresh ~26-year MSCI backfill therefore leaves `fact_index_returns` uncomputed for everything older than 1 year (the Indexes page is unaffected — it computes trailing returns from raw `index_levels` via the API). Run a full-history index-returns recompute (EOD pipeline / `benchmarks` step) if deep-history index alpha is needed against the newly-seeded MSCI instruments.

## Deferred from: code review of portfolios-live-returns-fix (2026-06-22)
- **Sort test doesn't distinguish live_return vs window_returns["1D"]** (apps/web/__tests__/portfolio-pivot.test.tsx) — the 1D-sort assertion holds under either field. Correct-by-construction (cell + sort share the `windowReturn` accessor; the cell is proven), so cosmetic test-strengthening only; a distinguishing fixture is fiddly.
- **Trailing windows show most-recent-non-null without a per-cell staleness mark** (packages/analytics/src/analytics/gateway.py composition) — Cause B's skip-null intentionally surfaces the last reviewed return when the latest date is gated/null (documented in the SQL comment). A per-cell "window as-of" / stale indicator is a future enhancement, not a bug.

## Deferred from: code review of ticker-region-codes (2026-06-22)
- **exchange verify passes if a MIC row is entirely absent** (verify/exchange_bbg_exchange_code.sql + the exchange_figi_exch_code precedent both use `NOT EXISTS ... IS NULL`, which a missing row satisfies). Rows are seeded so it doesn't bite today; optional hardening = also assert the major MIC rows EXIST.
- **Bloomberg venue-code accuracy (bbg_exchange_code)** — display-only, no in-repo authority. Cross-check the less-common seeded codes (XBOM IB, XNSE IS, XFRA GF, XTSE CT, XASX AT) against a Bloomberg exchange-code list, and fill the 4 deliberate NULLs (XASE, ARCX, XSHG, XSHE) once confirmed.
- **Detail (/sym/securities/[figi]) + Attention pages show the bare ticker** — inconsistent with the Explorer convention on click-through, exactly where same-ticker ambiguity (ADS Adidas vs Bread Financial) matters most. Adopt the qualified-ticker helper there (needs the detail/composition payloads to carry exch_code/bbg_exchange_code). Open Q#3 deferral.
- **Pivot grid Ticker column** — adopt the qualified-ticker convention (the composition payload must expose the codes). Open Q#3 deferral.

## Deferred from: code review of ticker-region-detail-pivot (2026-06-22)
- **Per-row store subscription in the pivot Ticker column** — each row's `QualifiedTicker` island calls `useTickerConvention()`, so an N-holding book registers N store + N window 'storage' listeners (the Explorer subscribes once at page level). Correct + idiomatic, immaterial at realistic book sizes; if a very large book needs it, lift to one page-level `useTickerConvention()` in PortfolioPivot + a Context the island reads (keeping the standalone hook fallback for the detail page).

## Deferred from: code review of portfolio-returns-skip-gated (2026-06-22)
- **Behavioral test for the returns date-pin skip-null** — the portfolios returns tests use a DB-free fake conn that can't execute SQL, so the gated-skip is only guarded by an SQL-text assertion (`"pr IS NOT NULL" in sql`), like the existing `"0.9"` broadly-complete guard. A true behavioral test (gated latest date → pin falls back to the earlier clean date → constituents populated) would need a SQL-capable fake (SQLite/in-memory pg). Behavior was verified live (3→100/100). Same harness limitation as the composition skip-null test.

## uk-rates-curve-store (2026-06-22, dev complete -> review)
- **sqitch deploy pending (Docker down):** `rates` DB + `curve_point` schema applied directly to the dev instance (deploy SQL is `IF NOT EXISTS`). Run `sqitch deploy` for project `rates` (db:pg://…/rates) once Docker is up — no-op-pending (the ticker-region-codes precedent).
- **Running API server (:8001) predates the `rates` install** → serves `/api/rates/curve` + `/curve/series` only after its next restart. Endpoint verified in-process (router mounts, gateway correct); not force-restarted per the minimize-churn rule.
- **api-types regen deferred** to the follow-on console story — no web consumer of `/api/rates` exists yet (run `npm run gen:types` against a live API that has rates mounted when the rates page lands).
- **Full-history backfill not run** — only the latest (current-month) BoE bundle loaded (13,140 nodes, 2026-06). One-time `rates curve load --start_date <floor>` pulls the ~39 MB per-curve archive zips when wanted.
- **Derived analytics layer (the big follow-on):** spreads (2s10s/flies/breakeven/asset-swap) + carry/roll off the forward curve + DV01/dirty-price + a console page. Pin BoE's exact compounding/day-count (methodology FAQ) first → makes the forward→spot reconciliation EXACT (currently an approximate WARN-level diagnostic). Then bond reference-data (cashflows) for specific-gilt pricing (curve→position bridge). See uk-rates-curve-store.md "OUT of scope" + the brainstorm doc.
- **`curve_point_review` queue has no promote tool yet** — implausible prints land there but there's no `rates curve review --accept` CLI (mirror `sym fx review`). Add when the first real flag appears.

## Deferred from: code review of uk-rates-curve-store (2026-06-22)
- **AC#6 stale check: UK bank-holiday calendar** — `check_staleness` excludes weekends only; a curve last published before a Bank Holiday Monday reads false-stale. WARN-only (no data/gating impact). Add a UK holiday calendar (e.g. exchange_calendars XLON) when building the derived-analytics layer.
- **AC#1 BoE compounding/day-count convention** — not captured from the BoE methodology FAQ; needed to make the forward→spot reconciliation EXACT (currently approximate WARN). Pin it in the derive-on-read story.
- **Ingest: `prev` not chained on a flagged point** — a sustained real >5pp daily move would flag every subsequent day. Theoretical for gilt curves (500bp/day doesn't happen); revisit only if the review queue fills.
- **Desync gate blind spot** — `expected_pairs` is derived from the most-complete day IN THE BATCH, so a wholesale-missing-basis bundle or a single-day premature publish can land a half-curve. Persist the expected basis-set (or compare to the last stored complete day) to close it.
- **`/api/rates/curve` enum validation** — params are free `str`; a typo returns HTTP 200 + empty curve instead of 422. Add `Literal` types when the rates console page is built.
- **`/curve/series` count(DISTINCT as_of_date)** — fine now (13k rows); over full gilt history this is the count-distinct latency trap. Revisit at scale (per the freshness-per-market guidance).
- **No download/extract size cap (zip-bomb)** — `_download`/`_parse_zip_bytes` read fully into memory with no cap. Trusted BoE host; add a ceiling if the source changes.
- **AC#5 explicit unit-canonicalization assert** — currently the `curve_point` value CHECK (>-10 AND <30) is the de-facto write-time representation guard; an explicit parser-level assert (values look like % p.a.) is a nice-to-have.

## rates-curve-analytics (2026-06-22, dev complete -> review)
- **Web tsc/eslint/vitest not runnable locally** — `apps/web/node_modules` is an incomplete install (empty `.bin`; no top-level typescript/eslint/vitest/next). Reinstalling is the churn `feedback_minimize_dev_churn` forbids (broke lightningcss). The rates page was verified via the sanctioned method (dev-server HTTP 200 + headless-Chrome dump-dom render, no error overlay) + a written `rates-page.test.tsx`. Run `tsc --noEmit` / `eslint` / `vitest run` wherever the web toolchain is whole (CI) and fix any nits.
- **api-types regen deferred** — needs a live API with `rates` mounted; `:8001` predates the rates install. The page uses LOCAL TS types (not `Schemas`), so this is non-blocking; regen `npm run gen:types` once the API serves `/api/rates/*`.
- **Live page→API→DB end-to-end pending `:8001` restart** — same caveat as the store. The data path is proven in-process (gateway `spreads()` returns real values; routes registered). The page currently renders its shell but the curve/spread fetches 404 against the stale server.
- **Full carry/roll monitor card** — `analytics.carry_roll` exists (roll-down + forward-implied carry) but the standard monitor set surfaces roll-down implicitly via spreads; a dedicated carry/roll card (with horizon selector) is a small follow-up.
- **Asset-swap is a yield proxy** (gilt − OIS), not a true par/par ASW — upgrades when bond reference-data (cashflows) lands.

## Deferred from: code review of rates-curve-analytics (2026-06-22)
- **`spreads()` reads full per-leg history on every summary load** [rates/gateway.py] — fine now (~13k rows; 15 days), but once the full-history archive is backfilled (decades × ~80 nodes/day per leg-group) the `/api/rates/spreads` card pays full-history cost for a latest value + 60-point sparkline. Switch to a windowed z-score (e.g. trailing 5y) at scale.
- **Leg-calendar mismatch silently thins a spread series** [rates/gateway.py `_spread_series`] — a date contributes only when ALL legs are published that day. Gilt & OIS share BoE's release calendar today, but a future 2nd source / different calendar would shrink the intersection with no diagnostic. Add a coverage/diagnostic note if that lands.
- **`spread_history` window floor anchored to the last data date, not today** [rates/gateway.py] — intentional (chart relative to available data); document so a stale feed's "1Y" isn't surprising.

## Deferred from: code review of dagster-job-buckets (2026-06-23)

- **universe `mode: monitor|refresh` flag** — the universe bucket hardcodes `sym universe monitor` (the correct default). The spec-optional `refresh` (re-resolve + reproject) capability is not wired to the launchpad. Add a `mode` field to `BucketConfig` when an operator wants per-run refresh. (Spec-optional feature, not a defect.)
- **rates per-country registry discovery** — the `rates` bucket has no discovery callable, so an explicit `--country` selection isn't validated against a registry (a bad country errors at the CLI). The "all" path relies on `rates curve load-world` iterating internally. Add a `rates countries` read if enumerable/validatable subcategories are wanted on the launchpad.
- **regenerate `apps/web/lib/api-types.ts`** — still carries dead `/api/sym/overview` + `SymOverview` entries after the Overview removal. No live consumer (the page uses local types), but the generated artifact is stale. Regenerate via openapi-typescript when the web toolchain is runnable locally.

## Deferred from: code review of commodities-store (2026-06-24)

- **Web tsc/eslint/vitest not runnable locally** — `apps/web/node_modules` is an incomplete install (the known `feedback_minimize_dev_churn` constraint). The `/commodities` page changes are pure client logic (no Next.js API surface); reviewed by inspection. Run `tsc --noEmit` / `eslint` / `vitest` wherever the web toolchain is whole (CI).
- **api-types regen deferred** — `apps/web/lib/api-types.ts` does not yet carry the `commodities` schemas; the page uses LOCAL TS types. Regenerate once `:8001` is restarted with `commodities` mounted.
- **Plausibility band re-flags an entire series after one flag** [commodities/ingest.py] — on a flagged day `prev[key]` is not advanced, so a sustained REAL regime shift floods `price_review`. Opt-in (`--band_pct`, default off) and identical to the `rates` idiom; revisit only if banding is enabled and the queue fills.
- **430-day board window vs 1Y/YTD anchor** [commodities/gateway.py] — `window_start` is anchored to the GLOBAL max as_of_date; a commodity lagging the global max can have its 1Y/YTD anchor fall before the window and resolve to `None` (blank), and a badly-stale commodity drops off the board silently. Conservative (blanks, never wrong numbers). Widen the window or anchor per-commodity if blanks show up.
- **`validate` uses naive `date.today()`** [commodities/validate/checks.py] — recency/staleness thresholds can flip by a day at the UTC/local boundary. `rates` threads an explicit `as_of_date` fallback; do the same here when an EOD job needs a pinned business date.
- **history 1Y/5Y cutoff `365*yrs`** [commodities/gateway.py] — ignores leap days (5Y shows ~4y363d). Chart-window cosmetic.
- **No source-adapter registry module** — `commodities/sources/` has the `PriceSource` protocol + one adapter; the named `registry.py` pattern (cf. `rates`) is unbuilt. Add when a 2nd source (deep-history / OI) lands.
- **Universe 22 codes < ~25–30 target** [commodities/universe.py] — all six sectors covered but base metals is COPPER-only (aluminium/zinc/nickel are LME, not freely on yahoo `=F`). Add probe-confirmed `=F` roots to reach the target.
## Deferred from: code review of backtest Tier-1 remainder (sweep/stats, 2026-06-24)

- **`/backtest` page surfacing of DSR/PBO/MinBTL** — the sweep verdict is computed + persisted + reachable via `GET /api/backtest/sweeps[/{id}]`, but the console page does not yet show it. Add a sweep panel (DSR, PBO, MinBTL-satisfied, verdict_credible) when the web toolchain is being worked.
- **`best.sharpe_ann` vs the linked run's own summary** [backtest/sweep.py] — the sweep reports the best config's Sharpe computed on the COMMON-day aligned series, while `best_run_id`'s own persisted summary Sharpe is on that config's full series. They won't reconcile when configs have different date coverage. Either compute the headline on the full series or label the sweep figure as "common-window".
- **Stale `summary.best.run_id` after a run delete** [backtest/db sweep.sql] — `sweep.best_run_id` is `ON DELETE SET NULL`, but the frozen JSONB `summary.best.run_id` still names the deleted run. A consumer following the JSON id 404s. Re-resolve from the column, or scrub the summary on delete.
- **`norm_ppf` returns ±inf for p≤0 / p≥1** [backtest/stats.py] — not reachable from current call sites (args are `1−1/N`, `1−1/(N·e)`, N≥2), but a future caller passing a raw probability gets inf/nan into a persisted summary rather than a clean error. Raise on out-of-domain p if it ever gets a public caller.
- **`len(common) < 2·n_splits` gate uses the requested n_splits** [backtest/sweep.py] — rejects a sweep that PBO could still run after auto-reducing S. Over-strict (usability, not correctness); relax to the reduced S if short-history sweeps become common.
- **σ_SR estimated over runnable configs while N = full grid** [backtest/sweep.py] — if some grid points error out, the cross-trial Sharpe stdev feeding DSR/MinBTL is from fewer than N Sharpes. Defensible (no Sharpe for a config that didn't run) and the conservative N is preserved; note only.
## Deferred from: code review of rates sources (Fed GSW + ECB expansion, 2026-06-24)

- **Web tsc/eslint/vitest not runnable locally** — `apps/web/rates/page.tsx` changes (source-provenance labels, curve-set labels gsw/govt_all, the √-tenor interpolation fix in `valueAtTenor`, and moving the cross-country overlay onto the main chart) were reviewed by inspection (no Next.js API surface). Run the web toolchain in CI; regenerate `api-types.ts` for the new optional `source` field once `:8001` is restarted.
- **fed_gsw: a nominal-file download failure also drops the TIPS curves** [rates/sources/fed_gsw.py] — `fetch` downloads `feds200628` then `feds200805` with no per-file guard, so a transient failure on only the nominal file loses the (independently fetchable) real/inflation curves for that run. The CLI attempt-all isolates US/fed_gsw from US/ustreasury (no crash), but unlike the ECB per-series tolerance, the two GSW files fail as a unit. Wrap each file independently if partial GSW loads become desirable.
- **gateway `curve()` takes `source = rows[0][2]`** [rates/gateway.py] — assumes every node of one series/day shares a single source (true today). If a future backfill ever mixed sources within one (series, day), the surfaced provenance would be the first row's only. Benign; documented.
- **`band_pp=20` backfill band applied to Fed GSW daily 60-year history** [rates/cli.py load-world] — the 20pp band was tuned for monthly/sparse official series; GSW is daily back to 1961 and includes the early-1980s rate spikes. Verify a full GSW backfill isn't spuriously routing real large moves to review (the band only means to catch decimal-shift corruption).

## Deferred from: code review of data-monitor-compact-counts (2026-06-24)

- **Rates instrument-count column coupling** [data_monitor/eod.py `_instrument_count`] — the rates
  "curve" count hardcodes `count(DISTINCT (country, curve_set, basis, rate_type))`; those three
  non-`country` column names live only in the gateway, decoupled from the `rates` `Dataset` (which
  declares just `group_column="country"`). Verified correct against `curve_point.sql`+`multi_country.sql`
  and it degrades safely (a rates-schema rename → caught by the never-500 try/except → bucket reads
  `unknown`, no count). If the rates schema drifts, the board would mask it behind an "unknown" pill
  rather than failing loudly. Promote the curve key into the `Dataset` (e.g. a `count_columns` tuple)
  if a second composite-count bucket appears.

## Deferred from: code review of fx-package (2026-06-24)
- fx_extract drop migration has no in-migration copy-verification guard before the destructive DROP (one-time live migration was done safely copy→verify→drop; fresh rebuilds have no data; re-runs no-op). Consider a row-count parity assertion if the pattern is reused.
- No cross-DB reconciliation between fx.currency and sym.currency: a currency added to sym's seed won't exist in the fx DB → fx load FK-fails for it / fundamentals.market_cap_usd silently NULLs. Add a validate check (cross-DB currency-set equality) or auto-seed unknown currencies on fx load.
- API FX-matrix (fx_matrix / fx_matrix_live) raises a raw 500, not a 503, if the fx DB is unreachable (the documented 503 contract only covers live-quote unreachability). Map an fx-DB OperationalError to a graceful response.
- Data Monitor fx-bucket degrade path lost test coverage when the boom test moved to equity_prices; add a test that the fx bucket degrades to 'unknown' when the fx DB read fails.
- sym fundamentals / sym fx CLI open the fx connection unconditionally, so they now hard-depend on fx-DB availability even for paths that barely use FX. Consider lazy-opening the fx conn only when the FX leg is actually needed.
- recompute_market_cap_usd uses a fixed TEMP-table name (_fx_rate_tmp); a concurrent recompute reusing one sym connection could collide. Low-probability under single-threaded EOD; use a unique temp name if pooled reuse becomes possible.
