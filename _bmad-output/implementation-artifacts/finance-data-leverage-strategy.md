# Strategy: leveraging Google Finance / Perplexity Finance (scrape or display, no APIs)

Status: strategy + probe findings (2026-06-19) · Operator: "leverage as much as possible Perplexity
Finance and Google Finance. Don't rely on api, find out ways to either scrape or simply display the
data. one example is daily news. come up with a way to scrap classification from perplexity and google."

## What I probed (in-env, 2026-06-19 — name-the-probe record)

| Target | Probe | Result | Usable? |
|---|---|---|---|
| **Google News RSS** | `news.google.com/rss/search?q=<company>%20stock` | **200, structured XML, real headlines** | ✅ **Yes — BUILT** |
| Yahoo Finance RSS | `feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL` | 200, 15KB | ✅ alt news feed |
| Google Finance quote | `google.com/finance/quote/CMA:NYSE` | 200 **but JS-SPA shell** — raw HTML has NO price/company (`Comerica` absent, no price div/attr) | ⚠️ headless-only |
| Perplexity (web/finance) | `perplexity.ai`, `/finance` | 200 **but JS SPA** (+ auth) | ⚠️ headless-only |
| **Stooq EOD CSV** | `stooq.com/q/d/l/?s=cma.us&i=d` (also cade.us, aapl.us) | **200 but JS bot-challenge** ("requires JavaScript to verify your browser") for *every* symbol incl. AAPL — no CSV | ❌ JS-walled (not a plain-fetch fallback) |
| Google / Bing / DuckDuckGo search | `…/search?q=<company> GICS sector` | 200 (Google likely a consent/JS page) | ⚠️ brittle/bot-walled |
| Perplexity / Gemini **APIs** | `api.perplexity.ai`, `generativelanguage.googleapis.com` | 401 / 403 (keyed) | ❌ no key (operator: don't rely on api) |

**Key takeaway:** the clean wins are **structured feeds (RSS)**, not scraping rendered SPAs. Google
News RSS is reachable, structured, and ToS-clean (RSS is *for* consumption). Google Finance / Perplexity
pages are JS SPAs — their data only exists after JS runs, so they need a **headless browser** to scrape
(brittle: class names/markup change without notice, and it's a ToS grey area).

## 1. Daily news — ✅ DONE (the flagship, merged 2cafc77)

Built `news.py` (Google News RSS) + `GET /api/sym/securities/{figi}/news` + a `NewsPanel` on the
security detail page. Live: AAPL → 12 real headlines (Bloomberg/Yahoo/Seeking Alpha/Axios). Fetched at
serve time, never persisted, best-effort (feed outage → empty). **This is the model for "display the
data": find the structured feed, don't scrape the page.**

Next, cheap extensions of the same pattern:
- **Universe / market news** — a news panel on the Universes or a market page (query the index name).
- **Macro/altdata news** — headlines next to a macro series.
- **"Headlines" digest** on the Overview.

## 2. Prices for the names yfinance lacks (CMA, CADE, TGNA, KLG, ZEUS…) — recommended path

These are real active names the in-env yfinance feed 404s on (a coverage gap, not delistings).
**Probed all the keyless paths — they're all blocked in-env:**
- **Stooq CSV** (`stooq.com/q/d/l/?s=cma.us&i=d`) — returns a **JS bot-challenge** ("This site requires
  JavaScript to verify your browser") for *every* symbol incl. AAPL. NOT usable via a plain fetch.
- **Google Finance** — JS SPA (no data in raw HTML).
- yfinance — 404 on these names.

So there is **no clean keyless structured fallback in-env.** Realistic options, best-first:
1. **Accept as a flagged gap** *(recommended default)* — ~8 of 650 S&P names; the Universes coverage view
   already surfaces them honestly (`partial` pills + the `?gap=` drill-down). Low effort, no fragile
   scraping.
2. **A keyed provider** (EODHD/FMP/Alpha Vantage) behind the existing source-abstraction, used only for
   the yfinance-empty residual — clean + structured, but needs a key (operator said "don't rely on api",
   so this is a last resort).
3. **Headless-browser scrape** (Google Finance, or Stooq-with-JS-solved) via the headless-Chrome harness
   already proven here — the only *keyless* path that could work, but **brittle + high-maintenance**
   (markup/challenge changes) and a ToS grey area. Build only if these specific names genuinely matter.

Recommendation: **accept the gap by default** (it's small + honestly surfaced); reach for a keyed provider
or a headless scraper only if a stakeholder needs those exact tickers. The "prefer a structured feed"
principle still holds — there just isn't a keyless one reachable here.

## 3. Classification from Perplexity / Google — honest assessment + the realistic path

The operator asked twice for a way to scrape classification from Perplexity/Google. Findings:
- **Google/Perplexity search/answer scraping is the worst option for classification**: bot-walled (Google
  returns a consent/JS page), SPA-rendered (needs headless), ToS-fraught, AND **redundant** — an LLM/search
  answer is exactly what the existing `llm` source provides (Claude → reviewed artifact), and the
  precision is no better.
- **What already covers this need:** the multi-source classification matrix has `financedatabase` +
  `sec_sic` + `yahoo_profile` + **`wikidata`** (free, structured) + `llm` (the "ask an AI" answer) — and
  `perplexity`/`google` are already built as keyed API sources (dormant). The matrix is at ~99% coverage.
- **If a scrape is still wanted**, the realistic path is **headless-Chrome → Perplexity Finance**: drive
  `perplexity.ai`, ask "what GICS sector is <company>?", parse the rendered answer, map to the 11 GICS
  sectors via the existing crosswalk, write `source='perplexity'`. The scaffold exists
  (`_llm_classifier.py` base + the GICS-answer validator); only the transport (headless render instead of
  the API call) would change. **But it's brittle/low-trust and I recommend against it** vs. the
  structured Wikidata source + the reviewed `llm` source already in place.

**Recommendation:** treat Google/Perplexity as **news + display** sources (where they shine — feeds), not
as classification scrapers. If you still want it after seeing this, I'll build the headless-Perplexity
classifier behind a flag — say so.

## 4. "Simply display" — embed/link, don't scrape

For pages that are SPAs (Google Finance, Perplexity Finance), the lowest-risk "leverage" is **link out /
embed**, not scrape: e.g. a "View on Google Finance ↗ / Perplexity ↗" link on the security detail (build
the deep-link URL from ticker+MIC), and/or a daily-news panel (done). Zero maintenance, no ToS risk.

## Recommended next builds (priority order)
1. **Extend news** to the Universes/market + macro pages (reuse `news.py`) — the proven, zero-risk win.
2. **"View on Google Finance / Perplexity ↗"** deep-links on the security detail (zero-risk display).
3. **Missing-data names:** default to leaving them as flagged gaps (Stooq is JS-walled, Google Finance is a
   SPA — no keyless feed reaches them in-env). Only add a keyed provider or a headless scraper if a
   stakeholder needs those exact tickers.
4. *(only if asked)* headless-Perplexity classification source behind a flag.

## References
- `services/api/src/qrp_api/modules/sym/news.py` — the built RSS pattern (the model).
- `packages/sym/src/sym/sources/` — the source-abstraction (yfinance + EODHD) to add Stooq behind.
- `packages/sym/src/sym/classification/{_llm_classifier,perplexity,google_gemini,wikidata}.py` — the existing classifiers.
- [[reference_env_external_sources]] — env reachability; add: Google News RSS ✅, Google Finance SPA-only, search bot-walled.
- [[project_freshness_per_market]] — why the missing names show as gaps.
