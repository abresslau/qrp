"""FX conversion (Epic FX, FX3b) — triangulate through USD, as-of, staleness-safe.

``convert(amount, from_ccy, to_ccy, as_of_date)`` folds an amount between currencies as-of a
date. Since every stored rate is ``ccy per 1 USD``, a cross is a single formula —
``amount × rate(to) / rate(from)`` — with USD legs resolving to ``rate=1`` (so USD↔ccy and
ccy↔ccy share one path). Both legs go through the as-of resolver (FX3a), so a missing or
stale leg makes the conversion ``None``; additionally the two legs' *observed* dates must
agree within the weekend span (else a Monday-vs-Thursday spread would masquerade as a
valid cross). Returns full-precision ``Decimal`` (round on display); ``None`` on any gap.

The ``(base,quote)`` schema stays general for a future *purchased direct cross*, but v1
builds no direct-cross branch — triangulation is the only path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg

from sym.fx.resolve import WEEKEND_SPAN_DAYS, FxResolution, fx_rate


def triangulate(
    amount: Decimal,
    from_res: FxResolution,
    to_res: FxResolution,
    *,
    max_leg_spread: int = WEEKEND_SPAN_DAYS,
) -> Decimal | None:
    """Cross via USD from two resolved legs (pure). ``None`` if either leg is unusable.

    Both legs must be ``ok``; their observed dates must agree within ``max_leg_spread``
    (two legs carried from different days would silently mix dates). USD legs carry
    ``rate=1`` and ``observed_date=as_of_date``, so USD↔ccy works through the same formula.
    """
    if from_res.status != "ok" or to_res.status != "ok":
        return None
    if from_res.rate is None or to_res.rate is None or from_res.rate <= 0 or to_res.rate <= 0:
        return None
    if from_res.observed_date is not None and to_res.observed_date is not None:
        if abs((from_res.observed_date - to_res.observed_date).days) > max_leg_spread:
            return None
    return amount * to_res.rate / from_res.rate


def convert(
    conn: psycopg.Connection,
    amount: Decimal | int | float | str,
    from_ccy: str,
    to_ccy: str,
    as_of_date: date,
) -> Decimal | None:
    """Convert ``amount`` from ``from_ccy`` to ``to_ccy`` as-of ``as_of_date`` (None on any gap)."""
    amt = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    # Normalize: stored codes are uppercase; 'usd' or ' EUR' would silently miss the
    # identity short-circuit / DB lookup and return None.
    from_ccy, to_ccy = from_ccy.strip().upper(), to_ccy.strip().upper()
    if from_ccy == to_ccy:
        return amt  # identity — no rate lookup, never stale
    return triangulate(amt, fx_rate(conn, from_ccy, as_of_date), fx_rate(conn, to_ccy, as_of_date))
