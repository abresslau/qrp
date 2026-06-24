"""The canonical commodity universe — the controlled vocabulary + per-commodity metadata.

Identity is an in-house `commodity_code` (no free universal symbology for commodities — the same
decision as sym's `sym_id`). Each entry carries its `sector`, the canonical `exchange` (one liquid
venue per commodity for v1), display `unit` + `currency`, and the Yahoo continuous front-month
ticker (`yahoo`) the v1 source pulls. `unit` is a DISPLAY label — v1 stores each commodity's raw
vendor series with no cross-commodity arithmetic, so a cosmetic unit label never corrupts a price.

Sectors (display order): energy, precious_metals, base_metals, grains, softs, livestock.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Commodity:
    code: str          # canonical internal code (PK across the package)
    name: str          # display name
    sector: str        # energy | precious_metals | base_metals | grains | softs | livestock
    exchange: str      # canonical venue (NYMEX/ICE/COMEX/CBOT/CME…)
    currency: str      # quote currency (USD for the v1 universe)
    unit: str          # display unit label (USD/bbl, USD/troy oz, USc/lb, …)
    yahoo: str         # Yahoo Finance continuous front-month ticker


# Sector display order + human label.
SECTORS: list[tuple[str, str]] = [
    ("energy", "Energy"),
    ("precious_metals", "Precious Metals"),
    ("base_metals", "Base Metals"),
    ("grains", "Grains & Oilseeds"),
    ("softs", "Softs"),
    ("livestock", "Livestock"),
]
SECTOR_LABEL = dict(SECTORS)

UNIVERSE: list[Commodity] = [
    # --- energy ---
    Commodity("WTI", "WTI Crude Oil", "energy", "NYMEX", "USD", "USD/bbl", "CL=F"),
    Commodity("BRENT", "Brent Crude Oil", "energy", "ICE", "USD", "USD/bbl", "BZ=F"),
    Commodity("NATGAS", "Natural Gas (Henry Hub)", "energy", "NYMEX", "USD", "USD/MMBtu", "NG=F"),
    Commodity("RBOB", "RBOB Gasoline", "energy", "NYMEX", "USD", "USD/gal", "RB=F"),
    Commodity("HEATOIL", "Heating Oil (ULSD)", "energy", "NYMEX", "USD", "USD/gal", "HO=F"),
    # --- precious metals ---
    Commodity("GOLD", "Gold", "precious_metals", "COMEX", "USD", "USD/troy oz", "GC=F"),
    Commodity("SILVER", "Silver", "precious_metals", "COMEX", "USD", "USD/troy oz", "SI=F"),
    Commodity("PLATINUM", "Platinum", "precious_metals", "NYMEX", "USD", "USD/troy oz", "PL=F"),
    Commodity("PALLADIUM", "Palladium", "precious_metals", "NYMEX", "USD", "USD/troy oz", "PA=F"),
    # --- base metals ---
    Commodity("COPPER", "Copper", "base_metals", "COMEX", "USD", "USD/lb", "HG=F"),
    # --- grains & oilseeds ---
    Commodity("CORN", "Corn", "grains", "CBOT", "USD", "USc/bushel", "ZC=F"),
    Commodity("WHEAT", "Wheat (SRW)", "grains", "CBOT", "USD", "USc/bushel", "ZW=F"),
    Commodity("SOYBEAN", "Soybeans", "grains", "CBOT", "USD", "USc/bushel", "ZS=F"),
    Commodity("SOYOIL", "Soybean Oil", "grains", "CBOT", "USD", "USc/lb", "ZL=F"),
    Commodity("SOYMEAL", "Soybean Meal", "grains", "CBOT", "USD", "USD/short ton", "ZM=F"),
    # --- softs ---
    Commodity("SUGAR", "Sugar No.11", "softs", "ICE", "USD", "USc/lb", "SB=F"),
    Commodity("COFFEE", "Coffee (Arabica)", "softs", "ICE", "USD", "USc/lb", "KC=F"),
    Commodity("COCOA", "Cocoa", "softs", "ICE", "USD", "USD/metric ton", "CC=F"),
    Commodity("COTTON", "Cotton", "softs", "ICE", "USD", "USc/lb", "CT=F"),
    # --- livestock ---
    Commodity("LIVECATTLE", "Live Cattle", "livestock", "CME", "USD", "USc/lb", "LE=F"),
    Commodity("FEEDERCATTLE", "Feeder Cattle", "livestock", "CME", "USD", "USc/lb", "GF=F"),
    Commodity("LEANHOGS", "Lean Hogs", "livestock", "CME", "USD", "USc/lb", "HE=F"),
]

BY_CODE: dict[str, Commodity] = {c.code: c for c in UNIVERSE}


def sector_rank(sector: str) -> int:
    keys = [s for s, _ in SECTORS]
    return keys.index(sector) if sector in keys else len(keys)
