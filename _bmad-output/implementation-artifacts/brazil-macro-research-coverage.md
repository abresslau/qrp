# Brazil Macro Research — Data-Coverage Gap Analysis

**Report analyzed:** *Brazil Macro Scenario — June 2026* (BTG Pactual, Macro Research, 92 pp.)
**QRP warehouse snapshot:** 370 series across 14 categories (queried live at `/api/macro/series`, 2026-06-19)
**Author:** Coverage audit for QRP macro warehouse

---

## 1. Summary

The report is a six-chapter house-view document (Global, External Sector, Fiscal, Activity, Inflation, Monetary Policy) plus three forecast tables. Its narrative leans almost entirely on **higher-frequency Brazilian series (monthly/daily)** and on **forecast/expectations data (BTG house numbers + BCB Focus)**.

**How QRP stacks up:**

- **Strong on the "spine" series.** The headline objects the report keeps returning to — IPCA, Selic, BRL, gross/net debt, primary & nominal result, current account, IBC-Br, PIM/PMC, unemployment, credit/household-debt — almost all exist in QRP at the right frequency. The Brazil monthly/daily core is in good shape.
- **The G15 cross-country layer is World-Bank-annual, but the report uses monthly/market data.** QRP has rich annual World Bank coverage for the US/EZ/China/peers (GDP, CPI, debt, FDI, CA, etc.), but the report discusses the US/EZ/China at **monthly and market frequency** (Core PCE, payrolls, HICP, breakevens, PMIs, 10y/30y yields, DXY). OECD monthly CPI and a few BLS/UST monthly series partially bridge this, but most global high-frequency series are MISSING.
- **Three whole sub-domains are essentially absent:** (a) **Brazil external *flows* detail** — trade by Trade Ministry (SECEX) at the working-day cadence, FX flow (commercial vs financial), FDI/BDI monthly, reserves are there but flows aren't; (b) **Brazil fiscal *granularity*** — central-government primary spending lines, tax collection (RFB), Treasury monthly results, quasi-fiscal impulse; (c) **agriculture/commodity *fundamentals*** — CONAB grain production, oil production (ANP/EPE), ENSO/El Niño index.
- **The single biggest structural gap is expectations breadth.** QRP has exactly one Focus series (`BCB:FOCUS_IPCA_12M`). The report's monetary-policy chapter is built on the **full Focus term structure** (IPCA for 2026/27/28/29, Selic end-of-year, GDP, FX, primary balance). This is the highest-leverage, lowest-difficulty addition (one BCB Focus/Olinda endpoint).
- **Curve gap on the Brazil side.** QRP has the policy rate (Selic/CDI) but **no Brazil yield curve / DI futures / NTN-B real yields / breakevens**. The report leans on rate differentials and the term structure; this is a notable miss.

**Counts (distinct report topics mapped):** ~70 topics inventoried → roughly **30 HAVE, 14 PARTIAL, 26 MISSING**. The missing items cluster in Brazil external flows, fiscal granularity, agriculture, the Focus term structure, and global high-frequency series.

---

## 2. Coverage tables by theme

Legend: **HAVE** = an existing QRP series is a direct match · **PARTIAL** = related but different cut/frequency/geo · **MISSING** = not present.

### Theme A — Inflation (Brazil) *(central to the report — ch. 5 + monetary)*

| Topic / metric | Freq | Authoritative source | Status | QRP series / note |
|---|---|---|---|---|
| IPCA headline (m/m, 12m) | M | IBGE / BCB SGS 433 | **HAVE** | `BCB:IPCA`, `BCB:IPCA_12M`, `IBGE:IPCA_INDEX`, `IBGE:IPCA_YTD` |
| IPCA core (exclusion, trimmed mean) | M | BCB | **HAVE** | `BCB:IPCA_CORE_EX`, `BCB:IPCA_CORE_TM` |
| IPCA-15 (headline + components) | M | IBGE SIDRA t.7060 | **MISSING** | Report uses IPCA-15 extensively (food-at-home, industrial goods, underlying services, avg core). Not in QRP. |
| IPCA "average of 5 core measures" | M | BCB (composite) | **PARTIAL** | Two cores present; report cites the 5-measure average (5.3% SAAR). |
| IPCA by group: food-at-home, industrial goods, underlying/labor-intensive services | M | IBGE SIDRA | **MISSING** | Group/sub-index breakdown is the backbone of ch.5. |
| IPCA monitored vs free (administered prices) | M | BCB | **PARTIAL** | Forecast table splits monitored/non-monitored; QRP has only headline cores. |
| INPC | M | IBGE / BCB | **HAVE** | `BCB:INPC` |
| IGP-M / IGP-DI | M | FGV / BCB | **HAVE** | `BCB:IGPM`, `BCB:IGPDI` |
| IPA (wholesale, core industrial) | M | FGV | **MISSING** | Report charts "core industrial IPA YoY" as the wholesale→retail lead. |
| IPCA expectations term structure (Focus 26/27/28/29) | D/W | BCB Focus | **PARTIAL→MISSING** | Only `BCB:FOCUS_IPCA_12M`. The dated 2026–2029 Focus paths are missing. **(High priority)** |

### Theme B — Monetary Policy & Rates (Brazil) *(central — ch. 6)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| Selic target & effective | D | BCB SGS 432 / 1178 | **HAVE** | `BCB:SELIC_TARGET`, `BCB:SELIC` |
| CDI | M | BCB / B3 | **HAVE** | `BCB:CDI` |
| Selic forecast path / terminal (Focus) | D/W | BCB Focus | **MISSING** | Report's whole ch.6 turns on the Selic path (14.50→14.25→12.50). |
| Brazil DI futures / yield curve | D | B3 / ANBIMA | **MISSING** | Term-structure & differential discussion has no Brazil curve in QRP. |
| NTN-B real yields / implied breakevens | D | ANBIMA / Tesouro | **MISSING** | Real-rate / breakeven narrative; nothing in QRP. |
| Short-term real neutral rate (~5%) | — | BCB / model | **MISSING** | House/model estimate; not a fetchable public series. |
| Estimated output gap | Q | BCB / IBGE-derived | **MISSING** | Cited (+0.4%); model-derived, would be computed not fetched. |

### Theme C — Economic Activity & Labor (Brazil) *(central — ch. 4)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| GDP (PIB, quarterly, real & nominal) | Q | IBGE | **HAVE/PARTIAL** | `IBGE:PIB` (nominal). Real q/q & demand-side components (consumption, investment, gov, X/M) **MISSING** as series (only in BTG forecast table). |
| GDP by sector (agri/industry/services) | Q | IBGE | **MISSING** | In forecast table only. |
| IBC-Br (monthly GDP proxy) | M | BCB | **HAVE** | `BCB:IBCBR`, `BCB:IBCBR_SA` |
| Industrial production (PIM) | M | IBGE | **HAVE** | `IBGE:PIM` |
| Retail sales (PMC broad) | M | IBGE | **HAVE** | `IBGE:PMC` |
| Services (PMS) | M | IBGE SIDRA t.5906 | **MISSING** | Dedicated PMS pages; not in QRP. |
| Capacity utilization (NUCI) | M | FGV/CNI via BCB | **HAVE** | `BCB:NUCI` |
| Vehicle production (ANFAVEA) | M | BCB | **HAVE** | `BCB:VEHICLES` |
| Unemployment (PNAD Contínua) | M | IBGE | **HAVE** | `IBGE:UNEMP` |
| Formal job creation (CAGED) | M | MTE | **MISSING** | Cited as a tightness signal alongside PNAD. |
| Real earnings / wages (PNAD) | M/Q | IBGE | **MISSING** | "Real wages above productivity" is a recurring claim. |
| NAIRU / neutral job-creation pace | — | model | **MISSING** | House estimates. |

### Theme D — Credit & Money (Brazil)

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| Credit outstanding / GDP | M | BCB | **HAVE** | `BCB:CREDIT_GDP` |
| Household debt-to-income | M | BCB | **HAVE** | `BCB:HH_DEBT` |
| Household debt-service burden | M | BCB SGS (comprometimento de renda) | **PARTIAL** | Have debt-to-income; debt-service ratio chart is a distinct series. |
| Default / delinquency rate (inadimplência) | M | BCB | **HAVE** | `BCB:DEFAULT_RATE` |
| New lending / concessions, spreads, avg lending rate | M | BCB | **MISSING** | "New lending declining", spreads & avg borrowing rate cited. |
| Broad money M3 | M | BCB | **HAVE** | `BCB:M3` |

### Theme E — Fiscal Accounts (Brazil) *(central — ch. 3)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| Primary result (public sector, 12m, % GDP) | M | BCB | **HAVE** | `BCB:PRIMARY_RESULT` |
| Nominal result (% GDP) | M | BCB | **MISSING** | Headline of ch.3 (8.9% 2026). Distinct SGS series; not in QRP. |
| Interest payments (% GDP) | M | BCB | **MISSING** | Driver of the nominal-deficit story. |
| Gross general govt debt (DBGG, % GDP) | M | BCB | **HAVE** | `BCB:DBGG` |
| Net public sector debt (% GDP) | M | BCB | **HAVE** | `BCB:NET_DEBT` |
| Central govt primary result & spending (real growth) | M | Tesouro Nacional (RTN) | **MISSING** | Spending acceleration pages (+5.6% real). |
| Federal tax collection (% GDP, by line) | M | Receita Federal (RFB) | **MISSING** | "Tax revenue remains strong" page + revenue-measures table. |
| Subnational (states) primary balance & cash reserve | M | BCB / Tesouro | **MISSING** | Dedicated states page. |
| Quasi-fiscal / parafiscal impulse (R$275bn) | ad hoc | BTG house | **MISSING** | Program-level table; house data, not a public series. |
| Social-security benefits queue / BPC normalization | M | Min. Desenvolvimento Social | **MISSING** | Queue normalization cost pages. |

### Theme F — External Sector & FX (Brazil) *(central — ch. 2)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| BRL/USD (PTAX) | D | BCB | **HAVE** | `BCB:BRLUSD` |
| Current account balance (monthly, USD) | M | BCB | **HAVE** | `BCB:CURRENT_ACCOUNT` |
| Current account % GDP & breakdown (trade/services/income) | M/Q | BCB | **PARTIAL** | Have monthly CA in USD; the %-GDP and 4-way decomposition are charted but not stored. |
| International reserves | D | BCB | **HAVE** | `BCB:RESERVES` |
| Trade balance — BoP (BCB) | M | BCB | **PARTIAL** | CA exists; standalone monthly BoP trade balance / exports / imports not isolated. |
| Trade balance — Trade Ministry / SECEX (US$/working day) | Weekly/M | MDIC / SECEX (Comex Stat) | **MISSING** | The report's primary trade chart; differs from BoP. **(High priority)** |
| Exports/imports by product (oil, grains) | M | SECEX | **MISSING** | Oil & distillates export volume, grain export value. |
| FX flow — commercial vs financial segment | Weekly | BCB | **MISSING** | "US$9bn commercial inflow" — central to ch.2. |
| FDI (monthly) & net FDI (FDI−BDI) | M | BCB | **MISSING** | FDI-vs-CA financing pages (annual exists via World Bank only). |
| Terms of trade | M | FUNCEX / BCB | **MISSING** | Explicitly discussed ("terms of trade improved"). |
| BRL realized vol / EM-FX beta | D | computed (Bloomberg) | **MISSING** | Derived; computable from `BCB:BRLUSD` + EM FX. |

### Theme G — Commodities & Agriculture *(central to external/inflation)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| Brent / WTI crude | D | market | **HAVE** | `MKT:BRENT`, `MKT:WTI` |
| Soybeans, corn, wheat, cotton, coffee, sugar (prices) | D | market | **HAVE** | `MKT:SOYBEAN`,`MKT:CORN`,`MKT:WHEAT`,`MKT:COTTON`,`MKT:COFFEE`,`MKT:SUGAR` |
| Iron ore, copper, gold, aluminium, etc. | D | market | **HAVE** | `MKT:IRONORE`,`MKT:COPPER`, … (18 commodities) |
| Brazil grain *production* (soy/corn/total, t) | seasonal | CONAB | **MISSING** | Record-harvest pages; production volumes, not prices. |
| Brazil oil *production* (mb/d) | M | ANP / EPE | **MISSING** | "4.3 mb/d record" — key to external story. |
| El Niño / ENSO (ONI) index & probability | M | NOAA CPC | **MISSING** | "Strong El Niño" drives 2027 inflation; a fetchable index. |
| Petrobras fuel prices / parity (gasoline, diesel) | D/M | ANP / Petrobras | **MISSING** | Fuel-subsidy & IPCA pass-through pages. |

### Theme H — Global: US / Euro Area / China *(ch. 1)*

| Topic / metric | Freq | Source | Status | QRP series / note |
|---|---|---|---|---|
| US GDP / unemployment / CPI / PCE (annual) | A | World Bank | **HAVE** | WB series for US |
| US nonfarm payrolls, unemployment (monthly) | M | BLS | **HAVE** | `BLS:PAYROLLS`, `BLS:UNRATE` |
| US CPI (monthly index) | M | BLS | **HAVE** | `BLS:CPI` |
| US PCE / Core PCE (monthly) | M | BEA | **MISSING** | Fed's target gauge; central to ch.1. |
| US private payrolls, quits, wages (proxy) | M | BLS | **PARTIAL** | Have total payrolls; quits/JOLTS & wage proxy missing. |
| Fed Funds rate (effective/target) | D | Fed (FRED) | **MISSING** | Forecast table has it; no live series (FRED blocked in env). |
| US Treasury par yields 3M/2Y/10Y/30Y | D | US Treasury | **HAVE** | `UST:PAR_YIELD:*` |
| US 5y5y / breakeven inflation | D | market/FRED | **MISSING** | Charted (US & EUR 5y5y). |
| NY Fed Global Supply Chain Pressure Index (GSCPI) | M | NY Fed | **MISSING** | Used as a goods-inflation lead in two charts. |
| Euro area HICP (headline) | M | Eurostat | **HAVE** | `EU:HICP:EA` |
| EZ core HICP, energy HICP, negotiated wages | M | Eurostat / ECB | **MISSING/PARTIAL** | Headline only; core/energy/wages charted. |
| EZ unemployment (monthly) | M | Eurostat | **HAVE** | `EU:UNEMP:EU27` |
| EZ / country GDP q/q | Q | Eurostat | **PARTIAL** | Annual WB only; report uses q/q by country. |
| Manufacturing PMI (EZ + countries) | M | S&P Global | **MISSING** | Charted; licensed data, hard. |
| ECB policy rates (DFR/MRR/MLFR) | D | ECB | **HAVE** | `ECB:DFR`,`ECB:MRR`,`ECB:MLFR` |
| China CPI / PPI (monthly) | M | NBS | **MISSING** | Charted (annual WB CPI only). |
| China activity (retail, IP, FAI), house prices, credit impulse | M | NBS | **MISSING** | China activity page. |
| Global 10y/30y yields (UK/GER/ITA/JPN) | D | market | **MISSING** | Only US Treasury yields in QRP. |
| DXY / EUR / JPY / CNY / GBP | D | market | **HAVE** | `MKT:DXY`,`MKT:EURUSD`,`MKT:USDJPY`,`MKT:USDCNY`,`MKT:GBPUSD` |

### Theme I — Markets

| Topic | Freq | Status | QRP series |
|---|---|---|---|
| Ibovespa, S&P 500, Nasdaq, Stoxx50, FTSE, Nikkei, Mexbol, VIX, DXY | D | **HAVE** | `MKT:*` (9 series) |

---

## 3. Prioritized retrieval backlog

Difficulty: **Low** = single known public API/endpoint, well-documented · **Med** = endpoint exists but needs parsing/normalization or SIDRA navigation · **High** = licensed/derived/no clean public feed.

> Note: BCB SGS series codes below are marked **(verify)** where I am not 100% certain of the exact number; confirm against `https://www3.bcb.gov.br/sgspub` before wiring.

### Priority — HIGH (core to the report's narrative)

1. **BCB Focus full term structure** — IPCA (2026/27/28/29), Selic eop, GDP, BRL, primary balance.
   Source: BCB **Olinda Focus API** (`https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais`). Freq daily. **Difficulty: Low.** Highest leverage — unlocks the whole monetary chapter.

2. **Brazil trade balance — Trade Ministry / SECEX** (exports, imports, balance; total + by product, working-day basis).
   Source: MDIC **Comex Stat** API (`api-comexstat.mdic.gov.br`). Freq monthly (weekly partials). **Difficulty: Med.** The report's primary external chart; differs from BoP.

3. **FX flow — commercial vs financial segment** (weekly, US$mn).
   Source: BCB SGS — *fluxo cambial*. SGS codes ~ 22707/22708/22709 **(verify)** or BCB "Fluxo cambial" report. Freq weekly. **Difficulty: Med.**

4. **Fiscal: nominal result & interest payments (% GDP, monthly).**
   Source: BCB SGS — nominal result `5727`**(verify)**, interest `4253/5520`**(verify)** (NFSP series). Freq monthly. **Difficulty: Low.** Completes the deficit story already half-covered by `BCB:PRIMARY_RESULT`.

5. **Central-government primary result & primary spending (real growth).**
   Source: **Tesouro Nacional** Resultado do Tesouro Nacional (RTN); Tesouro Transparente / SICONFI API. Freq monthly. **Difficulty: Med.**

6. **Federal tax collection (arrecadação, RFB).**
   Source: Receita Federal monthly "Arrecadação" (also BCB SGS for federal revenue **verify**). Freq monthly. **Difficulty: Med.**

7. **IPCA-15 + IPCA by group/sub-index** (food-at-home, industrial goods ex-X, underlying/labor-intensive services).
   Source: IBGE **SIDRA** (IPCA-15 table 7060; IPCA table 7060/1419). Freq monthly. **Difficulty: Med** (SIDRA group navigation).

8. **El Niño / ENSO — Oceanic Niño Index (ONI) + CPC probabilities.**
   Source: **NOAA CPC** (ONI ASCII table; IRI/CPC ENSO probability). Freq monthly. **Difficulty: Low.** Cheap, and directly drives the 2027 inflation scenario.

9. **Brazil oil production (mb/d).**
   Source: **ANP** "Produção de petróleo e gás" (boletim mensal) / EPE. Freq monthly. **Difficulty: Med** (ANP downloads, less API-friendly).

10. **US Core PCE (headline + core, monthly).**
    Source: **BEA** API (NIPA table 2.8.x) — FRED blocked in env, BEA reachable=verify. Freq monthly. **Difficulty: Med.** Fed's primary gauge; ch.1 leans on it.

### Priority — MEDIUM

11. **CAGED net formal job creation** — MTE / Novo CAGED (PDET). Monthly. *Med.*
12. **PMS — Services sector volume** — IBGE SIDRA t.5906. Monthly. *Med.*
13. **Brazil GDP demand-side & sector components (real q/q)** — IBGE SIDRA (Contas Nacionais Trimestrais t.1620/1621). Quarterly. *Med.*
14. **Credit detail: new lending (concessões), avg lending rate, spreads, debt-service ratio** — BCB SGS (debt-service "comprometimento de renda" ~ 29034 **verify**; concessões; ICC). Monthly. *Low–Med.*
15. **FDI monthly + net FDI (FDI−BDI)** — BCB BoP / SGS. Monthly. *Low–Med.*
16. **Terms of trade** — FUNCEX / BCB SGS. Monthly. *Med.*
17. **IPA wholesale (FGV, core industrial)** — FGV (IPA-DI/IPA-M components). Monthly. *Med* (FGV access).
18. **China CPI & PPI (monthly)** — NBS / OECD MEI. Monthly. *Med.*
19. **EZ core HICP + energy HICP + negotiated wages** — Eurostat (prc_hicp_*) + ECB SDW (negotiated wages). Monthly/Quarterly. *Low–Med.*
20. **Fed Funds effective rate** — Fed/FRED (env-blocked) → alt: BEA/BIS policy-rate dataset. Daily/Monthly. *Med.*
21. **Subnational (states) primary balance & cash reserves** — BCB SGS / Tesouro SICONFI. Monthly. *Med.*
22. **NY Fed GSCPI** — NY Fed Excel/CSV. Monthly. *Low.*
23. **CONAB grain production (soy/corn/total)** — CONAB Levantamento de Safras. Seasonal. *Med.*
24. **Petrobras / ANP fuel prices (gasoline, diesel, parity)** — ANP weekly fuel survey. Weekly. *Med.*

### Priority — LOW (nice-to-have, derived, or licensed)

25. **Global long-end yields (UK/GER/ITA/JPN 10y & 30y)** — licensed (Bloomberg) or per-country DMOs. Daily. *High.*
26. **Manufacturing PMIs (EZ + countries, US)** — S&P Global, licensed. Monthly. *High.*
27. **US 5y5y / EUR 5y5y breakevens; breakeven inflation** — FRED (blocked) / market. Daily. *Med–High.*
28. **China activity bundle (retail/IP/FAI, house prices, credit impulse)** — NBS / PBoC. Monthly. *Med–High.*
29. **Brazil DI futures curve / NTN-B real yields / breakevens** — B3 / ANBIMA. Daily. *Med* (ANBIMA has public files) — worth promoting to Med if curve work is prioritized.
30. **Derived/house-only series** (output gap, NAIRU, neutral rate, quasi-fiscal impulse, BRL EM-FX beta, terms-of-trade vol) — compute internally; no external feed.

---

## 4. Notable already-covered strengths

- The Brazil **inflation core** (`IPCA`, `IPCA_12M`, two core measures, INPC, IGP-M, IGP-DI) is well covered.
- The Brazil **monetary anchor** (`SELIC`, `SELIC_TARGET`, `CDI`) and **debt** (`DBGG`, `NET_DEBT`) are present.
- **Activity proxies** (`IBCBR`, `PIM`, `PMC`, `NUCI`, `VEHICLES`, `UNEMP`) cover most of ch.4's monthly dashboard.
- **Commodities** are comprehensive (18 series incl. Brent/WTI/iron ore + all the Brazil ag exports).
- **Market/FX** daily series cover every index and major cross the report charts.
- **World Bank annual** layer gives a consistent G15 cross-section for slow-moving structural comparisons (GDP, debt, CA, FDI, tax, population) — good for context even though the report itself runs at higher frequency.

---

*Caveat on SGS codes:* every BCB SGS number above tagged **(verify)** should be confirmed in the SGS catalog before ingest; the Olinda Focus, Comex Stat, NOAA CPC, NY Fed GSCPI, BEA, Eurostat and IBGE SIDRA endpoints are all publicly documented and were prioritized partly because of that.
