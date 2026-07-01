"""Country → source registry for the multi-country curve load.

Maps each FX-matrix country (euro area fanned out by member) to the adapter that pulls it, from the
respective central bank / official statistics API where reachable. GB stays on its own dedicated
``rates curve load`` path (the BoE archive is a different, much heavier fetch); the registry covers
everything else. ``EU`` is the euro-area aggregate (ECB AAA spot curve); ``IT`` uses the ECB
long-term (10y) convergence rate; ``FR`` uses the AFT daily TEC-10 (nominal 10y) + OAT€i (real);
``ES`` the BdE daily curve; ``HK`` the HKMA daily EFBN indicative curve. Blocked/needs-auth sources
(DK, MX, CN) are intentionally absent.
"""

from __future__ import annotations

from .aft_fr import AftOateiCurveSource
from .aft_tec10 import AftTec10CurveSource
from .anbima import AnbimaNtnbCurveSource
from .banco_espana import BancoEspanaCurveSource
from .base import CurveSource
from .boc import BocCurveSource
from .bundesbank import BundesbankCurveSource
from .ecb import EcbLongTermRateSource, EcbYieldCurveSource
from .fed_gsw import FedGswCurveSource
from .hkma import HkmaCurveSource
from .mof_jp import MofJgbCurveSource
from .norgesbank import NorgesBankCurveSource
from .oecd_ltir import OecdLtirCurveSource
from .rba import RbaCurveSource
from .rbnz import RbnzCurveSource
from .riksbank import RiksbankCurveSource
from .snb import SnbCurveSource
from .tesouro import TesouroCurveSource
from .ustreasury import UsTreasuryCurveSource


def build_registry() -> dict[str, list[CurveSource]]:
    """Fresh source instances keyed by ISO-3166 alpha-2 (insertion order = load order). A country
    may have MORE THAN ONE source — the US carries both the official Treasury CMT par curve and the
    Fed GSW fitted nominal/real/inflation curves, each tagged with its own ``source`` provenance."""
    return {
        "DE": [BundesbankCurveSource()],   # most important euro member first
        "EU": [EcbYieldCurveSource()],     # euro-area aggregate (full Svensson spot curve)
        # AFT TEC-10 nominal 10y (DAILY, supersedes the ECB Maastricht 10y monthly) + AFT OAT€i
        # 10y real/breakeven (monthly file). Both accrue history forward (latest-day-only feeds).
        "FR": [AftTec10CurveSource(), AftOateiCurveSource()],
        "IT": [EcbLongTermRateSource("IT")],
        "ES": [BancoEspanaCurveSource()],  # BdE daily curve (0.5–15y) — supersedes ECB 10y monthly
        "US": [UsTreasuryCurveSource(), FedGswCurveSource()],  # CMT par + Fed GSW fitted curves
        "JP": [MofJgbCurveSource()],
        # SNB spot curve (frozen: discontinued 2025-07-31) + OECD monthly 10y yield top-up (fresh)
        "CH": [SnbCurveSource(), OecdLtirCurveSource(country="CH", geo="CHE", currency="CHF")],
        "CA": [BocCurveSource()],
        "AU": [RbaCurveSource()],
        "NZ": [RbnzCurveSource()],
        "SE": [RiksbankCurveSource()],
        "NO": [NorgesBankCurveSource()],
        "HK": [HkmaCurveSource()],
        # Tesouro Direto retail per-issue curve (govt) + ANBIMA authoritative NTN-B real reference
        "BR": [TesouroCurveSource(), AnbimaNtnbCurveSource()],
    }


# Display metadata for the console country switcher (label + currency + region grouping).
COUNTRY_META: dict[str, dict[str, str]] = {
    "GB": {"label": "United Kingdom", "currency": "GBP", "region": "Europe"},
    "DE": {"label": "Germany", "currency": "EUR", "region": "Euro area"},
    "EU": {"label": "Euro area (AAA)", "currency": "EUR", "region": "Euro area"},
    "FR": {"label": "France", "currency": "EUR", "region": "Euro area"},
    "IT": {"label": "Italy", "currency": "EUR", "region": "Euro area"},
    "ES": {"label": "Spain", "currency": "EUR", "region": "Euro area"},
    "US": {"label": "United States", "currency": "USD", "region": "Americas"},
    "JP": {"label": "Japan", "currency": "JPY", "region": "Asia-Pacific"},
    "CH": {"label": "Switzerland", "currency": "CHF", "region": "Europe"},
    "CA": {"label": "Canada", "currency": "CAD", "region": "Americas"},
    "AU": {"label": "Australia", "currency": "AUD", "region": "Asia-Pacific"},
    "NZ": {"label": "New Zealand", "currency": "NZD", "region": "Asia-Pacific"},
    "SE": {"label": "Sweden", "currency": "SEK", "region": "Europe"},
    "NO": {"label": "Norway", "currency": "NOK", "region": "Europe"},
    "HK": {"label": "Hong Kong", "currency": "HKD", "region": "Asia-Pacific"},
    "BR": {"label": "Brazil", "currency": "BRL", "region": "Americas"},
}
