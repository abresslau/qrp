"""Country → source registry for the multi-country curve load.

Maps each FX-matrix country (euro area fanned out by member) to the adapter that pulls it, from the
respective central bank / official statistics API where reachable. GB stays on its own dedicated
``rates curve load`` path (the BoE archive is a different, much heavier fetch); the registry covers
everything else. ``EU`` is the euro-area aggregate (ECB AAA spot curve); ``FR``/``IT``/``ES`` are
the ECB long-term (10y) convergence rate (the only directly-published national series — see
PULL_REPORT.md). Blocked/needs-auth sources (DK, MX, CN) are intentionally absent.
"""

from __future__ import annotations

from .base import CurveSource
from .boc import BocCurveSource
from .bundesbank import BundesbankCurveSource
from .ecb import EcbLongTermRateSource, EcbYieldCurveSource
from .hkma import HkmaCurveSource
from .mof_jp import MofJgbCurveSource
from .norgesbank import NorgesBankCurveSource
from .rba import RbaCurveSource
from .rbnz import RbnzCurveSource
from .riksbank import RiksbankCurveSource
from .snb import SnbCurveSource
from .tesouro import TesouroCurveSource
from .ustreasury import UsTreasuryCurveSource


def build_registry() -> dict[str, CurveSource]:
    """Fresh source instances keyed by ISO-3166 alpha-2 (insertion order = load order)."""
    return {
        "DE": BundesbankCurveSource(),     # most important euro member first
        "EU": EcbYieldCurveSource(),       # euro-area aggregate (full Svensson spot curve)
        "FR": EcbLongTermRateSource("FR"),
        "IT": EcbLongTermRateSource("IT"),
        "ES": EcbLongTermRateSource("ES"),
        "US": UsTreasuryCurveSource(),
        "JP": MofJgbCurveSource(),
        "CH": SnbCurveSource(),
        "CA": BocCurveSource(),
        "AU": RbaCurveSource(),
        "NZ": RbnzCurveSource(),
        "SE": RiksbankCurveSource(),
        "NO": NorgesBankCurveSource(),
        "HK": HkmaCurveSource(),
        "BR": TesouroCurveSource(),
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
