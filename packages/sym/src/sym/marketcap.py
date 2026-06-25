"""Derived market cap (Epic FX consumer) — price × shares, in LCY or any currency.

Market cap is **derived, not stored**: ``close_raw(t) × shares_outstanding(as-of t)``, in the
security's local currency (LCY); convert to USD (or any target) via the FX layer. This keeps a
single source of truth (the raw price + the raw ``shares_outstanding`` fundamental) and yields
market cap for *any* date and *any* currency — the stored ``fundamentals.market_cap_lcy`` /
``market_cap_usd`` are point-in-time snapshots (vendor cross-check), never the source of truth.

Bases: ``close_raw`` is the then-current (historical-basis) price and ``shares_outstanding`` is
the then-reported count, so on a report date the product matches the vendor figure. Shares are
forward-filled from the last report (they change slowly). **Caveat:** a stock split strictly
*between* the last shares report and ``as_of_date`` leaves the carried share count on the wrong
split basis until the next report — accurate on/near report dates, a small split-window
approximation between (the standard data-vendor behavior). ``shares_as_of_date`` is returned so
the basis date is explicit.

Staleness: the price leg is bounded by ``MAX_PRICE_STALE_DAYS`` — a delisted/halted name's
years-old close must not silently multiply into a "current" market cap (the FX leg already
enforces its own outage cap).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg
from fx.convert import convert

# The price leg's recency bound (calendar days). Mirrors the FX resolver's
# outage-cap philosophy: beyond it, the value is withheld rather than stale.
MAX_PRICE_STALE_DAYS = 30


@dataclass(frozen=True)
class MarketCap:
    """A derived market cap with its inputs exposed (for transparency / staleness checks)."""

    figi: str
    as_of_date: date
    currency: str | None  # the currency the value is expressed in (LCY or the requested target)
    value: Decimal | None
    local_currency: str | None
    close_raw: Decimal | None
    shares: Decimal | None
    shares_as_of_date: date | None  # report date the share count came from (forward-filled)


def shares_outstanding_asof(
    conn: psycopg.Connection, figi: str, as_of_date: date
) -> tuple[Decimal | None, date | None]:
    """The most recent reported ``shares_outstanding`` on/before ``as_of_date`` (forward-filled).

    Non-positive vendor counts are rejected — a zero/negative share count would
    yield a zero/negative "market cap" presented as a valid value.
    """
    row = conn.execute(
        "SELECT shares_outstanding, as_of_date FROM fundamentals "
        "WHERE composite_figi = %s AND as_of_date <= %s "
        "AND shares_outstanding IS NOT NULL AND shares_outstanding > 0 "
        "ORDER BY as_of_date DESC LIMIT 1",
        (figi, as_of_date),
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def market_cap(
    conn: psycopg.Connection,
    fx_conn: psycopg.Connection,
    eq_conn: psycopg.Connection,
    figi: str,
    as_of_date: date,
    ccy: str | None = None,
) -> MarketCap:
    """Derived market cap of ``figi`` on ``as_of_date``: ``close_raw × shares``, in LCY or ``ccy``.

    ``conn`` is the sym DB (securities/fundamentals); ``eq_conn`` is the equity DB (the adjusted
    price); ``fx_conn`` is the fx DB (rates), read only when a non-local ``ccy`` conversion is
    needed. ``ccy=None`` returns LCY (the security's own currency); any other code converts via the
    FX layer (``value=None`` if the FX leg is missing/stale). ``value=None`` also when the price or
    the share count is unavailable, or the latest price is older than ``MAX_PRICE_STALE_DAYS``.
    """
    sec = conn.execute(
        "SELECT currency_code FROM securities WHERE composite_figi = %s", (figi,)
    ).fetchone()
    local = sec[0].strip() if sec and sec[0] else None
    px = eq_conn.execute(
        "SELECT close_raw, session_date FROM v_prices_adjusted "
        "WHERE composite_figi = %s AND session_date <= %s "
        "ORDER BY session_date DESC LIMIT 1",
        (figi, as_of_date),
    ).fetchone()
    close_raw = px[0] if px and px[0] is not None else None
    if close_raw is not None and (as_of_date - px[1]).days > MAX_PRICE_STALE_DAYS:
        close_raw = None  # withhold a stale price rather than silently multiplying it
    shares, shares_as_of_date = shares_outstanding_asof(conn, figi, as_of_date)

    out_ccy = ccy or local  # None when the security itself has no currency on file
    if close_raw is None or shares is None or local is None:
        return MarketCap(
            figi, as_of_date, out_ccy, None, local, close_raw, shares, shares_as_of_date
        )

    mcap_lcy = close_raw * shares
    if ccy is None or ccy == local:
        value = mcap_lcy
    else:
        value = convert(fx_conn, mcap_lcy, local, ccy, as_of_date)  # None if FX leg missing/stale
    return MarketCap(figi, as_of_date, out_ccy, value, local, close_raw, shares, shares_as_of_date)
