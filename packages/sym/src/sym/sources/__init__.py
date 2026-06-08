"""Source-abstraction contract and per-vendor adapters (yfinance, EODHD).

Importing this package registers the bundled adapters so they are selectable by
config key via :func:`sym.sources.registry.get_source`.
"""

# Import adapters for their self-registration side effect.
from sym.sources import yfinance_adapter as yfinance_adapter  # noqa: E402,F401
from sym.sources.contract import (
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
from sym.sources.registry import (
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
