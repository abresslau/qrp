"""Config-keyed adapter registry (Story 2.2, AR-5).

A source is selected by a config *key* (``SYM_SOURCE``), not by importing a
specific adapter — so swapping vendors is a config flip, and the ingestion layer
never names a concrete adapter. Adapters self-register at import; a source that
cannot satisfy the contract (adjusted-only, no raw + explicit factors) is marked
``adjusted_only`` and raises :class:`UnsupportedSourceError` when selected.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from equity.sources.contract import OhlcvSource, SourceError, UnsupportedSourceError


class UnknownSourceError(SourceError):
    """A source key with no registered adapter."""


_REGISTRY: dict[str, tuple[Callable[..., OhlcvSource], bool]] = {}


def register_source(
    key: str, factory: Callable[..., OhlcvSource], *, adjusted_only: bool = False
) -> None:
    """Register an adapter ``factory`` under ``key``.

    ``adjusted_only=True`` marks a source that only exposes adjusted prices (no
    raw + explicit factors); selecting it raises :class:`UnsupportedSourceError`.
    """
    _REGISTRY[key] = (factory, adjusted_only)


def is_registered(key: str) -> bool:
    return key in _REGISTRY


def get_source(key: str, **kwargs: Any) -> OhlcvSource:
    """Construct the adapter registered under ``key``.

    Raises :class:`UnknownSourceError` for an unregistered key and
    :class:`UnsupportedSourceError` for an adjusted-only source.
    """
    if key not in _REGISTRY:
        raise UnknownSourceError(f"no source adapter registered for {key!r}")
    factory, adjusted_only = _REGISTRY[key]
    if adjusted_only:
        raise UnsupportedSourceError(
            f"source {key!r} is adjusted-only; sym requires raw OHLCV + explicit factors"
        )
    return factory(**kwargs)
