"""FX ingest (Epic FX, FX2) — load USD-base observed rates, immutable + source-tagged.

Fetches USD-base observations from an ``FxSource``, runs a **relative** day-over-day
plausibility band (catches a decimal shift / inverted feed / 10x without per-currency
magic numbers), and inserts them as ``(base='USD', quote=ccy, …)`` with
``ON CONFLICT DO NOTHING`` (immutable; resumable — a re-run inserts only missing rows).
``backfill`` loads from the ECB-inception floor; ``delta`` loads only the tail after the
latest stored date. Stored rates are never overwritten; corrections are out of scope (v1).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from sym.fx.source import FxObservation, FxSource

# ECB reference-rate inception (Frankfurter's historical floor).
DEFAULT_FX_FLOOR = date(1999, 1, 4)

# Relative day-over-day gross-corruption band. FX rarely moves > ~10%/day; 50% leaves
# headroom for legit EM crisis moves while catching a 10x, a decimal shift, or an
# inverted feed (e.g. BRL 5.4 -> 0.185 is a 96% drop).
MAX_DAILY_MOVE = Decimal("0.50")


@dataclass
class FxLoadSummary:
    currencies: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    implausible: int = 0
    flagged: list[str] = field(default_factory=list)


def implausible(prev: Decimal | None, new: Decimal, *, band: Decimal = MAX_DAILY_MOVE) -> bool:
    """True if ``new`` moves more than ``band`` (relative) vs the prior observed ``prev``."""
    if prev is None or prev <= 0:
        return False  # nothing to compare against (first observation)
    return abs(new / prev - Decimal(1)) > band


def _default_currencies(conn: psycopg.Connection) -> list[str]:
    """Every non-USD currency in the reference table (Frankfurter returns what it supports)."""
    rows = conn.execute("SELECT code FROM currency WHERE code <> 'USD' ORDER BY code").fetchall()
    return [r[0] for r in rows]


def _last_stored_rate(conn: psycopg.Connection, ccy: str, source: str) -> Decimal | None:
    row = conn.execute(
        "SELECT rate FROM fx_rate WHERE base_currency='USD' AND quote_currency=%s AND source=%s "
        "ORDER BY as_of_date DESC LIMIT 1",
        (ccy, source),
    ).fetchone()
    return row[0] if row else None


def _max_stored_date(conn: psycopg.Connection, source: str) -> date | None:
    row = conn.execute(
        "SELECT max(as_of_date) FROM fx_rate WHERE source=%s", (source,)
    ).fetchone()
    return row[0] if row else None


def load_fx(
    conn: psycopg.Connection,
    source: FxSource,
    *,
    start: date,
    end: date,
    currencies: Sequence[str] | None = None,
) -> FxLoadSummary:
    """Fetch USD-base rates for ``[start, end]``, plausibility-filter, immutable-insert."""
    conn.autocommit = True
    ccys = list(currencies) if currencies is not None else _default_currencies(conn)
    summary = FxLoadSummary()
    obs = source.fetch(ccys, start, end)
    by_ccy: dict[str, list[FxObservation]] = {}
    for o in obs:
        by_ccy.setdefault(o.currency, []).append(o)
    for ccy, series in by_ccy.items():
        summary.currencies += 1
        prev = _last_stored_rate(conn, ccy, source.SOURCE)
        for o in sorted(series, key=lambda x: x.as_of_date):
            if implausible(prev, o.rate):
                summary.implausible += 1
                summary.flagged.append(f"{ccy}@{o.as_of_date}={o.rate}")
                continue  # reject; do NOT advance prev to a bad value
            row = conn.execute(
                "INSERT INTO fx_rate (base_currency, quote_currency, as_of_date, rate, source) "
                "VALUES ('USD', %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING quote_currency",
                (ccy, o.as_of_date, o.rate, source.SOURCE),
            ).fetchone()
            if row is not None:
                summary.inserted += 1
            else:
                summary.skipped_existing += 1
            prev = o.rate
    return summary


def backfill_fx(
    conn: psycopg.Connection,
    source: FxSource,
    *,
    end: date,
    start: date = DEFAULT_FX_FLOOR,
    currencies: Iterable[str] | None = None,
) -> FxLoadSummary:
    """Full-history load from the ECB-inception floor (resumable; immutable writes)."""
    return load_fx(
        conn, source, start=start, end=end,
        currencies=list(currencies) if currencies is not None else None,
    )


def delta_fx(
    conn: psycopg.Connection,
    source: FxSource,
    *,
    end: date,
    currencies: Iterable[str] | None = None,
) -> FxLoadSummary:
    """Incremental load of the tail after the latest stored date for this source."""
    last = _max_stored_date(conn, source.SOURCE)
    start = (last + timedelta(days=1)) if last is not None else DEFAULT_FX_FLOOR
    if start > end:
        return FxLoadSummary()
    return load_fx(
        conn, source, start=start, end=end,
        currencies=list(currencies) if currencies is not None else None,
    )
