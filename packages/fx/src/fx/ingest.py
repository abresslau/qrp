"""FX ingest (Epic FX, FX2) — load USD-base observed rates, immutable + source-tagged.

Fetches USD-base observations from an ``FxSource``, runs a **relative** day-over-day
plausibility band (catches a decimal shift / inverted feed / 10x without per-currency
magic numbers), and inserts them as ``(base='USD', quote=ccy, …)`` with
``ON CONFLICT DO NOTHING`` (immutable; resumable — a re-run inserts only missing rows).

One loader, :func:`fill_fx`, mirrors `sym load`: no ``start_date`` → the tail after the latest
stored date (the daily case); an explicit ``start_date`` → fill from that floor (e.g. the
ECB-inception ``DEFAULT_FX_FLOOR``, a full-history backfill). Stored rates are never
overwritten; corrections are out of scope (v1), so there is no overwrite mode.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from fx.source import FxObservation, FxSource

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
    # The window actually loaded, after tail resolution — so callers can surface the
    # resolved start in the daily case (where the caller passed start_date=None).
    start_date: date | None = None
    end_date: date | None = None


def implausible(prev: Decimal | None, new: Decimal, *, band: Decimal = MAX_DAILY_MOVE) -> bool:
    """True if ``new`` moves more than ``band`` (relative) vs the prior observed ``prev``."""
    if prev is None or prev <= 0:
        return False  # nothing to compare against (first observation)
    return abs(new / prev - Decimal(1)) > band


def _default_currencies(conn: psycopg.Connection) -> list[str]:
    """Every non-USD currency in the reference table (Frankfurter returns what it supports)."""
    rows = conn.execute(
        "SELECT code FROM fx.currency WHERE code <> 'USD' ORDER BY code"
    ).fetchall()
    return [r[0] for r in rows]


def _last_rate_before(
    conn: psycopg.Connection, ccy: str, source: str, before: date
) -> Decimal | None:
    """Last stored rate strictly BEFORE ``before`` — the plausibility seed for a load window.

    Seeding from the global latest rate instead would compare e.g. a 1999 backfill
    observation against today's rate and falsely reject decades of history for any
    currency that moved more than the band since (most of EM).
    """
    row = conn.execute(
        "SELECT rate FROM fx.fx_rate WHERE base_currency='USD' AND quote_currency=%s AND source=%s "
        "AND as_of_date < %s ORDER BY as_of_date DESC LIMIT 1",
        (ccy, source, before),
    ).fetchone()
    return row[0] if row else None


def _last_stored_dates(conn: psycopg.Connection, source: str) -> dict[str, date]:
    """Latest stored as_of_date per quote currency for this source."""
    rows = conn.execute(
        "SELECT quote_currency, max(as_of_date) FROM fx.fx_rate WHERE source=%s "
        "GROUP BY quote_currency",
        (source,),
    ).fetchall()
    return {c: d for c, d in rows}


def _record_rejection(conn, ccy, o, prev, source, reason) -> None:
    """Persist a plausibility rejection (Story S.1 — FX NFR4's review surface).

    The in-memory ``flagged`` list is the CLI print; THIS row is what survives
    the process. One OPEN row per (quote, date, source): a daily re-run of the
    same rejection refreshes, never duplicates. A wedged band (genuine move,
    e.g. a peg break) therefore shows up as a growing open queue — and
    ACCEPTING a row (``fx review --accept``) inserts the rate into
    ``fx_rate``, after which ``prev`` advances naturally on the next load.
    """
    relative = (
        abs(o.rate / prev - Decimal(1))
        if (prev is not None and prev > 0 and o.rate > 0)
        else None
    )
    conn.execute(
        """
        INSERT INTO fx.fx_rate_review
            (quote_currency, as_of_date, rate, prior_rate, relative_move, source, reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (quote_currency, as_of_date, source) WHERE NOT reviewed DO UPDATE
            SET rate = EXCLUDED.rate, prior_rate = EXCLUDED.prior_rate,
                relative_move = EXCLUDED.relative_move, reason = EXCLUDED.reason
        """,
        (ccy, o.as_of_date, o.rate, prev, relative, source, reason),
    )


def load_fx(
    conn: psycopg.Connection,
    source: FxSource,
    *,
    start_date: date,
    end_date: date,
    currencies: Sequence[str] | None = None,
) -> FxLoadSummary:
    """Fetch USD-base rates for ``[start_date, end_date]``: plausibility-filter,
    immutable-insert; rejections persist to ``fx_rate_review`` (S.1)."""
    conn.autocommit = True
    ccys = list(currencies) if currencies is not None else _default_currencies(conn)
    summary = FxLoadSummary(start_date=start_date, end_date=end_date)
    obs = source.fetch(ccys, start_date, end_date)
    by_ccy: dict[str, list[FxObservation]] = {}
    for o in obs:
        by_ccy.setdefault(o.currency, []).append(o)
    for ccy, series in by_ccy.items():
        summary.currencies += 1
        series = sorted(series, key=lambda x: x.as_of_date)
        # Seed the day-over-day band from the last rate BEFORE this window (not the global
        # latest) so backfills below stored history compare against the right neighbour.
        prev = _last_rate_before(conn, ccy, source.SOURCE, series[0].as_of_date)
        # Drain gate (S.1): only probe per-insert when this currency HAS open
        # rejection rows — the common clean path pays one query per currency.
        has_open_rejections = conn.execute(
            "SELECT 1 FROM fx.fx_rate_review WHERE quote_currency = %s AND source = %s "
            "AND NOT reviewed LIMIT 1",
            (ccy, source.SOURCE),
        ).fetchone() is not None
        for o in series:
            if o.rate <= 0:
                summary.implausible += 1
                summary.flagged.append(f"{ccy}@{o.as_of_date}={o.rate} (non-positive)")
                _record_rejection(conn, ccy, o, prev, source.SOURCE, "non_positive")
                continue  # never store a non-positive rate; do NOT advance prev
            if implausible(prev, o.rate):
                summary.implausible += 1
                summary.flagged.append(f"{ccy}@{o.as_of_date}={o.rate}")
                _record_rejection(conn, ccy, o, prev, source.SOURCE, "band_exceeded")
                continue  # reject; do NOT advance prev to a bad value
            row = conn.execute(
                "INSERT INTO fx.fx_rate (base_currency, quote_currency, as_of_date, rate, source) "
                "VALUES ('USD', %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING quote_currency",
                (ccy, o.as_of_date, o.rate, source.SOURCE),
            ).fetchone()
            if row is not None:
                summary.inserted += 1
                if has_open_rejections:
                    # A stored rate makes any queued rejection for this key MOOT
                    # (the band un-wedged and this observation passed) — close it
                    # as superseded so a multi-day wedge queue DRAINS itself.
                    conn.execute(
                        "UPDATE fx.fx_rate_review "
                        "   SET reviewed = TRUE, resolution = 'superseded', "
                        "       reviewed_at = now() "
                        " WHERE quote_currency = %s AND as_of_date = %s "
                        "   AND source = %s AND NOT reviewed",
                        (ccy, o.as_of_date, source.SOURCE),
                    )
            else:
                summary.skipped_existing += 1
            prev = o.rate
    return summary


def fill_fx(
    conn: psycopg.Connection,
    source: FxSource,
    *,
    end_date: date,
    start_date: date | None = None,
    currencies: Iterable[str] | None = None,
) -> FxLoadSummary:
    """Add missing USD-base rates (immutable insert; skips existing) — the one FX loader.

    Forward (``start_date=None``): only the tail after the latest stored date — resolved
    PER CURRENCY, so a currency newly added to the ``currency`` table pulls its whole
    history (the fetch window is the min over currencies; ``ON CONFLICT DO NOTHING``
    makes the refetch of already-covered currencies a cheap skip). Gap-aware (explicit
    ``start_date``): fill from that floor — e.g. ``DEFAULT_FX_FLOOR`` for a full-history
    backfill. Mirrors `sym load` (fill).
    """
    ccys = list(currencies) if currencies is not None else _default_currencies(conn)
    if start_date is None:
        last_by_ccy = _last_stored_dates(conn, source.SOURCE)
        starts = [
            (last_by_ccy[c] + timedelta(days=1)) if c in last_by_ccy else DEFAULT_FX_FLOOR
            for c in ccys
        ]
        start_date = min(starts) if starts else DEFAULT_FX_FLOOR
    if start_date > end_date:
        return FxLoadSummary(start_date=start_date, end_date=end_date)
    return load_fx(conn, source, start_date=start_date, end_date=end_date, currencies=ccys)
