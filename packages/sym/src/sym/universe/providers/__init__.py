"""Concrete universe providers (Epic U1+).

Importing this package registers the built-in providers (so a `get_provider(kind)`
resolves after import). Story U1.7 ships the custom-list provider; Epic U2 adds the
index provider (orchestrating the FMP / ETF / Wikipedia archetype sources).
"""

from __future__ import annotations

from sym.universe.providers import (
    criteria,  # noqa: F401  (self-registers)
    custom_list,  # noqa: F401  (self-registers)
    index_provider,  # noqa: F401  (self-registers + sources)
)
