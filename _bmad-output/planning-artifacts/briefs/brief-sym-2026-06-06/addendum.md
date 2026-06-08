---
title: "Addendum: sym Universe Layer — design & sourcing detail"
status: ready
created: 2026-06-06
updated: 2026-06-06
---

# Addendum — sym Universe Layer

Downstream detail for the PRD / architecture workflow. Not part of the 1–2 page brief.

## A. Provider abstraction sketch (mirrors AR-5 OHLCV source pattern)

A `UniverseProvider` Protocol + config-keyed registry, parallel to `src/sym/sources/` (the `fetch_ohlcv` Protocol + `register_source` registry).

- Conceptual contract: given a universe config, yield **point-in-time membership** — members with `valid_from` / `valid_to` and the best available identifier(s). Sketch:
  - `members(start, end) -> Iterable[UniverseMember]` where `UniverseMember = {identifier(s): ticker+MIC and/or ISIN, valid_from, valid_to, source, provenance}`.
- Registry keyed by config (`{provider: "sp500"}`, `{provider: "custom_list", path: ...}`, `{provider: "criteria", rule: ...}`), so adding a provider is a registration, not a pipeline change.

### v1 providers
1. **Index — by source archetype, not one-per-index** (the key design choice; adding an index = config; the layer picks best-source-per-index + falls back). Archetypes, in preference order:
   - **Open-finance-API provider (FMP / OpenBB)** — *preferred for US flagships*. FMP free tier: `sp500_constituent` / `nasdaq_constituent` / `dowjones_constituent` (current) **and** `historical/sp500_constituent` (dated add/remove events). OpenBB `index.constituents(provider=fmp)` wraps the same (current-focused). **US-only**; free tier ~250 calls/day; **risk:** FMP relabels constituent endpoints "Legacy" and tightens free access — verify live; archetype fallback is the mitigation.
   - **ETF-holdings provider** — *preferred for European flagships* + big/gated US (S&P 400/600, STOXX Europe 600, later Russell). Daily holdings CSVs (iShares/Amundi/Xtrackers); self-archiving = clean PIT-forward + corroboration source. Less brittle than Wikipedia.
   - **Wikipedia provider** — component table + reusable **revision-diff engine**; **fallback/corroboration**, and the only free *20-year* PIT for S&P 500 (community repos `fja05680/sp500` since 1996, `riazarbi/sp500-scraper` to 2006). Also the free path for CAC 40 / EURO STOXX 50 / IBEX / AEX / SMI (no API/`yfiua` coverage). The free `yfiua/index-constituents` GitHub dataset (monthly snapshots, Yahoo-aligned symbols) is a lower-brittleness alternative but covers only **DAX / FTSE 100 / FTSE MIB** since ~2023.
   - **Exchange-CSV provider** *(out of US/Europe scope for now)*: openly-publishing exchanges — B3, NSE India (ISIN), JPX/KRX/TWSE/BMV. Future archetype.
   - **Yahoo is NOT a membership archetype** — yfinance has no reliable constituents; Yahoo stays the *price* source (U4) and a *corroboration* signal only.
   Membership only (sym derives GICS via Story 1.8). v1 = **S&P 1500** (FMP for the 500 current+history, repos for 20y backfill, ETF for 400/600), then European flagships (ETF-holdings + Wikipedia).
2. **Custom list.** Generalization of `seed_universe.toml`: tickers+MIC and/or ISINs, optional effective dates. Today's 50-name seed becomes an instance.
3. **Criteria.** Rules-based screen (e.g. "US common stock, top N by month-end market cap"). Needs reference fundamentals (see §C).

## B. Membership store (event log + projection)

**Truth = `membership_event` log** (append-only): `(universe_id, raw_identifier, change: join|leave|correct, effective_date, effective_date_precision, source, provenance, recorded_at)`. Immutable; corrections are appended corrective events (AR-6/AR-10 pattern), never mutations.

- **`effective_date_precision`** (Feynman gap): a dated API (FMP) gives an *exact* effective date; snapshot-diffing (Wikipedia/ETF) only bounds it to the polling gap (`exact` vs `poll_bounded`). Daily polling caps `poll_bounded` uncertainty at ≤1 day — a concrete reason the cadence is daily. Don't silently flatten poll-bounded dates to look exact.
- **Source preference is per-index config with automatic fallback** (e.g. FMP→ETF→Wikipedia): the resolver-of-sources tries the preferred archetype, falls back on failure, and records which one produced each event (provenance).

**Read-model = `universe_membership` interval (SCD) table**, *projected* from the log — same shape/constraints family as `security_symbology` / `gics_scd` (btree_gist no-overlap EXCLUDE per (universe, member)). Columns ≈ `(universe_id, composite_figi NULLABLE, raw_identifier, valid_from, valid_to, source, resolution_status)`. Rebuildable from the log at any time; this is what queries hit.

- `composite_figi` nullable because a member may be **known but unresolved** (delisted leaver OpenFIGI can't map). `resolution_status` ∈ {resolved, unresolved, unpriced} — retain-and-flag, never drop (survivorship honesty; ties to Story 3.7).
- Ingestion reads `WHERE valid_to IS NULL` (or as-of) members with `resolution_status = resolved` to drive `run_load`; the rest are visible backlog.
- **`pit_valid_from` per universe** (pre-mortem #2): the date trustworthy history begins — ~20y ago for repo-seeded S&P 1500, ≈ tracking-start "today" for European build-forward indexes. Membership queries before it MUST refuse or loudly flag; never back-project current members onto earlier dates. This is the universe-level survivorship guardrail.
- **Frozen resolution** (pre-mortem #3): a member's `composite_figi` is resolved *as-of its membership dates* (ISIN-preferred) and frozen at first resolution — a recycled ticker can never re-point a historical member at a different company.

## B2. Daily index maintenance (change detection) — core v1 mechanism

The universe is maintained, not defined once. Design notes for the architecture/epics:

- **Scheduled daily monitor** per configured index: fetch current constituents (Wikipedia / ETF archetype) → diff against the stored *current* membership → record **joiners** (insert `universe_membership` row, `valid_from=today`, `valid_to=NULL`) and **leavers** (close the open row, `valid_to=today`). This is change-data-capture into the SCD; over time it accumulates genuine point-in-time history even where no free historical source exists (the European flagships).
- **Sanity-gating (AR-9-style two-stage).** A diff that churns more than a guard threshold, or a parse that returns empty/garbage, must NOT auto-apply — it's flagged for review (a vandalized Wikipedia page or a layout change shouldn't wipe a universe). Small, plausible diffs auto-apply; large swings annotate-then-await-confirm, mirroring the price-anomaly model. Threshold is tunable (open question).
- **Freshness/liveness (pre-mortem #1).** Every universe stores `last_successful_monitor`; a monitor that hasn't succeeded in N days alarms, and an empty/failed parse is an **error**, never silently treated as "no changes today" (a frozen universe is the most insidious failure).
- **Corroboration + reversibility (pre-mortem #4).** A detected change must persist N days OR be confirmed by a second source (e.g. the ETF-holdings archetype) before it's recorded; the change log is an **appended, reversible audit trail** — a bad event can be rolled back, never silently overwrites history.
- **Change log** akin to `pipeline_run_log`: every monitor run records {index, date, joiners, leavers, action: applied|flagged|corroborating}. Auditable.
- **Membership accuracy gate (pre-mortem #7, Epic U3.5).** Periodic cross-check of derived current membership vs an independent second source (Wikipedia-vs-SPY-holdings for S&P 500); divergence beyond a threshold alarms — an SM-6 analogue for *membership* (catches a *wrong* universe, not just a stale one).
- **Seeding vs maintaining.** S&P 1500: seed 20y PIT from community repos (one-time backfill), then maintain forward. European flagships: seed current snapshot, maintain forward (PIT grows from day one).
- **Scheduling mechanism** is an implementation detail (Windows Task Scheduler / cron / a `universe monitor` CLI invoked by a scheduler) — out of brief scope; the monitor itself is idempotent (re-running the same day is a no-op).

## C. Criteria provider's data dependency (the main new dependency)

Rules-based screens need market cap = price × shares outstanding, plus ADV (computable from stored EOD volume×price). sym stores prices but **not shares outstanding / market cap** today.

- Free US options: FMP (free tier, market-cap + shares endpoints, US-strong, throttled), yfinance fast_info (flaky intl). Global/reliable shares-outstanding → EODHD bulk fundamentals (paid).
- Decision for PRD: either (a) include a minimal fundamentals input in v1 to unlock criteria, or (b) ship index + custom-list first and fast-follow criteria once a fundamentals source exists. Brief flags this as an Open Question.

## D. Source-feasibility matrix (individual budget, ~20y point-in-time)

| Universe | Free PIT? | Best individual-paid | Notes |
|---|---|---|---|
| S&P 500 / 400 / 600 (S&P 1500) | ✅ to ~2006 (Wikipedia-diff repos) | EODHD ~$50/mo (S&P/DJ, but only ~12y → ~2014 floor) | **v1 target.** Membership free; delisted-leaver *data* still needs paid source |
| Nasdaq-100, DJIA | 🟡 Wikipedia-diffable | — | Same S&P/DJ-ish family, easy follow-on |
| Russell 1000/2000/3000 | ❌ | **Norgate Platinum ~$630/yr** (PIT to 2000) | EODHD does NOT cover Russell. Out of v1 |
| CRSP US Total Market | ❌ | CRSP via WRDS (institutional / free w/ university) | Out of v1 |
| MSCI World / ACWI / EAFE / EM | ❌ (unavailable to individuals) | none retail; MSCI/LSEG institutional | URTH proxy current-only, since 2012. Out of v1 |
| FTSE All-World / Global All Cap | ❌ | none retail | Licensed. Out of v1 |
| Rules-based (e.g. top-N mktcap) | 🟡 (US, via free fundamentals) | EODHD bulk fundamentals (global) | The license-free escape hatch; needs fundamentals (§C) |

## D2. Free index availability by market (current vs point-in-time)

Survey of popular indexes by market (mid-2026). Free **current** membership is feasible almost everywhere via one of the three archetypes; free **point-in-time** is a short list.

| Market | Indexes | Free current (archetype) | Free PIT | ID |
|---|---|---|---|---|
| USA | S&P 500 | Wikipedia | **Yes, turnkey** (repos to 1996) | ticker |
| USA | S&P 400/600, Nasdaq-100, DJIA | Wikipedia / ETF | Partial (WP-diff; 400/600 noisier) | ticker |
| USA | Russell 1000/2000/3000 | ETF-holdings (IWB/IWM/IWV) | Partial (annual June recon files) | ticker |
| **Brazil (B3)** | **Ibovespa, IBX, IBrX-50, SMLL** | **Exchange-CSV (carteira teórica, +weights)** | Partial (archived portfolios) | local ticker |
| **India (NSE)** | **Nifty 50, Nifty 500, Sensex** | **Exchange-CSV (CSV +ISIN)** | Partial (niftyindices historical reports) | symbol **+ISIN** |
| Germany | DAX/MDAX/SDAX/TecDAX | Wikipedia (+ISIN often) | Partial (WP-diff) | ticker/ISIN |
| UK | FTSE 100/250/350/All-Share | Wikipedia (100/250) / ETF | Partial (100/250) | ticker (.L) |
| France | CAC 40, SBF 120 | Wikipedia / Euronext | Partial (CAC 40) | ticker (+ISIN) |
| Pan-EU | EURO STOXX 50, STOXX 600 | Wikipedia (50) / ETF (600) | Partial (50) / No (600) | ticker (+ISIN) |
| Japan | Nikkei 225, TOPIX | Nikkei list / JPX | Partial (225) / No (TOPIX) | 4-digit code |
| Hong Kong | HSI, HSCEI | Wikipedia / ETF | Partial (HSI) | HK code |
| China | CSI 300, SSE 50 | CSI site / ETF | No | .SS/.SZ |
| Canada | S&P/TSX Comp, TSX 60 | Wikipedia (60) / ETF | Partial (60) | ticker (.TO) |
| Australia | S&P/ASX 200, All Ords | Wikipedia / ETF | Partial (200) | ticker (.AX) |
| Korea | KOSPI 200 | KRX / ETF | No | 6-digit code |
| Taiwan | Taiwan 50, TAIEX | ETF (0050) / TWSE | Partial (50) | .TW code |
| Switzerland | SMI, SPI | Wikipedia (SMI) | Partial (SMI) | ticker (+ISIN) |
| Spain/Italy/NL/Mexico | IBEX 35, FTSE MIB, AEX, IPC | Wikipedia / ETF | Partial (all small flagships) | local ticker |

**Ease ranking (most free coverage / least effort):** US → Brazil (B3) → India (NSE) → UK → Germany → France/NL/EU-flagship → CH/ES/IT → Canada/Australia → Hong Kong → Japan → Taiwan/Korea/Mexico → China → broad/whole-market (ETF-only, no PIT).

**Honest framing:** free PIT outside the US is a *manual Wikipedia-diff exercise limited to small flagship indexes* — there is no non-US equivalent of the S&P 500 community repos. Most non-US universes are realistically *current-now, build-PIT-forward*.

**Trademark/licensing:** index *names* (S&P, FTSE, STOXX, Nikkei, TOPIX, MSCI, CSI, Hang Seng) are trademarks; membership *facts* aren't copyrightable, but official index *feeds* are licensed. Source free providers from public web pages / Wikipedia / ETF filings (not licensed feeds), for personal research, and don't market them as the official index.

## E. Identifier gotchas (feed the ISIN-first resolver)

- Free index/ETF sources hand you **tickers** (iShares intl files sometimes carry ISIN/SEDOL/CUSIP — capture when present; ISIN is the cleanest OpenFIGI key).
- **Ticker recycling** is the survivorship trap: a delisted name's old ticker may be reused (EODHD literally shows `ACR` reassigned, old = `ACR_old`). Resolving a leaver by ticker alone silently grabs the wrong company → pin (ticker, as-of-date, exchange); prefer ISIN/CUSIP for delisted.
- OpenFIGI: ISIN is best primary key but broad (one security across listings) → still disambiguate by exch_code (per `reference_openfigi_resolution`); the ISIN-fallback + home-listing narrowing just built handles this.
- Reality check from the build session: of the 5 seed delistings, only ATVI & CSGN resolved (by ISIN, ambiguous-with-candidates); TWTR/LEHMQ/ENE purged from OpenFIGI entirely → genuinely unresolvable free.

## F. Key source links

- Free S&P PIT: github.com/fja05680/sp500 ; github.com/riazarbi/sp500-scraper
- EODHD: eodhd.com/pricing ; historical constituents (S&P/DJ only) eodhd.com/marketplace/unicornbay/spglobal ; delisted eodhd.com/financial-apis/delisted-stock-companies-data
- Norgate (Russell PIT): norgatedata.com/data-content-tables.php ; norgatedata.com/prices.php
- MSCI constituent history (institutional): msci.com/www/product-documentation/msci-constituent-history/0163808536
- ETF-holdings proxy: ishares.com (IVV/IWV/URTH) ; github.com/talsan/ishares
- Screening fundamentals: site.financialmodelingprep.com/developer/docs
- Free index constituents (current/PIT): financialmodelingprep.com (US current+historical) ; github.com/yfiua/index-constituents (DAX/FTSE100/FTSE MIB) ; docs.openbb.co/platform/reference/index/constituents

## G. Architecture Decision Records (provisional)

Provisional ADRs capturing the *why* behind the brief's choices, for the architecture/epics workflow to formalize. Format: decision · alternatives · rationale · consequence.

**ADR-1 — Provider abstraction = Protocol + config-keyed registry (mirrors AR-5).** *Alt:* bespoke loader per index; config-driven monolith. *Rationale:* reuses sym's existing OHLCV-source pattern, makes "add a source = register" literal, quarantines source brittleness behind one seam. *Consequence:* contract must span snapshot AND dated-event sources; needs registry/config schema.

**ADR-2 (scored) — Source archetype priority: API-first (US) / ETF-holdings (Europe) / Wikipedia fallback.**

Weighted comparison (criteria/weights: PIT-history 25, robustness 20, coverage 20, identifier quality 10, cost/terms 10, low-maintenance 15; scores 1–5, % of max):

| Archetype | PIT | Robust | Cover | ID | Cost | Maint | Score |
|---|---|---|---|---|---|---|---|
| FMP / OpenBB API | 5 | 4 | 2 | 3 | 3 | 4 | 73% |
| ETF-holdings | 3 | 4 | 5 | 4 | 4 | 3 | 76% |
| Wikipedia + diff | 3 | 2 | 3 | 2 | 4 | 2 | 53% |
| yfiua repo | 2 | 3 | 2 | 3 | 4 | 4 | 56% |

Region-blind, ETF edges FMP on coverage. Region-specific (re-scoring coverage vs the actual target) decides it: **US** → FMP ≈ **85%** (dated-event PIT dominates where it has coverage) = winner; **Europe** → FMP coverage 0 (out), **ETF wins (76%)**, Wikipedia fallback (53%), yfiua narrow (56%, only DAX/FTSE100/MIB). Conclusion: best-source-*per-index* — ETF is the highest-coverage workhorse + universal fallback; FMP wins only where it has coverage (US).

 *Alt:* Wikipedia-first everywhere; one source per region. *Rationale:* FMP gives dated US events (least brittle); Europe has no free API so self-archived ETF holdings are least-brittle + PIT-forward; Wikipedia is universal fallback/corroborator; best-source-per-index behind the abstraction. *Consequence:* multiple parsers; FMP free-tier dependency risk (mitigated by fallback).

**ADR-3 — Membership = point-in-time SCD with a `pit_valid_from` honesty boundary.** *Alt:* current snapshot only; SCD that silently back-projects before tracking start. *Rationale:* survivorship is sym's reason to exist — a snapshot reintroduces bias and silent back-projection is worse (an invisible lie); `pit_valid_from` makes the boundary explicit (refuse/flag pre-history queries). *Consequence:* membership queries carry as-of semantics; seed `pit_valid_from` per universe.

**ADR-4 — Change detection = daily poll + diff (CDC), corroborated and sanity-gated — not event-driven.** *Alt:* true event subscription (no free feed); naive poll, trust-the-source. *Rationale:* no free event bus; daily poll is the pragmatic CDC, upgraded to event-grade where FMP supplies dated changes; corroboration + gate defend against bad/vandalized sources. *Consequence:* idempotent scheduler; guard-threshold tuning; N-day corroboration latency (acceptable).

**ADR-5 — Resolution = ISIN-preferred, as-of membership date, FIGI frozen at first resolution.** *Alt:* re-resolve by current ticker each run. *Rationale:* ticker recycling silently corrupts historical members; freezing the FIGI preserves identity integrity and reuses the ISIN-first resolver. *Consequence:* store per-member resolved FIGI + resolution date; re-resolve only on explicit correction.

**ADR-6 — Unresolved/unpriced members are retained-and-flagged, never dropped.** *Alt:* drop unresolved (clean but survivorship-biased). *Rationale:* an unpriceable member is backlog, not a non-member — dropping it is the bias sym exists to kill. *Consequence:* nullable `composite_figi` + `resolution_status` + coverage metric.

**ADR-7 — Maintenance-first delivery (U1–U3.5 before U4 ingestion).** *Alt:* ingest-as-you-define. *Rationale:* ingesting from an unmaintained/incorrect universe wastes effort and yields biased data; correct membership is the precondition for pulling prices. *Consequence:* no universe-driven price data until U4; the existing seed keeps the returns engine exercised meanwhile.

**ADR-8 — Membership truth = append-only event log; the `universe_membership` interval (SCD) table is a derived projection.** *Alt:* SCD interval table *is* the store, corrections by mutation+audit. *Rationale:* index membership changes only via discrete dated events, so the event stream is the fundamental model and the interval table is its integral (the accumulated running state); an event log is immutable with corrections-by-append (reversibility, pre-mortem #4), merges multi-source events with provenance (corroboration), and reuses sym's AR-6 (explicit events) + AR-10 (immutable + correction sweep) patterns — lowering conceptual surface, not raising it. Subsumes/justifies ADR-3 (SCD = projection) and ADR-4 (corroboration/reversibility fall out). *Consequence:* a `membership_event` log table + a projection step to (re)build the interval read-model; providers are *event-producing* (index/list) or *function-evaluating* (criteria → compute, optionally snapshot to the log).

## H. Component failure modes (FMEA — failure modes & effects analysis)

Per-component failure → prevention, for the architecture workflow. (Whole-system scenarios are in the pre-mortem decisions; these are finer-grained.)

- **API provider (FMP):** symbology ≠ sym's (bare US tickers) → normalize to ticker+MIC=US; *orphan leave* events (removal with no prior add in-window) → tolerate/flag, don't crash projection; rate-limit (250/day) mid-backfill → call-budget + expected-vs-returned check.
- **ETF-holdings provider:** non-equity rows (cash/futures/FX) → whitelist equity, drop derivatives; **diff the identifier *set* only, not weights** (weight change ≠ membership change); ETF is a *proxy* (sampling/lag) → label proxy provenance, lean on the accuracy gate.
- **Wikipedia provider:** ticker-format drift (BRK.B/BRK-B) → normalize identifiers before diffing (reuse sym normalization); vandalism-mid-revert → N-day persistence/corroboration rule.
- **Membership event log:** duplicate events across sources → idempotent append, dedupe key `(universe, id, change, effective_date)`; conflicting effective dates → **source-precedence** (official/dated-API wins; keep both); late/out-of-order corrections → projection **rebuilds from the full ordered log**, never incremental-only.
- **Projection (log → intervals):** *mid-membership ticker rename* → would project as leave+join (spurious survivorship gap) → **project at the CompositeFIGI level, not raw ticker** (resolve first); overlap caught by btree_gist EXCLUDE; property test `invert(project(log)) == log`.
- **Daily monitor:** per-index partial failure hidden by a global flag → **per-index `last_successful_monitor`**; effective dates on non-trading days / TZ skew → align to the exchange calendar.
- **Resolution bridge:** unresolved backlog grows silently → **unresolved count + age metric**; non-common-stock members (REIT/units/when-issued) → flag by `securityType`.
- **Ingestion bridge:** a new joiner has prior history → **join triggers historical backfill** over its membership window (forward-only leaves a hole); a leaver stops forward fetches without daily re-try.
- **Accuracy gate:** "independent" sources that share an upstream (both Yahoo-derived) → false confidence → pair genuinely independent sources (FMP vs ETF); proxy-aware tolerance to avoid alert fatigue.

