"""The source-abstraction contract: one boundary all price ingestion goes through (Story 2.2).

Every vendor adapter implements :class:`OhlcvSource` (``fetch_ohlcv``) and returns an
:class:`OhlcvResult` carrying RAW OHLCV plus *explicit* corporate-action records
(splits, dividends). There is deliberately no adjusted-close field and no code path
that derives a factor from a price ratio — the HARD RULE (AR-6): corporate-action
factors come ONLY from explicit action records. The factor helpers here take
``splits``/``dividends``, never prices, which is what makes that rule structural.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class SourceError(RuntimeError):
    """Base class for source-adapter failures."""


class UnsupportedSourceError(SourceError):
    """The configured source cannot satisfy the contract (e.g. adjusted-only)."""


class UnknownSymbolError(SourceError):
    """No vendor symbol could be resolved for a CompositeFIGI."""


@dataclass(frozen=True)
class OhlcvBar:
    """One raw (unadjusted) daily bar. Currency is carried once on the result."""

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class SplitEvent:
    """A stock split on its ex-date. ``ratio`` is new-for-old (4.0 = a 4:1 split)."""

    ex_date: date
    ratio: Decimal


@dataclass(frozen=True)
class DividendEvent:
    """A cash dividend on its ex-date, per share, in the result's currency."""

    ex_date: date
    amount: Decimal


@dataclass(frozen=True)
class OhlcvResult:
    """Raw OHLCV + explicit corporate actions for one security from one vendor.

    ``splits``/``dividends`` default to ``[]`` (never None) so "no actions" is
    unambiguous. There is no adjusted-close field by design (AR-6/AR-7).
    """

    figi: str
    currency: str
    bars: list[OhlcvBar]
    source: str
    retrieved_at: datetime
    splits: list[SplitEvent] = field(default_factory=list)
    dividends: list[DividendEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.bars is None or self.splits is None or self.dividends is None:
            raise ValueError("bars/splits/dividends must be lists, not None")


class OhlcvSource(Protocol):
    """A vendor adapter resolving a CompositeFIGI to raw OHLCV + explicit actions."""

    def fetch_ohlcv(self, figi: str, start: date, end: date) -> OhlcvResult: ...


def cumulative_split_factor(splits: Sequence[SplitEvent], as_of_date: date) -> Decimal:
    """Back-adjustment split factor for ``as_of_date``: product of ratios with a later ex-date.

    Derived ONLY from explicit split records (HARD RULE) — it takes no prices.
    A price on ``as_of_date`` is split-adjusted by dividing by this factor.
    """
    factor = Decimal(1)
    for split in splits:
        if split.ex_date > as_of_date:
            factor *= split.ratio
    return factor


def _dividend_tolerance(amount: Decimal) -> Decimal:
    """Per-AC dividend match tolerance: max(0.5% of the amount, $0.005)."""
    return max(abs(amount) * Decimal("0.005"), Decimal("0.005"))


def actions_agree(left: OhlcvResult, right: OhlcvResult) -> bool:
    """Whether two vendors' corporate actions agree for the same name (AC #4).

    Splits must match exactly (ex-date and ratio); dividends must share ex-dates
    exactly and agree on amount within max(0.5%, $0.005). The tolerance is taken
    from the LARGER amount so the comparison is commutative.
    """
    if {(s.ex_date, s.ratio) for s in left.splits} != {(s.ex_date, s.ratio) for s in right.splits}:
        return False
    left_div = {d.ex_date: d.amount for d in left.dividends}
    right_div = {d.ex_date: d.amount for d in right.dividends}
    if left_div.keys() != right_div.keys():
        return False
    return all(
        abs(left_div[ex] - right_div[ex])
        <= _dividend_tolerance(max(left_div[ex], right_div[ex], key=abs))
        for ex in left_div
    )


class ContractViolation(SourceError):
    """An adapter result that breaks the OhlcvResult contract."""


def assert_ohlcv_contract(result: OhlcvResult) -> None:
    """Check an adapter result honours the contract (reusable conformance check).

    Raises :class:`ContractViolation` — real exceptions, not ``assert`` statements,
    which silently vanish under ``python -O``.
    """

    def check(cond: bool, message: str) -> None:
        if not cond:
            raise ContractViolation(message)

    check(bool(result.source), "source must be stamped")
    check(isinstance(result.retrieved_at, datetime), "retrieved_at must be stamped")
    check(bool(result.currency), "currency must be explicit")
    for bar in result.bars:
        check(isinstance(bar.close, Decimal), "prices must be Decimal")
        check(bar.close >= 0 and bar.open >= 0, "prices must be non-negative")
        check(bar.high >= bar.low, "high must be >= low")
    for split in result.splits:
        check(isinstance(split.ratio, Decimal) and split.ratio > 0, "split ratio Decimal > 0")
    for dividend in result.dividends:
        check(isinstance(dividend.amount, Decimal), "dividend amount must be Decimal")
    split_dates = [s.ex_date for s in result.splits]
    div_dates = [d.ex_date for d in result.dividends]
    bar_dates = [b.date for b in result.bars]
    check(len(split_dates) == len(set(split_dates)), "splits must be ex-date keyed (unique)")
    check(len(div_dates) == len(set(div_dates)), "dividends must be ex-date keyed (unique)")
    check(len(bar_dates) == len(set(bar_dates)), "bars must be date-unique")
