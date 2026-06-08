---
stepsCompleted: []
inputDocuments: []
session_topic: ''
session_goals: ''
selected_approach: ''
techniques_used: []
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** {{user_name}}
**Date:** {{date}}

## Session Overview

**Topic:** FX-rate storage — a canonical, USD-referenced model. Store one USD-base
quote per currency (USDBRL, USDGBP, USDJPY, …) and **derive** any cross (e.g.
GBPBRL = USDBRL / USDGBP) rather than storing both directions or every pair.

**Goals:** a storage + derivation design that is minimal (store-once), reconstructable
(immutable raw + derived crosses, no redundant inverses), and integrates with the
existing model (sym_id, per-instrument `currency_code`: IBOV→BRL, FTSE→GBP, S&P→USD …)
so prices / market caps / returns can be expressed in a common currency.

### Session Setup

Facilitated ideation: design the FX storage layer + surface edge cases before building.

## Technique Selection

**Approach:** AI-Recommended Techniques

**Recommended sequence:**
- **First Principles Thinking** (Phase 1) — reduce FX storage to irreducible truths; produce the canonical model + derivation rule.
- **Assumption Reversal** (Phase 2) — flip load-bearing assumptions (store-only-USD-base, USD-hub, one-rate-per-day, USD-base vs market quote).
- **Failure Analysis / pre-mortem** (Phase 3) — work backward from a wrong number to edge cases → schema constraints + validation checks.

**AI Rationale:** Concrete data-model design with edge-case discovery → foundation → stress-test → harden.

## Ideas Generated

### Phase 1 — First Principles (results)

**[Foundations #1] Directed ratio:** a rate = units of QUOTE per 1 BASE at an instant; direction is a stored fact, not inferred from the 6-letter code.
**[Foundations #2] Two identities collapse the space:** inverse (BRLUSD=1/USDBRL → never store both) + triangulation (GBPBRL=USDBRL/USDGBP → store vs one pivot). N currencies = N−1 series; inverses/crosses are a view, not a table.
**[Foundations #3] USD/USD=1 is injected, never stored.**
**[Decision] USD pivot for ALL currencies** — pure star graph (no per-currency forest/peg anchors for now).
**[Decision] Daily EOD rate** — one value per (currency, date) for now; evolve later to named fixings/intraday.
**[Foundations #4] Source dimension from day 1:** store source-tagged raw (like prices_raw) so a purchased feed is *additive*; a canonical rate per (currency, date) is chosen by source precedence.

**Canonical model (provisional):**
- `fx_rate` (immutable, source-tagged): `(currency_code, as_of_date, rate_per_usd, source)`, PK `(currency_code, as_of_date, source)`; USD not stored.
- Derived view/function: canonical pick by source precedence; inverse = 1/rate; cross XXXYYY = rate(YYY)/rate(XXX); USD identity injected.

### Phase 2 — Assumption Reversal (results)

**[R1 → Decision] General `(base_currency, quote_currency, as_of_date, rate, source)`, USD-base PREFERRED.**
Today every row is base=USD (star graph). A purchased *direct cross* (e.g. EURGBP fix) slots in later as a first-class row with zero schema change; derivation prefers a direct row when present, else triangulates through USD. Inverses are still never stored.
**[Integrity need surfaced] Canonical direction per pair** — must prevent storing both USDEUR and EURUSD (or both directions of a cross): one row per unordered {ccy1,ccy2} per date per source, via a currency-priority rank (USD highest) + a unique constraint / CHECK that base outranks quote.

**[R2 → Decision] As-of resolution, no stored fills:** "rate for date D" = most recent observed rate with date ≤ D; **staleness bound = 4 calendar days** (covers weekend + 1–2 holidays); beyond it → conversion NULL + "FX stale" flag. Raw stays observed-only/immutable.
**[Decision] Canonical direction:** currency priority rank (USD top, else alphabetical); CHECK rank(base)<rank(quote) + UNIQUE(base,quote,as_of_date,source). One row per unordered pair; redundant inverse impossible.

### Phase 3 — Failure Analysis (pre-mortem) → guards

| # | Failure mode | Guard | v1? |
|---|---|---|---|
| F1 | Wrong-direction ingest (vendor quotes EURUSD, stored as USD-base slot) | per-source direction map; normalize/invert to USD-base on ingest; plausibility band | **v1** |
| F2 | Triangulation rounding | NUMERIC full precision; never pre-round; round on display only | **v1** |
| F3 | Zero/negative/garbage tick (÷0 in inverse) | CHECK rate>0; jump flag (>±X%/day) like prices_review | **v1** |
| F4 | Two legs stale (GBPBRL needs USDGBP AND USDBRL) | both legs as-of≤D within bound, else NULL+flag (compounding staleness) | **v1** |
| F5 | Source disagreement | canonical pick by source precedence; cross-source divergence flag | later |
| F6 | Accidental USD/USD row | injected identity only; guard against storing USD as a currency | **v1** |
| F7 | Redenomination / peg break (series discontinuity) | stable currency_code; document discontinuity; low risk for modern data | later |

### Phase 2/3 pivot — broader data-source strategy (Google Finance + Perplexity)

**[Sources #A] Trust-tiered source registry:** new sources slot into the *same* source-tagged precedence model we designed for FX. Precedence ≈ trust tier: official exchange (B3) > licensed vendor > free-API (yfinance) > scraped (Google Finance) > LLM-derived (Perplexity). FX, prices, AND classification all become multi-source with precedence + cross-source divergence flags.
**[Sources #B] LLM-as-source needs provenance-as-truth:** Perplexity is non-deterministic, so it breaks "recompute from source." Handle by storing its OUTPUT immutably — `{model, version, prompt, citations, fetched_at}` — lowest precedence, review-gated. Reproducible *as-recorded*, not re-derivable. Extends the reconstructability invariant to non-deterministic sources by freezing the answer, not the computation.
**[Sources #C] Classification gap-fill:** Google Finance / Perplexity backfill the ~8% GICS gap (the ~134 names financedatabase misses) as *fallback* classifiers behind the primary, source-tagged ("GICS via Perplexity — review").
**[Sources #D] Google Finance access reality:** no official API since 2012 → practical access is `GOOGLEFINANCE()` via Sheets export or scrape → brittle, mid-trust; best as corroboration/spot-fill, not a primary feed.

**[Scope decision] Google Finance + Perplexity roles:**
- **Perplexity → classification gap-fill** (GICS sector/sub-industry with citations) behind `financedatabase`; lowest precedence; review-gated; output frozen `{model,version,prompt,citations,fetched_at}`.
- **Google Finance → fill level/price series yfinance lacks** (e.g. IBrX-100 `IBXX:INDEXBVMF`) + corroboration; low/mid precedence; access is scrape-only (consent wall, no API) → brittle, ToS-gray.
- Both slot into the existing source-tagged precedence (trust-tier) model — no new plumbing, just registry entries.

## Deep Research — sources & libraries (synthesis)

### FX rates
- **Primary: Frankfurter (`?base=USD`)** — free, no key/quota, ECB-backed, 31 ccys incl. BRL/GBP/EUR/JPY, server-side USD-base, daily back to 1999. (Upgrades the earlier "yfinance FX" assumption.)
- **Reconcile/ground-truth: ECB SDMX (`ecbdata`)** — authoritative EUR-base; store raw EUR-base + EUR/USD leg so USD-base is independently re-derivable.
- **Breadth fallback: fawazahmed0 currency-api** (CC0, 200+ ccys for exotics). **Spot-check only: yfinance `=X`** (USDBRL=X already USD-base, but stale/flat-print data-quality issues).
- Gotchas confirmed: EUR-base vs USD-base (invert ECB); weekend/ECB-holiday gaps → as-of resolution + 4-day staleness (already decided); **don't forward-fill the base table** (fill in a view, flag filled rows).

### Classification (GICS gap-fill)
- **Taxonomy mismatch is the real work:** financedatabase ≈ GICS names; yfinance/FMP use **Morningstar** scheme (`Technology`/`Financial Services`/`Consumer Cyclical`); B3 has its own; GLEIF=NACE. A **crosswalk to GICS is mandatory glue** (classification.codes tables + py-gics/gics-icb).
- **Cascade:** financedatabase → **yfinance `sectorKey`** (free, global incl `.SA`/EU; needs crosswalk) → **B3 official sectorial** (BR-specific patch) → **Perplexity** (review-gated, cited) → Wikidata (large caps only). FMP is the best *paid* option (broad BR/EU). OpenFIGI/GLEIF are NOT sector classifiers.

### Perplexity (as a source)
- OpenAI-compatible API; `sonar-pro` + JSON-schema structured output + `citations`/`search_results` metadata; **~<$0.01/classification**; 50 RPM free tier is plenty.
- GICS is proprietary → output is **inference, not authoritative** (sub-industry error-prone). Store frozen `{model, version, prompt, schema, content, citations, search_results, usage, retrieved_at}`; lowest precedence; review-gated; auto-reject low-confidence.

### Google Finance — DROP for now
- No API since 2012; consent wall; `GOOGLEFINANCE()` Sheets **fails for live B3**; DIY scraping brittle/ToS; paid scrapers (SerpApi) work but cost + unverified BVMF coverage.
- **yfinance already covers** B3 stocks (`.SA`), Ibovespa (`^BVSP`), IBrX-50 (`^IBX50`). Only **IBrX-100 level** (`IBXX.SA` = 1 row) is a genuine gap — marginal; revisit via paid scraper or B3-derived level only if needed.

## Next-step stories (out of this session)
1. **FX storage layer** — `fx_rate(base_currency, quote_currency, as_of_date, rate, source)` + rank-direction CHECK + UNIQUE; Frankfurter USD-base ingest (+ ECB raw reconcile); `v_fx` derivation (inverse, triangulated cross, USD identity, as-of≤D within 4-day staleness); guards F1–F4,F6; `sym validate` FX-gap checks.
2. **Classification fallback** — GICS crosswalk table (Morningstar/B3→GICS) + cascade behind financedatabase (yfinance sectorKey → B3 → Perplexity), `classification_source` provenance, review queue for LLM-derived.
3. **(deferred) IBrX-100 level** — only if benchmark needed; paid scraper or B3-reductor-derived.
