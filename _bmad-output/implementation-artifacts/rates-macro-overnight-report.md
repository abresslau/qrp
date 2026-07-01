# Overnight enrichment report — rates (all countries) + macro (IBGE)

**Run:** 2026-06-30 → 07-01, autonomous. **Ask:** "check the rates for each country and enrich them …
all rates nominal, real, etc. populated for all countries, up to yesterday / all vertices"; then, when
rates is done, "add more relevant macro datasets (e.g. IBGE)".

> **2026-07-01 UPDATE:** the overnight branches were merged to `main`, and a follow-up replaced the
> monthly HK/FR sources with daily ones and topped up CH — see the **Addendum** at the end. The
> per-country table + "Git state" below are updated; the narrative TL;DR reflects the overnight run.

## TL;DR
- Every daily source **refreshed to the latest published business day**; three stale/thin sources
  investigated and **JP fixed** (freshness) + **ES upgraded** (thin→full daily curve).
- **Real curves added for CA, AU, NZ** (reusing each source's existing feed) → AU/NZ now also carry a
  derived **breakeven**. GB/US/BR already had real+breakeven.
- The honest ceiling: a **published, free, fitted _real_ curve simply does not exist** for most
  countries (DE/EU/IT/ES/SE/NO/JP/CH). Those are documented, not faked, with a re-test trigger each.
- **Macro:** added the headline **IBGE inflation** series that were missing — IPCA & INPC, monthly and
  12-month — the single most-watched Brazilian prints.
- **[Overnight] Nothing pushed** — work was committed on feature branches for review. *(Since merged +
  pushed to `main` on 2026-07-01, along with the HK/FR/CH follow-up — see "Git state" + Addendum.)*

## Rates — per-country status (as of 2026-07-01; "yesterday" = 06-30)

| Ctry | Nominal | Real | Breakeven | Vertices | Fresh to | Notes / change this run |
|---|---|---|---|---|---|---|
| **GB** | ✅ fitted | ✅ | ✅ (RPI) | 0.5–40y +OIS | 06-29 | reference (BoE) — unchanged |
| **US** | ✅ fitted | ✅ | ✅ (CPI) | 1m–30y | 06-30 / gsw 06-26 | reference (Treasury + Fed GSW) |
| **BR** | ✅ (LTN+NTN-F) | ✅ (NTN-B) | ✅ (IPCA, approx) | per-issue → ~34y | 06-30 | Tesouro (retail) + **ANBIMA reference NEW** (07-01 follow-up: nominal LTN/NTN-F + real NTN-B, `curve_set='anbima'`) — the prefixed leg stands in for the B3 DI curve |
| **DE** | ✅ fitted Svensson | ✖ ceiling | ✖ | 0.5–30y | **06-30** | refreshed +31 days |
| **EU** | ✅ fitted (AAA+all) | ✖ ceiling | ✖ | 3m–30y ×3 types | 06-29 | refreshed |
| **CA** | ✅ benchmarks | **✅ NEW (RRB 30y)** | — (single 30y pt) | 2/3/5/7/10/30y +real | 06-29 | **real added** |
| **AU** | ✅ benchmarks | **✅ NEW (10y)** | **✅ NEW 2.27%** | 2/3/5/10y +real10y | 06-24* | **real+breakeven added** |
| **NZ** | ✅ benchmarks | **✅ NEW (linkers)** | **✅ NEW 1.99%** | 1/2/5/10y + 4 real | 06-29 | **real curve+breakeven added** |
| **JP** | ✅ fitted | ✖ ceiling | ✖ | 1–40y | **06-29** | **freshness FIXED** (was 05-29) |
| **ES** | ✅ **NEW daily** | ✖ ceiling | ✖ | 0.5/1/3/5/10/15y | **06-26** | **thin→full** (BdE; was 1 monthly 10y pt) |
| **SE** | ✅ benchmarks | ✖ ceiling | ✖ | 2/5/7/10y | 06-29 | refreshed |
| **NO** | ✅ benchmarks | ✖ ceiling | ✖ | 3m–10y | 06-29 | refreshed |
| **FR** | ✅ **10y DAILY** | ✅ (10y) | ✅ (10y) | 10y | **nom 07-01** / real 06-01 | **nominal now DAILY** (AFT TEC-10, 07-01 follow-up); real/BE stay OAT€i monthly |
| **IT** | ⚠ 10y only | ✖ ceiling | ✖ | 10y (monthly) | 05-01 | ceiling — see below |
| **CH** | ✅ **10y (OECD)** + frozen spot | ✖ ceiling | ✖ | 10y yield + spot 1–30y | **10y 2026-05** / spot 2025-07-31 | **OECD monthly 10y top-up added** (07-01 follow-up); SNB spot curve still frozen |
| **HK** | ✅ **DAILY** | ✖ ceiling | ✖ | 1W–2Y | **06-30** | **now daily** (EFBN indicative-price, 07-01 follow-up; was monthly-bulletin 05-29; 5–15y long end dropped) |

\* AU nominal itself lags to 06-24 (RBA F2 publish cadence) — a source lag, not fixable.

`rates validate`: **exit 0, zero FAIL** across all countries. After the 07-01 follow-up (FR/HK/CH
below) the only remaining staleness WARN is **AU** (RBA publish lag) + a transient ES band hole; the
overnight run's AU/CH/HK/FR WARNs are otherwise cleared. GB's two free checks (RPI breakeven =
nominal−real; fwd↔spot identity) pass.

## Why "real + all vertices for every country" is only partly attainable (the ceilings)
A market real curve needs a liquid inflation-linked bond market **and** a public fitted curve. Confirmed
via live probes that these do **not** exist for free:
- **DE / EU** — Bundesbank & ECB publish nominal curves only. ECB's whole SDMX catalogue has no
  BEIR/real/ILS yield-curve dataflow; Bundesbank's only "real" is a survey-derived *expected* rate
  (5y/10y monthly), not a market curve. → ceiling.
- **JP** — no fitted JGBi curve published (only per-issue JSDA quotes). → ceiling.
- **SE / NO** — Riksbank SWEA & Norges SDMX are nominal-only (NO issues no linkers). → ceiling.
- **IT** — no free daily multi-tenor curve at all (Banca d'Italia infostat is WAF-blocked, MTS is
  commercial, MEF is auction-only); stays at the ECB 10y monthly point. → ceiling.
- **FR** — real + breakeven from AFT OAT€i 10y (daily-in-file, monthly-published, `aft_fr.py`; latest
  06-01: real 1.46%, breakeven 2.19%). **Nominal is now DAILY** (07-01 follow-up — AFT TEC-10, see
  addendum), superseding the ECB 10y monthly. The nominal FULL curve is still a ceiling (BdF
  discontinued OAT rates 2024-07-10; MTS commercial; Webstat needs an API key). NB the OAT€i is
  euro-HICP-linked, so FR breakeven = EU inflation, and it's a single ~10y benchmark, not a fitted
  curve. (The openpyxl-rejects-`.xls` snag was the extension check — a BytesIO handle reads it fine.)
- **CH** — the SNB `rendoblid` daily spot curve was **discontinued** (last data 2025-07-31; the monthly
  `rendoblim` and the `rendopar` NSS params stop on the same date — an SNB-wide discontinuation). The
  fitted spot curve stays frozen, but a **fresh 10y yield is now topped up** from OECD monthly (07-01
  follow-up, see addendum). A free daily Swiss 10y does not exist (SNB was the only one; FRED blocked).

### Re-test triggers (to break the ceilings later)
- FR/IT full nominal: a commercial/MTS feed, or Banca d'Italia infostat dataflow code (contact BdI).
  (FR nominal 10y is now daily via TEC-10 — this trigger is only for the FULL fitted curve.)
- CH: a non-SNB full-curve vendor for the fitted spot curve (the 10y benchmark is now covered by OECD).
- HK: ~~monthly-bulletin lag~~ RESOLVED (07-01 follow-up — daily EFBN indicative-price). The dropped
  5–15y long end returns if HKMA issues on-the-run EFNs at those tenors again.
- AU: reload after the next RBA publication (source cadence lag, not a bug).
- BR: ~~ANBIMA ETTJ authoritative curve~~ ADDED (07-01 follow-up — ANBIMA Mercado Secundário
  indicative rates: nominal LTN/NTN-F + real NTN-B). The literal **B3 DI futures curve** stays
  deferred: no clean endpoint in-env (the DI×Pré reference curve is behind a JS/Cloudflare page; the
  only reachable raw data is a 12MB/day BVBG-086 pregão XML — too heavy for a daily feed). Re-test =
  a browser-driven fetch of the reference-rate proxy, the B3 developers API with credentials, or a
  paid feed. The ANBIMA prefixed curve is the reachable stand-in in the meantime.
- MX/CN/DK/SG: unchanged from PULL_REPORT (auth/undocumented/discontinued).

## Addendum — 2026-07-01 follow-up: HK / FR / CH daily source fixes + BR ANBIMA
After review flagged that HK and FR should not be monthly, the sources were replaced/added (merged to
`main`; `rates validate` exits 0 with HK/FR/CH staleness now green):
- **HK** — swapped the monthly-bulletin `efbn-yield-daily` (only refreshed with the monthly bulletin →
  ran ~a month stale) for the daily `daily-monetary-statistics/efbn-indicative-price` (Reuters-priced
  twice daily). Fresh to the latest business day (06-30), tenors 1W–2Y. Trade-off: reaches only ~2y —
  HKMA has no on-the-run EFN beyond ~3y, so the old 5/7/10/15y benchmark points are dropped. Latest-
  business-day-only, so history accrues forward. `hkma.py` rewritten (`parse_records`).
- **FR** — added AFT **TEC-10** (CNO-TEC-10 nominal 10y, MTS-sourced) as a **daily** nominal-10y point
  (fresh 07-01, 3.65%), superseding the ECB Maastricht 10y monthly (removed from the FR registry to
  avoid a same-key collision — the store key has no `source`). OAT€i real/breakeven retained. New
  `aft_tec10.py` (`parse_tec10` + retry-on-403). History accrues forward.
- **CH** — added an OECD monthly **long-term (10y) interest rate** (`DF_FINMARK` `MEASURE=IRLT`, fresh
  2026-05) as a 10y `yield` point, coexisting with the frozen SNB `spot` curve (different `rate_type` →
  no key clash). Monthly points are **month-end-dated** so the ~1-month-lagged series stays inside the
  staleness cadence window. New `oecd_ltir.py` (reusable `OecdLtirCurveSource(country, geo, currency)`).
- **BR** — added the **ANBIMA** Mercado-Secundário indicative curve (`curve_set='anbima'`, coexists
  with the Tesouro retail `govt` curve): real **NTN-B** + prefixed nominal **LTN/NTN-F** (LTN
  zero-coupon preferred over a same-maturity NTN-F; NTN-F extends the long end). This is the
  authoritative reference the Tesouro docstring flagged as the follow-on. New `anbima.py`
  (`AnbimaCurveSource`, `parse_ms`). Live 06-30: 17 nominal (0→10.5y) + 15 real (0.13→34y). The
  prefixed leg is the reachable stand-in for the **B3 DI curve**, which stays deferred (no clean
  endpoint in-env — see re-test triggers).
- **Verified:** live loads landed (FR 07-01, HK 06-30, CH 437 monthly pts to 2026-05, BR ANBIMA
  06-30); rates tests 88/88 pass; ruff clean. The full Dagster `eod` job was run end-to-end
  afterwards (15/15 nodes SUCCESS) to confirm the `rates` node picks these up.

## Addendum — 2026-07-01: Brazil macro breadth (trade / employment / IBGE PIM-PMC)
Separately (macro package, merged to `main`; 45/45 macro tests pass):
- **Trade** — `BCB:TRADE_BALANCE`/`EXPORTS`/`IMPORTS` (SGS 22707/8/9, SECEX goods FOB, USD-mn monthly,
  fresh May-2026, reconcile exactly). The earlier-deferred 22704/22705 were the WRONG codes.
- **Employment** — `BCB:CAGED_STOCK` (SGS 28763, Novo CAGED formal-employment stock, fresh Apr-2026).
- **IBGE PIM/PMC** — the SA index levels were already live (the deferred "zero rows" note was stale);
  added the growth prints `IBGE:PIM_MOM`/`PIM_YOY` + `PMC_MOM`/`PMC_YOY` (tables 8888/8880, fresh
  Apr-2026). The old "non-JSON metadata" blocker was just gzip on the `/agregados/{t}/metadados` API.
- **Skipped:** IPEADATA EMBI (dead since 2024-07-30, no fresh free source).

## Macro — IBGE enrichment
Added the headline **inflation** series that were missing from the IBGE/SIDRA catalogue (we had the IPCA
index + YTD, unemployment, GDP, industrial production, retail — but not the most-watched rate prints):
- `IBGE:IPCA_MOM` — IPCA monthly % (latest 0.58%)
- `IBGE:IPCA_12M` — IPCA 12-month % (latest **4.72%** — the headline inflation number)
- `IBGE:INPC_MOM` — INPC monthly %
- `IBGE:INPC_12M` — INPC 12-month % (latest 4.42%)

All verified against SIDRA (deep history to ~1980) before adding. (PMS services-volume was probed but
needs a classification pin — left as a follow-on.) Full `macro load` ran green: **814 series /
324,542 observations** (the 4 new IBGE series loaded 546–566 obs each). Note we now carry IPCA-12m from
both IBGE (the statistics office, official) and BCB (the central bank's republish) — complementary
provenance. `macro load` is idempotent, so re-running is safe.

## Git state (MERGED — 2026-07-01)
All overnight branches were reviewed and **merged to `main`**, and pushed:
- `feat/rates-enrich-realcurves-freshness` (`bbc2ebb`) — the rates enrichment.
- `feat/macro-enrich-national-stats` — the IBGE additions.
- `feat/rates-fr-oatei-real` (`ab2ec67`) — FR OAT€i real/breakeven.
- **07-01 follow-up (all merged + pushed):** `feat/rates-hk-fr-daily-sources` (daily HK + FR TEC-10),
  `feat/rates-ch-oecd-10y` (CH OECD 10y top-up), `feat/rates-anbima-ntnb` + `feat/rates-anbima-nominal`
  (BR ANBIMA real + prefixed nominal), plus the macro-breadth branches `feat/macro-br-trade-employment`
  and `feat/macro-ibge-pim-pmc-growth`. Also `chore/retire-commodity-job` (commodity → eod node only).
  See the Addenda above.
- The data is loaded in the rates/macro databases.
