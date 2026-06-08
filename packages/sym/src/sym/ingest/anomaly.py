"""Stage-1 price-anomaly detection (Story 2.4, AR-9 / NFR-1 annotate half).

Pure detection: given a security's raw bars + its explicit splits + the expected
trading calendar, return the suspect dates to flag in ``prices_review``. The price
itself is never discarded (the writer still lands it in ``prices_raw``) — flagging
is annotation.

The ±50% single-day-move check runs on **split-adjusted** prices: because sym stores
TRUE raw prices, a 4:1 split is a real −75% raw move, so detecting on raw prices
would false-flag every corporate action. Dividing by the explicit cumulative split
factor makes corporate-action days continuous, so only a genuine bad tick trips it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sym.sources.contract import OhlcvBar, SplitEvent, cumulative_split_factor

PRICE_JUMP = "price_jump"
PRICE_ON_NON_TRADING_DAY = "price_on_non_trading_day"

JUMP_THRESHOLD = Decimal("0.50")  # NFR-1: a single-day move > ±50% is suspect.


@dataclass(frozen=True)
class PriceFlag:
    """One suspect (session_date) to annotate in prices_review."""

    session_date: date
    flag_type: str
    detail: str
    pct_move: Decimal | None = None


def detect_anomalies(
    bars: Sequence[OhlcvBar],
    splits: Sequence[SplitEvent],
    expected_sessions: set[date] | None = None,
) -> list[PriceFlag]:
    """Suspect dates for a security — split-aware ±50% jumps + non-trading-day prices.

    At most one flag per date (a jump takes precedence; a coincident non-trading-day
    is folded into its detail) so the write is a clean UPSERT on (figi, date).
    """
    ordered = sorted(bars, key=lambda b: b.date)
    flags: dict[date, PriceFlag] = {}

    previous: tuple[date, Decimal] | None = None
    for bar in ordered:
        adjusted = bar.close / cumulative_split_factor(splits, bar.date)
        if previous is not None:
            _, prev_adjusted = previous
            if prev_adjusted > 0:
                move = adjusted / prev_adjusted - Decimal(1)
                if abs(move) > JUMP_THRESHOLD:
                    flags[bar.date] = PriceFlag(
                        bar.date,
                        PRICE_JUMP,
                        f"{move:+.1%} split-adjusted single-day move",
                        move,
                    )
        previous = (bar.date, adjusted)

    if expected_sessions is not None:
        for bar in ordered:
            if bar.date in expected_sessions:
                continue
            existing = flags.get(bar.date)
            if existing is None:
                flags[bar.date] = PriceFlag(
                    bar.date, PRICE_ON_NON_TRADING_DAY, "price on a non-trading day"
                )
            else:  # already a jump on this date — note the coincident divergence
                flags[bar.date] = PriceFlag(
                    bar.date,
                    existing.flag_type,
                    f"{existing.detail}; also on a non-trading day",
                    existing.pct_move,
                )

    return [flags[d] for d in sorted(flags)]
