# Multi-country rates pull — overnight report

**Run:** 2026-06-23, autonomous (story `fx-matrix-rates-curves`). Goal: yield curves for every FX-matrix
country, EUR broken down by country, pulled from central banks where reachable in-env. Probe-first,
attempt-all, never-block. **Each source below was confirmed with a live in-env `curl`.**

## Probe results — per country (source, reachability, exact endpoint)

| Country | Ccy | Source | Verdict | Tenors | rate_type | History | Endpoint (confirmed) |
|---|---|---|---|---|---|---|---|
| GB | GBP | Bank of England | **DONE** (prior story) | 0.5–40y +short | spot+fwd | 1979 | (xlsx zip) |
| **DE** | EUR | Bundesbank BBSIS (Svensson) | **USABLE — full curve** | 0.5y,1–30y | spot | 1997 | `api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A` (Accept: text/csv) |
| EU | EUR | ECB YC (euro-area aggregate) | **USABLE — full curve** | 3M–30Y | spot (Svensson) | 2004 | `data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_<T>?format=csvdata` |
| US | USD | US Treasury par yield curve | **USABLE — full curve** | 1M–30Y | par | 1990 | `home.treasury.gov/.../pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=<YYYY>` (parser exists in macro) |
| JP | JPY | MoF Japan JGB | **USABLE — full curve** | 1–40y | spot | 1974 | `mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv` |
| CH | CHF | SNB rendoblid | **USABLE** (monthly) | 1–30y | spot | 1988 | `data.snb.ch/api/cube/rendoblid/data/csv/en` |
| CA | CAD | Bank of Canada Valet | **USABLE** | 2/3/5/7/10y+long | yield | 2001 | `bankofcanada.ca/valet/observations/group/bond_yields_benchmark/json` |
| AU | AUD | RBA table F2 | **USABLE** | 2/3/5/10y | yield | 2013 | `rba.gov.au/statistics/tables/csv/f2-data.csv` |
| NZ | NZD | RBNZ table B2 | **USABLE** (needs browser UA) | 1/2/5/10y | yield | 2018 | `rbnz.govt.nz/-/media/.../b2/hb2-daily-close.xlsx` (UA: Mozilla) |
| SE | SEK | Riksbank SWEA | **USABLE** | 2/5/7/10y | yield | 1987 | `api.riksbank.se/swea/v1/Observations/<id>/<from>/<to>` (ids SEGVB2YC/5YC/7YC/10YC) |
| NO | NOK | Norges Bank | **USABLE** | 3M/6M/12M/3/5/7/10Y | yield | 2019 | `data.norges-bank.no/api/data/GOVT_GENERIC_RATES/B.<T>.GBON?format=csv` |
| HK | HKD | HKMA EFBN | **USABLE — full curve** | 7d–15y | yield | 1991 | `api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/efbn/efbn-yield-daily` |
| BR | BRL | Tesouro Direto (Prefixado=nominal) | **USABLE** | per-issue maturities | yield | 2007 | `tesourotransparente.gov.br/ckan/.../precotaxatesourodireto.csv` |
| FR | EUR | ECB IRS (Maastricht 10y) | **LIMITED — 10y only** | 10y | yield | 1986 | `data-api.ecb.europa.eu/service/data/IRS/M.FR.L.L40.CI.0000.EUR.N.Z?format=csvdata` |
| IT | EUR | ECB IRS 10y | **LIMITED — 10y only** | 10y | yield | 1986 | `.../IRS/M.IT.L.L40.CI.0000.EUR.N.Z` |
| ES | EUR | ECB IRS 10y | **LIMITED — 10y only** | 10y | yield | 1986 | `.../IRS/M.ES.L.L40.CI.0000.EUR.N.Z` |
| SG | SGD | MAS (auction yields) | **LIMITED — auction-level, no clean daily benchmark endpoint** | per-issue | auction yield | 2000 | `eservices.mas.gov.sg/statistics/api/v1/bondsandbills/m/listbondsandbills` |
| DK | DKK | Danmarks Nationalbank | **BLOCKED — govt curve discontinued Nov-2012** (DKK≈EUR peg; DE is the proxy) | — | — | — | (DNRENTM frozen 2012) |
| MX | MXN | Banxico SIE | **NEEDS-AUTH (free token)** — skipped per autonomy rule (don't obtain tokens) | — | — | — | `banxico.org.mx/SieAPIRest` (needs `?token=`) |
| CN | CNY | ChinaBond | **BLOCKED — endpoint reachable but POST schema undocumented; returns empty** | — | — | — | `yield.chinabond.com.cn/cbweb-mn/yc/searchYc` |

**Re-test triggers:** MX → register a free Banxico SIE token. CN → capture the live `searchYc` POST body via
browser devtools. FR/IT/ES full curves → a national-CB or vendor source (ECB only gives 10y). DK → a
non-DN vendor (or accept the EUR/DE proxy). SG → capture the benchmark-by-tenor endpoint from the MAS .aspx.
NZ uses a browser User-Agent. Norges starts 2019 (shallower).

**Side finding (logged for Andre):** the `reference_env_external_sources` memo says "FRED blocked" — a
probe today returned HTTP 200 from `fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`. The note is stale;
re-verify before relying on it either way. (We use the central-bank sources directly regardless.)

## Build plan (this run)
Foundation: add `country`/`currency` to `curve_point`; generalise ingest/validate/gateway/router/page.
Then build adapters for the USABLE + LIMITED sources (skip MX/CN/DK as above), load, validate, and add a
**country switcher + cross-country comparison** to the `/rates` Curve & spreads page.

---

# RESULTS — morning of 2026-06-23 ✅

**16 countries loaded** (GB from the prior story + 15 from the registry). All historical, straight from
the central banks. `rates validate` is **green (no FAIL)** across every country. The `/rates` page now has
a country switcher (all 16) and a cross-country compare overlay — verified end-to-end in a real browser.

## What landed (rows · history · type)
| Country | Source | Rows | History | rate_type | Note |
|---|---|---:|---|---|---|
| GB | Bank of England | 6,395,898 | 1979→ | spot+fwd | prior story; glc nominal/real/inflation + OIS |
| DE | Bundesbank BBSIS (Svensson) | 219,617 | 1997-08-07→2026-06-22 | spot | full curve 0.5–30y |
| US | US Treasury par curve | 98,354 | 1990-01-02→2026-06-22 | par | 1M–30Y |
| CH | SNB rendoblid | 97,321 | 1988-01-04→**2025-07-31** | spot | source vintage ends Jul-2025 (stale, see below) |
| HK | HKMA EFBN | 81,840 | 1991-06-10→2026-05-29 | yield | 2 prints flagged→review |
| EU | ECB AAA yield curve | 66,828 | 2004-09-06→2026-06-19 | spot | euro-area aggregate, 3M–30Y |
| JP | MoF JGB | 162,607 | 1974-09-24→2026-05-29 | yield | 1–40y |
| SE | Riksbank SWEA | 39,543 | 1987-01-02→2026-06-18 | yield | 2/5/7/10y |
| CA | Bank of Canada Valet | 38,209 | 2001-01-02→2026-06-19 | yield | 2/3/5/7/10/30y |
| BR | Tesouro Direto (Prefixado) | 27,805 | 2004-12-31→2026-06-19 | yield | per-issue tenors (nominal LTN) |
| AU | RBA table F2 | 12,930 | 2013-05-20→2026-06-17 | yield | 2/3/5/10y |
| NZ | RBNZ table B2 | 7,948 | 2018-01-03→2026-06-19 | yield | 1/2/5/10y; needed a full browser UA (WAF) |
| NO | Norges Bank | 7,480 | 2019-01-02→2026-06-19 | yield | 3/5/7/10y |
| FR | ECB long-term (Maastricht) | 485 | 1986-01-01→2026-05-01 | yield | 10y only, **monthly** |
| IT | ECB long-term | 423 | 1991-03-01→2026-05-01 | yield | 10y only, monthly |
| ES | ECB long-term | 415 | 1991-11-01→2026-05-01 | yield | 10y only, monthly |

EUR is broken down **by country** as you asked — DE first (full curve), then the FR/IT/ES 10y points and
the `EU` aggregate. DE/EU give a real euro curve; FR/IT/ES are 10y-only because the ECB is the only
directly-published national series (a fuller national curve needs a per-country source — re-test trigger
below).

## Validation (green — `rates validate`, exit 0)
- No FAILs anywhere. GB's two exact free checks pass (inflation = nominal−real within 0.02pp; the
  forward↔spot continuous-compounding identity within 0.5pp).
- Plausible-band PASS for all 16. Staleness is per-cadence: WARN (not FAIL) on **CH** (source data ends
  2025-07-31), **JP** and **HK** (publish ~monthly with a lag → latest 2026-05-29), and **AU** (latest
  2026-06-17, 6 calendar days). These are honest source-lag warnings, not data errors.

## NOT loaded (blocked / needs-auth — unchanged from the probe, with re-test triggers)
- **DK** — Danmarks Nationalbank discontinued its govt curve (Nov-2012). DKK≈EUR peg; DE/EU is the proxy.
- **MX** — Banxico SIE needs a free API token; skipped per the autonomy rule (don't obtain credentials).
  *Re-test:* register a Banxico SIE token, add a `banxico.py` adapter.
- **CN** — ChinaBond `searchYc` endpoint reachable but POST schema undocumented (returns empty).
  *Re-test:* capture the live POST body from browser devtools.
- **FR/IT/ES full curves** — only the 10y is published by the ECB. *Re-test:* a national-CB or vendor
  source (e.g. Banque de France / Banca d'Italia / Tesoro Público term structures).
- **SG** — MAS only exposes auction-level yields, no clean daily benchmark-by-tenor endpoint.

## Where to see it
`/rates` (console) → **Country** switcher (top-right, all 16) drives the curve + spreads. New
**"Compare across countries"** section overlays any set of countries' headline nominal curves on one tenor
axis (each labelled with its rate_type, since spot/par/yield differ by source). `rates curve coverage`
lists per-country/series coverage; `rates curve load-world [--country XX]` re-runs the pull.

## Engineering notes (for later)
- **Schema:** `curve_point` re-keyed on `(country, curve_set, basis, rate_type, tenor, as_of_date)`;
  `rate_type` broadened to spot/forward/par/yield; value band widened to (−10,60). Two covering indexes
  (as_of_date-leading for curve-by-date; tenor-leading for spread-series). Applied directly via psycopg
  (Docker down) — **sqitch deploy of `multi_country` is pending** when the container is back up.
- **Perf trap fixed:** a spread leg filters `tenor = ANY(list)`; psycopg binds a Python float list as
  `float8[]`, and `numeric = ANY(float8[])` silently bypasses the index → a multi-million-row seqscan
  (16s for the UK spreads page). Cast to `::numeric[]` in the query → ~0.3s/leg. `countries()` likewise
  drops `count(DISTINCT as_of_date)` (the distinct-count-over-6M-rows trap).
- **Schedules:** added a `rates_world_daily` Dagster schedule (weekdays 18:30 America/New_York, explicit
  tz, STOPPED until enabled) that tail-loads all countries + validates. GB keeps `rates_curve_daily`.
- **Adapters:** one module per source under `packages/rates/src/rates/sources/`, each separating a pure
  parser from the network fetch (the BoE pattern); registry in `sources/registry.py`.
