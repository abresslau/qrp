"""Shared price-source contract: the ``PricePoint`` record + the ``PriceSource`` protocol.

A ``PricePoint`` is one daily observation of one commodity's continuous series. The store keys on
``(commodity_code, series_type, as_of_date)``. ``settle`` is the daily settlement proxy (the
vendor's close); OHLC + volume are stored where the source provides them. A ``PriceSource`` fetches
a window of points; ``commodity.ingest.fill_prices`` is commodity-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PricePoint:
    """One daily commodity observation. ``as_of_date`` is the trading date; prices are raw."""

    commodity_code: str
    series_type: str  # 'continuous_front' (v1); future: 'continuous_2nd', dated contracts (Tier B)
    as_of_date: date
    settle: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


@runtime_checkable
class PriceSource(Protocol):
    """A price adapter. ``SOURCE`` tags rows. ``fetch`` returns points in ``[start_date, end_date]``
    (both inclusive; ``None`` = unbounded), any order. Network/parse failures raise — the loader's
    attempt-all driver catches per source so one bad feed never blocks the rest."""

    SOURCE: str

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[PricePoint]: ...
