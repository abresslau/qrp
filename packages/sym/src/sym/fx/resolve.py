"""FX as-of resolver (Epic FX, FX3a) — last observed rate ≤ D, with staleness policy.

The authoritative as-of path (used by ``convert`` and ``sym validate``). For a currency
and a date D it returns the most recent observed USD-base rate with ``as_of_date ≤ D``:
- a carry within the **weekend span (3 days)** is the normal Fri→Mon case;
- a longer carry (holiday cluster) is still returned but flagged ``is_filled`` with ``days_stale``;
- beyond the **outage cap (7 days)** the rate is withheld (``status='stale'``, ``rate=None``) so a
  vendor outage can't silently carry a stale rate.

No forward-fill is ever stored — this resolves on read against immutable observations. The
pure ``classify`` is unit-tested DB-free; ``fx_rate`` is the thin DB wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

USD = "USD"
WEEKEND_SPAN_DAYS = 3  # normal Fri->Mon carry (a fill within this is unremarkable)
OUTAGE_CAP_DAYS = 7  # beyond this from the last observed rate -> withhold (stale)


@dataclass(frozen=True)
class FxResolution:
    """The as-of resolution for one (currency, date)."""

    currency: str
    as_of: date
    rate: Decimal | None
    observed_date: date | None
    days_stale: int
    status: str  # ok | stale | no_data

    @property
    def is_filled(self) -> bool:
        """True when the rate was carried forward from an earlier observed date."""
        return self.status == "ok" and self.days_stale > 0


def classify(
    currency: str,
    as_of: date,
    observed_date: date | None,
    rate: Decimal | None,
    *,
    outage_cap: int = OUTAGE_CAP_DAYS,
) -> FxResolution:
    """Classify the latest observed rate ≤ ``as_of`` (pure).

    ``observed_date``/``rate`` are the most recent observation on/before ``as_of`` (or
    ``None`` if there is none). ``no_data`` (nothing observed ≤ as_of, incl. an unknown
    currency) is distinct from ``stale`` (an observation exists but is older than the cap).
    """
    if observed_date is None or rate is None:
        return FxResolution(currency, as_of, None, observed_date, 0, "no_data")
    days = (as_of - observed_date).days
    if days < 0:
        return FxResolution(currency, as_of, None, observed_date, days, "no_data")
    if days > outage_cap:
        return FxResolution(currency, as_of, None, observed_date, days, "stale")
    return FxResolution(currency, as_of, rate, observed_date, days, "ok")


def fx_rate(
    conn: psycopg.Connection,
    currency: str,
    as_of: date,
    *,
    outage_cap: int = OUTAGE_CAP_DAYS,
) -> FxResolution:
    """Resolve the USD-base rate (currency per 1 USD) as-of ``as_of`` (thin DB wrapper)."""
    if currency == USD:
        return FxResolution(USD, as_of, Decimal(1), as_of, 0, "ok")
    # Latest observation on/before as_of; when two sources hold the same date, the lower
    # fx_source_rank wins (Frankfurter over ECB over fawazahmed0) so the pick is deterministic.
    row = conn.execute(
        "SELECT as_of_date, rate FROM fx_rate "
        "WHERE base_currency = 'USD' AND quote_currency = %s AND as_of_date <= %s "
        "ORDER BY as_of_date DESC, fx_source_rank(source) ASC LIMIT 1",
        (currency, as_of),
    ).fetchone()
    observed_date, rate = (row[0], row[1]) if row else (None, None)
    return classify(currency, as_of, observed_date, rate, outage_cap=outage_cap)
