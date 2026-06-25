"""Source-abstraction contract and per-vendor adapters (yfinance only, today).

Importing this package registers the bundled adapters so they are selectable by
config key via :func:`equity.sources.registry.get_source`. A second vendor (EODHD
was the Story 2.7 candidate) was never implemented — the cross-vendor comparator
(``actions_agree``) is ready for one.
"""

# Import adapters for their self-registration side effect.
from equity.sources import yfinance_adapter as yfinance_adapter  # noqa: E402,F401
from equity.sources.contract import (
    DividendEvent,
    OhlcvBar,
    OhlcvResult,
    OhlcvSource,
    SourceError,
    SplitEvent,
    UnknownSymbolError,
    UnsupportedSourceError,
    actions_agree,
    assert_ohlcv_contract,
    cumulative_split_factor,
)
from equity.sources.registry import (
    UnknownSourceError,
    get_source,
    is_registered,
    register_source,
)

__all__ = [
    "DividendEvent",
    "OhlcvBar",
    "OhlcvResult",
    "OhlcvSource",
    "SourceError",
    "SplitEvent",
    "UnknownSourceError",
    "UnknownSymbolError",
    "UnsupportedSourceError",
    "actions_agree",
    "assert_ohlcv_contract",
    "cumulative_split_factor",
    "get_source",
    "is_registered",
    "register_source",
]
