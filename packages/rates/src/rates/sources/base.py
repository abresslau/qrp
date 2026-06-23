"""Shared curve-source contract: the ``CurvePoint`` record + the ``CurveSource`` protocol.

A ``CurvePoint`` is one published node of one country's yield curve. The store is keyed on
``(country, curve_set, basis, rate_type, tenor, as_of_date)`` — the BoE-era key plus ``country`` so
the euro area can fan out by member (DE/FR/IT/ES/…). ``currency`` is a grouping/label attribute
(DE→EUR, GB→GBP). A ``CurveSource`` knows its own country/currency and fetches a window of points;
``rates.ingest.fill_curve`` is country-agnostic and reads ``country``/``currency`` off each point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CurvePoint:
    """One published curve node. ``value`` is % per annum; ``as_of_date`` is the curve's date.

    ``country`` is ISO-3166 alpha-2 (GB/DE/US/…); ``currency`` is ISO-4217 (GBP/EUR/…).
    ``curve_set`` is the curve family (UK: ``glc``/``ois``; most others: ``govt``; swaps: ``irs``),
    ``basis`` is ``nominal``/``real``/``inflation``, ``rate_type`` is ``spot``/``forward``/``par``/
    ``yield`` (most central banks publish par or market ``yield``, not a fitted ``spot``).
    """

    country: str
    currency: str
    curve_set: str
    basis: str
    rate_type: str
    tenor: float
    as_of_date: date
    value: float


@runtime_checkable
class CurveSource(Protocol):
    """A per-country adapter. ``SOURCE`` tags rows; ``COUNTRY``/``CURRENCY`` identify the issuer.

    ``fetch`` returns every point in ``[start_date, end_date]`` (both inclusive; ``None`` =
    unbounded) for this source's single country, in any order. Network/parse failures raise — the
    loader's attempt-all driver catches per source so one bad feed never blocks the rest.
    """

    SOURCE: str
    COUNTRY: str
    CURRENCY: str

    def fetch(
        self, *, start_date: date | None = None, end_date: date | None = None
    ) -> list[CurvePoint]: ...
