"""Macro ingest: fetch the configured public series and upsert into the `macro` schema.

Idempotent (observations upserted on (series_id, obs_date)). Sources: World Bank, ECB,
US Treasury FiscalData, OECD, Eurostat — each series source-attributed; a no-data series
is omitted, never faked. Run via ``python -m macro.ingest`` or the gateway's refresh().
"""

from __future__ import annotations

from datetime import date as _date

import psycopg

from macro.db import connect
from macro.market_sources import fetch_yfinance
from macro.sources import (
    fetch_bcb_focus_12m,
    fetch_bcb_focus_annual,
    fetch_bcb_sgs,
    fetch_bls,
    fetch_ecb,
    fetch_eurostat,
    fetch_fiscaldata_avg_rates,
    fetch_fiscaldata_debt,
    fetch_oecd_cpi,
    fetch_sidra,
    fetch_treasury_par_yield,
    fetch_worldbank,
    fetch_worldbank_all,
    worldbank_country_iso3,
)

# Canonical category slugs (lower-case, URL-safe — they appear in console paths and must
# match the `^[a-z]+$` DB CHECK). Every catalog entry declares one; the upsert refuses
# anything else. The console submenu reads the live category set, so a new slug here (once
# a series populates it) appears in the sidebar automatically. The slugs map to the standard
# sell-side macro buckets (activity/inflation/labor/monetary/fx/fiscal/external/credit).
CATEGORIES = (
    "inflation", "rates", "fx", "activity", "gdp", "employment",
    "fiscal", "debt", "external", "money", "trade", "population",
    "commodities", "markets",
)

# Market series via yfinance (commodities + indices) — the cross-asset context a macro desk
# reads alongside the official data (Kinea's energy/commodities spine). (ticker, series_id,
# name, unit, geo, category). A ticker with no data is dropped, never faked.
_MARKET = [
    ("BZ=F", "MKT:BRENT", "Brent crude oil", "USD/bbl", "Global", "commodities"),
    ("CL=F", "MKT:WTI", "WTI crude oil", "USD/bbl", "US", "commodities"),
    ("GC=F", "MKT:GOLD", "Gold", "USD/oz", "Global", "commodities"),
    ("SI=F", "MKT:SILVER", "Silver", "USD/oz", "Global", "commodities"),
    ("PL=F", "MKT:PLATINUM", "Platinum", "USD/oz", "Global", "commodities"),
    ("NG=F", "MKT:NATGAS", "US natural gas (Henry Hub)", "USD/MMBtu", "US", "commodities"),
    ("HO=F", "MKT:HEATOIL", "Heating oil", "USD/gal", "US", "commodities"),
    ("RB=F", "MKT:GASOLINE", "RBOB gasoline", "USD/gal", "US", "commodities"),
    ("HG=F", "MKT:COPPER", "Copper", "USD/lb", "Global", "commodities"),
    ("ALI=F", "MKT:ALUMINIUM", "Aluminium", "USD/tonne", "Global", "commodities"),
    ("PA=F", "MKT:PALLADIUM", "Palladium", "USD/oz", "Global", "commodities"),
    ("TIO=F", "MKT:IRONORE", "Iron ore (62% CFR China)", "USD/tonne", "Global", "commodities"),
    ("ZC=F", "MKT:CORN", "Corn", "USc/bushel", "Global", "commodities"),
    ("ZS=F", "MKT:SOYBEAN", "Soybeans", "USc/bushel", "Global", "commodities"),
    ("ZW=F", "MKT:WHEAT", "Wheat", "USc/bushel", "Global", "commodities"),
    ("KC=F", "MKT:COFFEE", "Coffee (arabica)", "USc/lb", "Global", "commodities"),
    ("SB=F", "MKT:SUGAR", "Sugar", "USc/lb", "Global", "commodities"),
    ("CT=F", "MKT:COTTON", "Cotton", "USc/lb", "Global", "commodities"),
    ("EURUSD=X", "MKT:EURUSD", "EUR / USD", "USD per EUR", "Euro area", "fx"),
    ("JPY=X", "MKT:USDJPY", "USD / JPY", "JPY per USD", "Japan", "fx"),
    ("CNY=X", "MKT:USDCNY", "USD / CNY", "CNY per USD", "China", "fx"),
    ("GBPUSD=X", "MKT:GBPUSD", "GBP / USD", "USD per GBP", "United Kingdom", "fx"),
    ("^BVSP", "MKT:IBOV", "Ibovespa", "index", "Brazil", "markets"),
    ("^GSPC", "MKT:SPX", "S&P 500", "index", "US", "markets"),
    ("^IXIC", "MKT:NASDAQ", "Nasdaq Composite", "index", "US", "markets"),
    ("^STOXX50E", "MKT:STOXX50", "Euro Stoxx 50", "index", "Euro area", "markets"),
    ("^N225", "MKT:NIKKEI", "Nikkei 225", "index", "Japan", "markets"),
    ("^FTSE", "MKT:FTSE", "FTSE 100", "index", "United Kingdom", "markets"),
    ("^MXX", "MKT:MEXBOL", "Mexbol (IPC)", "index", "Mexico", "markets"),
    ("DX-Y.NYB", "MKT:DXY", "US dollar index (DXY)", "index", "US", "markets"),
    ("^VIX", "MKT:VIX", "Volatility index (VIX)", "index", "US", "markets"),
]

# A major-economy panel for the annual World Bank indicators. EXISTING geo codes are kept
# verbatim (US/BRA/EMU/GBR/JPN) so no historical series_id orphans; the rest broaden
# coverage. A country an indicator doesn't cover yields an empty series and is dropped
# (never faked), so a wide panel on a partial indicator is safe.
_WB_GEOS = [
    "US", "CHN", "JPN", "DEU", "IND", "GBR", "FRA", "BRA",
    "CAN", "KOR", "ITA", "ESP", "MEX", "AUS", "EMU",
]

# World Bank annual indicators × the economy panel: (indicator, name, unit, category,
# scale, geos). Levels are stored in labelled units via `scale` (the UST:DEBT trillions
# precedent): population head-counts in millions, nominal GDP in USD trillions.
_WB = [
    ("FP.CPI.TOTL.ZG", "CPI inflation (YoY)", "% per year", "inflation", 1.0, _WB_GEOS),
    ("NY.GDP.MKTP.KD.ZG", "Real GDP growth", "% per year", "gdp", 1.0, _WB_GEOS),
    ("NY.GDP.MKTP.CD", "GDP (nominal)", "USD trillions", "gdp", 1e-12, _WB_GEOS),
    ("NY.GDP.PCAP.CD", "GDP per capita", "current US$", "gdp", 1.0, _WB_GEOS),
    ("FR.INR.RINR", "Real interest rate", "%", "rates", 1.0, _WB_GEOS),
    ("FR.INR.LEND", "Lending interest rate", "%", "rates", 1.0, _WB_GEOS),
    ("SL.UEM.TOTL.ZS", "Unemployment rate", "% of labour force", "employment", 1.0, _WB_GEOS),
    ("GC.DOD.TOTL.GD.ZS", "Central govt debt", "% of GDP", "debt", 1.0, _WB_GEOS),
    # Population (SP.POP.TOTL / SP.POP.GROW) is NOT on the 15-country panel — it gets a
    # dedicated all-countries ingest (ingest_population_all) so the world map shades globally.
    ("BN.CAB.XOKA.GD.ZS", "Current account balance", "% of GDP", "trade", 1.0, _WB_GEOS),
    ("NE.EXP.GNFS.ZS", "Exports of goods & services", "% of GDP", "trade", 1.0, _WB_GEOS),
    ("NE.IMP.GNFS.ZS", "Imports of goods & services", "% of GDP", "trade", 1.0, _WB_GEOS),
    ("FM.LBL.BMNY.ZG", "Broad money growth", "% per year", "money", 1.0, _WB_GEOS),
    ("NY.GDP.DEFL.KD.ZG", "GDP deflator inflation", "% per year", "inflation", 1.0, _WB_GEOS),
    ("GC.XPN.TOTL.GD.ZS", "Government expense", "% of GDP", "fiscal", 1.0, _WB_GEOS),
    ("GC.TAX.TOTL.GD.ZS", "Tax revenue", "% of GDP", "fiscal", 1.0, _WB_GEOS),
    ("NE.GDI.FTOT.ZS", "Gross fixed capital formation", "% of GDP", "activity", 1.0, _WB_GEOS),
    ("SL.TLF.CACT.ZS", "Labour force participation", "% of population 15+", "employment",
     1.0, _WB_GEOS),
    ("BX.KLT.DINV.WD.GD.ZS", "FDI net inflows", "% of GDP", "external", 1.0, _WB_GEOS),
]

# Population indicators ingested for EVERY country (not the 15-panel) so the world map has
# global coverage: (indicator, name, unit, scale).
_WB_POP_ALL = [
    ("SP.POP.TOTL", "Population", "millions", 1e-6),
    ("SP.POP.GROW", "Population growth", "% per year", 1.0),
]

# Focus survey term structure (expectations for a fixed reference year, tracked over time) —
# the monetary-policy anchor a desk lives on. (Olinda indicator, id-prefix, name, unit,
# category). One series per reference year (current..+3) via ingest_focus_annual. An unknown
# indicator string yields an empty series (stored as nothing) — never bad data.
_BCB_FOCUS_ANNUAL = [
    ("IPCA", "IPCA", "IPCA expectation (Focus)", "% per year", "inflation"),
    ("Câmbio", "BRL", "BRL/USD eop expectation (Focus)", "BRL per USD", "fx"),
    ("PIB Total", "PIB", "GDP growth expectation (Focus)", "% per year", "gdp"),
    ("Dívida bruta do governo geral", "GROSSDEBT",
     "Gross general govt debt expectation (Focus)", "% of GDP", "debt"),
    # NOTE: Selic eop expectations live in a separate Olinda endpoint
    # (ExpectativasMercadoSelic) — wire as a follow-up.
]

# ECB Data Portal series: (key, series_id, name, unit, frequency, category). The three
# ECB policy rates (main refinancing, deposit facility, marginal lending) are the standee
# corridor; each is a daily feed the fetcher compresses to change-points.
_ECB = [
    (
        "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
        "ECB:MRR",
        "ECB main refinancing rate",
        "%",
        "daily",
        "rates",
    ),
    (
        "FM/D.U2.EUR.4F.KR.DFR.LEV",
        "ECB:DFR",
        "ECB deposit facility rate",
        "%",
        "daily",
        "rates",
    ),
    (
        "FM/D.U2.EUR.4F.KR.MLFR.LEV",
        "ECB:MLFR",
        "ECB marginal lending rate",
        "%",
        "daily",
        "rates",
    ),
]

# OECD CPI YoY (monthly) per REF_AREA — all category `inflation`. Monthly series chart far
# better than the annual WB CPI, so cover the panel widely. An area the flow doesn't serve
# 404s and is mapped to an empty series (omitted by the no-data rule). ISO-3 codes here
# (the OECD key), distinct from the WB panel's mixed codes.
_OECD_CPI_GEOS = [
    "USA", "GBR", "JPN", "BRA", "DEU", "FRA", "CAN", "KOR", "ITA", "ESP", "AUS", "MEX",
]

# BCB SGS (Banco Central do Brasil) series — the Brazilian macro spine a desk watches, all
# from the central bank's open SGS API (no key). (code, series_id, name, unit, frequency,
# category, scale, compress_steps). Codes verified live against the SGS catalog 2026-06-14.
# Levels are stored in labelled units via `scale` (reserves USD-mn → USD-bn; M3 R$-thousand
# → R$-trillion). Policy/step series compress to change-points.
_BCB = [
    # monetary / rates
    (432, "BCB:SELIC_TARGET", "Selic target rate (Copom)", "% p.a.", "daily",
     "rates", 1.0, True),
    (1178, "BCB:SELIC", "Selic rate (effective, annualized)", "% p.a.", "daily",
     "rates", 1.0, False),
    # inflation
    (433, "BCB:IPCA", "IPCA inflation (monthly)", "%", "monthly", "inflation", 1.0, False),
    (13522, "BCB:IPCA_12M", "IPCA inflation (12-month)", "% per year", "monthly",
     "inflation", 1.0, False),
    (4466, "BCB:IPCA_CORE_TM", "IPCA core (trimmed means)", "%", "monthly",
     "inflation", 1.0, False),
    (11427, "BCB:IPCA_CORE_EX", "IPCA core (exclusion)", "%", "monthly",
     "inflation", 1.0, False),
    (189, "BCB:IGPM", "IGP-M inflation (monthly)", "%", "monthly", "inflation", 1.0, False),
    (188, "BCB:INPC", "INPC inflation (monthly)", "%", "monthly", "inflation", 1.0, False),
    (190, "BCB:IGPDI", "IGP-DI inflation (monthly)", "%", "monthly", "inflation", 1.0, False),
    (4391, "BCB:CDI", "CDI rate (monthly accumulated)", "%", "monthly", "rates", 1.0, False),
    # fx
    (1, "BCB:BRLUSD", "BRL/USD exchange rate (PTAX sell)", "BRL per USD", "daily",
     "fx", 1.0, False),
    # activity
    (24364, "BCB:IBCBR_SA", "IBC-Br economic activity (SA)", "index", "monthly",
     "activity", 1.0, False),
    (24363, "BCB:IBCBR", "IBC-Br economic activity (NSA)", "index", "monthly",
     "activity", 1.0, False),
    (28561, "BCB:NUCI", "Capacity utilisation (NUCI)", "%", "monthly", "activity", 1.0, False),
    (1373, "BCB:VEHICLES", "Vehicle production (ANFAVEA)", "units", "monthly",
     "activity", 1.0, False),
    # fiscal
    (5793, "BCB:PRIMARY_RESULT", "Primary fiscal result (12m)", "% of GDP", "monthly",
     "fiscal", 1.0, False),
    # debt stocks
    (13762, "BCB:DBGG", "Gross general government debt (DBGG)", "% of GDP", "monthly",
     "debt", 1.0, False),
    (4513, "BCB:NET_DEBT", "Net public sector debt", "% of GDP", "monthly",
     "debt", 1.0, False),
    # external
    (22701, "BCB:CURRENT_ACCOUNT", "Current account balance (monthly)", "USD million",
     "monthly", "external", 1.0, False),
    (13621, "BCB:RESERVES", "International reserves", "USD billion", "daily",
     "external", 1e-3, False),
    # trade (SECEX/MDIC, republished via BCB SGS; monthly USD-mn — balance = exports − imports.
    # NB the earlier-probed 22704/22705 were the WRONG codes [magnitudes didn't reconcile];
    # 22707/22708/22709 reconcile exactly, verified live 2026-07-01 to May-2026.)
    (22707, "BCB:TRADE_BALANCE", "Trade balance (goods, FOB)", "USD million", "monthly",
     "trade", 1.0, False),
    (22708, "BCB:EXPORTS", "Exports (goods, FOB)", "USD million", "monthly",
     "trade", 1.0, False),
    (22709, "BCB:IMPORTS", "Imports (goods, FOB)", "USD million", "monthly",
     "trade", 1.0, False),
    # employment (Novo CAGED, formal-employment STOCK; its month-over-month change is the widely
    # watched net formal-job creation. Verified live 2026-07-01 to Apr-2026.)
    (28763, "BCB:CAGED_STOCK", "Formal employment (Novo CAGED, stock)", "jobs", "monthly",
     "employment", 1.0, False),
    # money / credit
    (27813, "BCB:M3", "Broad money M3 (end of period)", "R$ trillion", "monthly",
     "money", 1e-9, False),
    (20622, "BCB:CREDIT_GDP", "Credit outstanding to GDP", "% of GDP", "monthly",
     "money", 1.0, False),
    (21082, "BCB:DEFAULT_RATE", "Credit default rate (inadimplência)", "%", "monthly",
     "money", 1.0, False),
    (29037, "BCB:HH_DEBT", "Household debt to income", "%", "monthly", "money", 1.0, False),
]

# IBGE SIDRA series (Brazilian official statistics, no key). (table, variable, series_id,
# name, unit, frequency, category, classifications, scale). IBGE owns the data BCB doesn't:
# the PNAD-Contínua unemployment rate (labor) and quarterly PIB (GDP), plus the IPCA index
# level / YTD that complement BCB's monthly %. Codes verified live 2026-06-14.
_IBGE = [
    (1737, 2266, "IBGE:IPCA_INDEX", "IPCA index level", "index", "monthly",
     "inflation", None, 1.0),
    (1737, 63, "IBGE:IPCA_MOM", "IPCA inflation (monthly)", "%", "monthly",
     "inflation", None, 1.0),
    (1737, 2265, "IBGE:IPCA_12M", "IPCA inflation (12-month)", "%", "monthly",
     "inflation", None, 1.0),
    (1737, 69, "IBGE:IPCA_YTD", "IPCA inflation (year to date)", "%", "monthly",
     "inflation", None, 1.0),
    (1736, 44, "IBGE:INPC_MOM", "INPC inflation (monthly)", "%", "monthly",
     "inflation", None, 1.0),
    (1736, 2292, "IBGE:INPC_12M", "INPC inflation (12-month)", "%", "monthly",
     "inflation", None, 1.0),
    (6381, 4099, "IBGE:UNEMP", "Unemployment rate (PNAD Contínua)", "%", "monthly",
     "employment", None, 1.0),
    (1846, 585, "IBGE:PIB", "GDP (PIB, nominal, quarterly)", "R$ trillion", "quarterly",
     "gdp", [(11255, 90707)], 1e-6),
    (8888, 12607, "IBGE:PIM", "Industrial production (PIM, SA)", "index", "monthly",
     "activity", [(544, 129314)], 1.0),
    (8880, 7170, "IBGE:PMC", "Retail sales volume (PMC, SA)", "index", "monthly",
     "activity", [(11046, 56734)], 1.0),
    # PIM/PMC growth rates — the prints a desk actually reads, alongside the index levels above
    # (same table + classification: PIM c544/129314 "Indústria geral", PMC c11046/56734 "volume").
    # Verified live 2026-07-01 to Apr-2026.
    (8888, 11601, "IBGE:PIM_MOM", "Industrial production MoM (PIM-PF, SA)", "%", "monthly",
     "activity", [(544, 129314)], 1.0),
    (8888, 11602, "IBGE:PIM_YOY", "Industrial production YoY (PIM-PF)", "%", "monthly",
     "activity", [(544, 129314)], 1.0),
    (8880, 11708, "IBGE:PMC_MOM", "Retail sales volume MoM (PMC, SA)", "%", "monthly",
     "activity", [(11046, 56734)], 1.0),
    (8880, 11709, "IBGE:PMC_YOY", "Retail sales volume YoY (PMC)", "%", "monthly",
     "activity", [(11046, 56734)], 1.0),
]

# US BLS series (no key; FRED-free US coverage). (bls_series, series_id, name, unit, category).
_BLS = [
    ("CUUR0000SA0", "BLS:CPI", "US CPI (index, NSA)", "index", "inflation"),
    ("LNS14000000", "BLS:UNRATE", "US unemployment rate", "%", "employment"),
    ("CES0000000001", "BLS:PAYROLLS", "US nonfarm payrolls", "thousands", "employment"),
]

# Eurostat datasets, every non-time dimension pinned (the fetcher asserts the shape):
# (code, filters, series_id, name, unit, category).
# une_rt_m serves no euro-area aggregate (EA/EA19/EA20 all empty, probed 2026-06-11) —
# EU27_2020 is the configured aggregate instead.
_EUROSTAT = [
    (
        "prc_hicp_manr",
        {"geo": "EA", "coicop": "CP00", "unit": "RCH_A"},
        "EU:HICP:EA",
        "HICP inflation (YoY, monthly)",
        "% per year",
        "inflation",
    ),
    (
        "une_rt_m",
        {"geo": "EU27_2020", "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        "EU:UNEMP:EU27",
        "Unemployment rate (monthly)",
        "% of labour force",
        "employment",
    ),
]


def _upsert(conn: psycopg.Connection, meta: dict, obs: list) -> tuple[int, int]:
    """Upsert one series + observations; returns ``(n_obs, n_restated)``.

    ``n_obs`` counts the observations processed (present after the call); ``n_restated``
    counts ONLY existing rows whose value actually changed — those get a fresh
    ``last_changed_at``; equal-value re-ingests leave the row untouched.

    Same-date duplicates within one fetch are collapsed FIRST (last wins, post-sort) —
    otherwise the second row would hit ON CONFLICT against its own sibling and count as
    a vendor restatement that never happened.
    """
    if meta.get("category") not in CATEGORIES:  # loud config error, attributed per-series
        raise ValueError(f"{meta.get('series_id')}: category {meta.get('category')!r} "
                         f"not in canonical set {CATEGORIES}")
    if not obs:
        return 0, 0  # never store an empty series (honest: a no-data series is omitted, not faked)
    obs = list(dict(obs).items())  # collapse same-date duplicates (dict keyed by date)
    conn.execute(
        """
        INSERT INTO macro.series (series_id, source, name, geo, unit, frequency, category,
                                  updated_at)
        VALUES (%(series_id)s, %(source)s, %(name)s, %(geo)s, %(unit)s, %(frequency)s,
                %(category)s, now())
        ON CONFLICT (series_id) DO UPDATE SET
            name = EXCLUDED.name, geo = EXCLUDED.geo, unit = EXCLUDED.unit,
            frequency = EXCLUDED.frequency, category = EXCLUDED.category, updated_at = now()
        """,
        meta,
    )
    n = restated = 0
    for d, v in obs:
        cur = conn.execute(
            """
            INSERT INTO macro.observation AS o (series_id, obs_date, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (series_id, obs_date) DO UPDATE
                SET value = EXCLUDED.value, last_changed_at = now()
                WHERE o.value IS DISTINCT FROM EXCLUDED.value
            RETURNING (xmax <> 0) AS was_update
            """,
            (meta["series_id"], d, v),
        )
        row = cur.fetchone()
        # row is None when the conflict row was identical (DO UPDATE's WHERE filtered it
        # out — nothing written); (True,) when an existing value was changed (restatement).
        if row is not None and row[0]:
            restated += 1
        n += 1
    return n, restated


def ingest_population_all(conn: psycopg.Connection) -> list[dict]:
    """Ingest population (head-count + growth) for EVERY World Bank economy so the population
    world map shades globally — not just the 15-country panel. Purges any prior WB:SP.POP.*
    rows first (the old panel used mixed ISO-2/ISO-3 codes; the all-countries path is ISO-3
    only), then upserts one series per country. Aggregates (regions/income groups) are
    excluded. Returns the per-series summary rows."""
    conn.autocommit = True
    out: list[dict] = []
    # Replace the prior population panel wholesale (avoids US/USA-style duplicate codes).
    conn.execute("DELETE FROM macro.observation WHERE series_id LIKE 'WB:SP.POP.%%'")
    conn.execute("DELETE FROM macro.series WHERE series_id LIKE 'WB:SP.POP.%%'")
    try:
        keep = worldbank_country_iso3()
    except Exception:  # noqa: BLE001 — fall back to ISO-3-present filter if the catalog fails
        keep = None
    for indicator, name, unit, scale in _WB_POP_ALL:
        try:
            series = fetch_worldbank_all(indicator, name, unit, scale=scale, keep_iso3=keep)
        except Exception as exc:  # noqa: BLE001
            out.append({"series_id": f"WB:{indicator}:ALL", "obs": 0, "restated": 0,
                        "ok": False, "error": str(exc)[:160]})
            continue
        for meta, obs in series:
            try:
                n, restated = _upsert(conn, dict(meta, category="population"), obs)
                out.append({"series_id": meta["series_id"], "obs": n,
                            "restated": restated, "ok": True})
            except Exception as exc:  # noqa: BLE001
                out.append({"series_id": meta["series_id"], "obs": 0, "restated": 0,
                            "ok": False, "error": str(exc)[:160]})
    return out


def ingest_focus_annual(conn: psycopg.Connection) -> list[dict]:
    """Ingest the Focus survey annual term structure: one series per (indicator, reference
    year) for the current + next three years. Returns the per-series summary rows."""
    conn.autocommit = True
    out: list[dict] = []
    y0 = _date.today().year
    for indicator, prefix, name, unit, category in _BCB_FOCUS_ANNUAL:
        for y in range(y0, y0 + 4):
            sid = f"BCB:FOCUS:{prefix}:{y}"
            try:
                meta, obs = fetch_bcb_focus_annual(indicator, sid, f"{name} ({y})", unit, y)
                n, restated = _upsert(conn, dict(meta, category=category), obs)
                out.append({"series_id": sid, "obs": n, "restated": restated, "ok": True})
            except Exception as exc:  # noqa: BLE001
                out.append({"series_id": sid, "obs": 0, "restated": 0, "ok": False,
                            "error": str(exc)[:160]})
    return out


def run_ingest(conn: psycopg.Connection) -> dict:
    """Fetch + upsert all configured series. Returns a per-series summary (never fabricates)."""
    conn.autocommit = True
    summary: list[dict] = []

    def _record(series_id: str, fetched: tuple[dict, list], category: str) -> None:
        meta, obs = fetched
        n, restated = _upsert(conn, dict(meta, category=category), obs)
        summary.append({"series_id": series_id, "obs": n, "restated": restated, "ok": True})

    def _failed(series_id: str, exc: Exception) -> None:
        summary.append(
            {"series_id": series_id, "obs": 0, "restated": 0, "ok": False,
             "error": str(exc)[:160]}
        )

    for indicator, name, unit, category, scale, geos in _WB:
        # One fetch per geo so a single failing country doesn't skip the indicator's
        # remaining geos (and the failure is attributed to the right series).
        for geo in geos:
            try:
                for meta, obs in fetch_worldbank(indicator, name, unit, [geo], scale=scale):
                    _record(meta["series_id"], (meta, obs), category)
            except Exception as exc:  # noqa: BLE001
                _failed(f"WB:{indicator}:{geo}", exc)
    summary.extend(ingest_population_all(conn))  # population for every country (world map)
    summary.extend(ingest_focus_annual(conn))  # Focus survey annual term structure
    for key, sid, name, unit, freq, category in _ECB:
        try:
            _record(sid, fetch_ecb(key, sid, name, unit, freq), category)
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    try:
        _record("UST:DEBT", fetch_fiscaldata_debt(), "debt")
    except Exception as exc:  # noqa: BLE001
        _failed("UST:DEBT", exc)
    # US Treasury par yield curve (2Y/10Y) — the 2s10s a macro desk lives on. ONE shared
    # per-year HTTP walk feeds both tenors; the wildcard id catches a fetch failure, and
    # upsert failures are attributed per tenor below.
    try:
        par_yield_series = fetch_treasury_par_yield()
    except Exception as exc:  # noqa: BLE001
        _failed("UST:PAR_YIELD:*", exc)
    else:
        for meta, obs in par_yield_series:
            try:
                _record(meta["series_id"], (meta, obs), "rates")
            except Exception as exc:  # noqa: BLE001
                _failed(meta["series_id"], exc)
    try:
        rate_series = fetch_fiscaldata_avg_rates()
    except Exception as exc:  # noqa: BLE001
        # ONE fetch serves all three series — only the shared HTTP call gets the
        # wildcard id; upsert failures are attributed per series below.
        _failed("UST:AVG_RATE:*", exc)
    else:
        for meta, obs in rate_series:
            try:
                _record(meta["series_id"], (meta, obs), "rates")
            except Exception as exc:  # noqa: BLE001
                _failed(meta["series_id"], exc)
    for geo in _OECD_CPI_GEOS:
        try:
            _record(f"OECD:CPI:{geo}", fetch_oecd_cpi(geo), "inflation")
        except Exception as exc:  # noqa: BLE001
            _failed(f"OECD:CPI:{geo}", exc)
    for code, filters, sid, name, unit, category in _EUROSTAT:
        try:
            _record(sid, fetch_eurostat(code, filters, sid, name, unit), category)
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    for code, sid, name, unit, freq, category, scale, compress in _BCB:
        try:
            _record(
                sid,
                fetch_bcb_sgs(code, sid, name, unit, freq, scale=scale, compress_steps=compress),
                category,
            )
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    for table, var, sid, name, unit, freq, category, cls, scale in _IBGE:
        try:
            _record(
                sid,
                fetch_sidra(table, var, sid, name, unit, frequency=freq,
                            classifications=cls, scale=scale),
                category,
            )
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    for ticker, sid, name, unit, geo, category in _MARKET:
        try:
            _record(sid, fetch_yfinance(ticker, sid, name, unit, geo), category)
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    for bls_series, sid, name, unit, category in _BLS:
        try:
            _record(sid, fetch_bls(bls_series, sid, name, unit), category)
        except Exception as exc:  # noqa: BLE001
            _failed(sid, exc)
    # BCB Focus survey: market inflation expectations (the anchor Kinea tracks vs realised).
    try:
        _record(
            "BCB:FOCUS_IPCA_12M",
            fetch_bcb_focus_12m(
                "IPCA", "BCB:FOCUS_IPCA_12M",
                "IPCA inflation expectation (12m ahead, Focus)", "% per year",
            ),
            "inflation",
        )
    except Exception as exc:  # noqa: BLE001
        _failed("BCB:FOCUS_IPCA_12M", exc)

    # Drop any catalog rows left without observations (e.g. a source with no data for a geo).
    conn.execute(
        "DELETE FROM macro.series s "
        "WHERE NOT EXISTS (SELECT 1 FROM macro.observation o WHERE o.series_id = s.series_id)"
    )
    return {
        "series": summary,
        "total_obs": sum(s["obs"] for s in summary),
        "total_restated": sum(s["restated"] for s in summary),
    }


if __name__ == "__main__":
    conn = connect()  # macro owns its own database (DSN resolved by macro.config)
    try:
        result = run_ingest(conn)
        for s in result["series"]:
            print(s)
        print("total observations:", result["total_obs"], "| restated:", result["total_restated"])
    finally:
        conn.close()
