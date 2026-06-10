"""fact_returns loader — materialized PR + TR matrix (Stories 3.4/3.5, FR-9/FR-10/AR-7).

Per the Story 3.3 spike the matrix is materialized via *filtered per-figi reads* of
``v_prices_adjusted`` (never a full-view scan). For each security the loader pulls
its adjusted series + raw closes + dividends + the current calendar once, builds a
total-return index (EXDATE_C: dividends reinvested on ex-date, gross), and computes
**both** PR (from ``adj_close``) and TR (from the TRI) for every (as_of_date × every window)
using the ``windows.py`` spec. Insufficient history → NULL. One durable txn per figi.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from sym.calendar.snapshot import current_calendar_version
from sym.returns.windows import (
    INCEPTION,
    WINDOWS,
    base_date,
    canonical_return,
    end_date,
    period_years,
)


def input_hash(
    calendar_version: int | None,
    base: date | None,
    end: date | None,
    adj_base: Decimal | None,
    adj_end: Decimal | None,
    tri_base: Decimal | None,
    tri_end: Decimal | None,
) -> str:
    """Stable hash of a row's inputs (AR-7: raw_slice + factor_set + calendar_version).

    ``base``/``end`` are the window's two endpoint sessions (``end`` is as-of for
    base->as-of windows, or a past session for discrete ``period`` windows). The
    adjusted endpoints encode raw + split factors; the TRI endpoints additionally
    encode dividends. With calendar_version (which fixes the dates) this is
    reproducible (DR determinism) and lets 3.6's dirty-set detect any input change.
    """
    payload = f"{calendar_version}|{base}|{end}|{adj_base}|{adj_end}|{tri_base}|{tri_end}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def total_return_index(
    rows: Sequence[tuple[date, Decimal, Decimal]],
    dividends: dict[date, Decimal],
) -> dict[date, Decimal]:
    """Forward total-return index (EXDATE_C). ``rows`` = (date, close_raw, adj_close) asc.

    ``TRI[d] = adj_close[d] × growth[d]`` where ``growth`` is the cumulative dividend
    reinvestment factor ``∏(1 + D/adj_close(ex))`` over ex-dates ≤ d. This keeps the
    price dimension exact: with **no dividends** ``growth ≡ 1`` so ``TRI == adj_close``
    and TR == PR exactly (computing TRI as a product of price *ratios* would instead
    accumulate Decimal rounding and make TR ≈ PR). Equivalent to the daily factor
    ``adj_ratio × (1 + yield)``, but rounding-free in the price term.

    **Ex-date on a missing bar:** a dividend whose ex-date has no price row (gap,
    halt, vendor-shifted date) is CARRIED FORWARD and reinvested at the next priced
    session's close — dropping it would silently understate TR forever. Dividends
    dated before the first bar are skipped (no price basis exists to reinvest at).

    **Basis consistency (critical):** the ex-date yield ``D / price`` must take D and the
    price in the SAME split basis. yfinance reports dividends **split-adjusted to today's
    basis**, and ``adj_close`` (= close_raw / future-split product) is likewise today-basis,
    so we divide by ``adj_close`` — not ``close_raw`` (then-current/historical). Mixing them
    inflates every pre-split dividend by the net split factor and compounds (e.g. GE's 1:8
    reverse split made its 30Y TR ~8× too high). The split factor cancels: ``D_today /
    adj_close == D_hist / close_raw`` = the true ex-date yield.
    """
    tri: dict[date, Decimal] = {}
    if not rows:
        return tri
    growth = Decimal(1)
    pending = Decimal(0)
    first_bar = rows[0][0]
    div_dates = [d for d in sorted(dividends) if d >= first_bar]
    di = 0
    for session_date, _close_raw, adj_close in rows:
        while di < len(div_dates) and div_dates[di] <= session_date:
            pending += dividends[div_dates[di]]
            di += 1
        if pending and adj_close > 0:
            growth = growth * (Decimal(1) + pending / adj_close)
            pending = Decimal(0)
        tri[session_date] = adj_close * growth
    return tri


@dataclass(frozen=True)
class ReturnRow:
    composite_figi: str
    window_id: int
    as_of_date: date
    pr: Decimal | None
    tr: Decimal | None
    input_hash: str
    gated: bool = False


def compute_return_rows(
    figi: str,
    as_of_dates: Sequence[date],
    adj: dict[date, Decimal],
    tri: dict[date, Decimal],
    sessions: Sequence[date],
    calendar_version: int | None,
    gated_dates: Collection[date] = frozenset(),
    gated_div_dates: Collection[date] = frozenset(),
) -> list[ReturnRow]:
    """PR + TR rows for one security across ``as_of_dates`` × all return windows (pure).

    A row whose as_of_date, base, or end references an unreviewed flag (``gated_dates``)
    is gated: pr/tr held NULL, ``gated=True`` (AR-9 gate half). TR is additionally gated
    when an unreviewed flag sits on an INTERIOR dividend ex-date (``gated_div_dates``) —
    the TRI folds that day's adj_close into every later value, so endpoint checks alone
    would publish TR built on a suspect price. ``input_hash`` still reflects the prices,
    so a later price change re-dirties even a gated row.

    Inception windows (SI/SI_ANN) anchor at the security's FIRST PRICED session
    (``min(adj)``), not ``sessions[0]`` — the exchange calendar reaches decades before
    most listings, and a calendar-anchored base has no price, which would NULL the
    window for every security younger than the calendar.
    """
    rows: list[ReturnRow] = []
    first_priced = min(adj) if adj else None
    div_flags = sorted(gated_div_dates)
    for as_of_date in as_of_dates:
        for window in WINDOWS:
            # end is as-of for base->as-of windows, a past session for `period` ones.
            end = end_date(window, as_of_date, sessions)
            base = (
                first_priced if window.kind == INCEPTION
                else base_date(window, as_of_date, sessions)
            )
            adj_end = adj.get(end) if end is not None else None
            tri_end = tri.get(end) if end is not None else None
            adj_base = adj.get(base) if base is not None else None
            tri_base = tri.get(base) if base is not None else None
            gated = (
                as_of_date in gated_dates
                or (base is not None and base in gated_dates)
                or (end is not None and end in gated_dates)
            )
            tr_gated = gated or (
                base is not None
                and end is not None
                and any(base < d <= end for d in div_flags)
            )
            years = period_years(end, base) if (window.annualized and base and end) else None
            pr = (
                canonical_return(adj_end, adj_base, annualized=window.annualized, years=years)
                if not gated and adj_base is not None and adj_end is not None else None
            )
            tr = (
                canonical_return(tri_end, tri_base, annualized=window.annualized, years=years)
                if not tr_gated and tri_base is not None and tri_end is not None else None
            )
            rows.append(
                ReturnRow(figi, window.id, as_of_date, pr, tr,
                          input_hash(calendar_version, base, end, adj_base, adj_end,
                                     tri_base, tri_end),
                          gated or tr_gated)
            )
    return rows


def _securities_for_returns(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """All securities, regardless of lifecycle status (AR-8 survivorship invariant).

    Returns are computed for active, delisted, AND suspended names alike — a
    delisted security keeps its full price history and MUST flow through the
    engine, else backtests built on sym carry survivorship bias. The active/
    delisted distinction is a *query-time* choice for the researcher, never a
    silent compute-time filter here. (Securities with no prices in range are
    natural no-ops downstream.)
    """
    rows = conn.execute(
        "SELECT composite_figi, mic FROM securities ORDER BY composite_figi"
    ).fetchall()
    return [(figi, mic.strip() if isinstance(mic, str) else mic) for figi, mic in rows]


def _calendar_sessions(conn: psycopg.Connection, mic: str) -> list[date]:
    rows = conn.execute(
        """
        SELECT tc.session_date FROM trading_calendar tc
          JOIN trading_calendar_version v USING (calendar_version)
         WHERE v.is_current AND tc.mic = %s
         ORDER BY tc.session_date
        """,
        (mic,),
    ).fetchall()
    return [r[0] for r in rows]


def _price_rows(conn: psycopg.Connection, figi: str) -> list[tuple[date, Decimal, Decimal]]:
    return conn.execute(
        """
        SELECT session_date, close_raw, adj_close FROM v_prices_adjusted
         WHERE composite_figi = %s ORDER BY session_date
        """,
        (figi,),
    ).fetchall()


def _dividends(conn: psycopg.Connection, figi: str) -> dict[date, Decimal]:
    rows = conn.execute(
        """
        SELECT ex_date, value FROM corporate_actions
         WHERE composite_figi = %s AND action_type = 'dividend'
        """,
        (figi,),
    ).fetchall()
    return {ex_date: value for ex_date, value in rows}


def _unreviewed_flag_dates(conn: psycopg.Connection, figi: str) -> set[date]:
    """Session dates with an unreviewed prices_review flag (the gate set)."""
    rows = conn.execute(
        "SELECT session_date FROM prices_review WHERE composite_figi = %s AND NOT reviewed",
        (figi,),
    ).fetchall()
    return {r[0] for r in rows}


def _upsert(conn: psycopg.Connection, rows: Sequence[ReturnRow]) -> None:
    """COPY into a temp table then UPSERT pr+tr — one durable transaction per figi."""
    if not rows:
        return
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE _ret (composite_figi char(12), window_id int, as_of_date date, "
            "pr numeric, tr numeric, input_hash text, gated boolean) ON COMMIT DROP"
        )
        copy_sql = (
            "COPY _ret (composite_figi, window_id, as_of_date, pr, tr, input_hash, gated) FROM STDIN"
        )
        with cur.copy(copy_sql) as cp:
            for r in rows:
                cp.write_row(
                    (r.composite_figi, r.window_id, r.as_of_date, r.pr, r.tr, r.input_hash, r.gated)
                )
        # Dirty-set skip: rewrite only rows whose inputs OR gate status changed.
        cur.execute(
            """
            INSERT INTO fact_returns
                (composite_figi, window_id, as_of_date, pr, tr, input_hash, gated)
            SELECT composite_figi, window_id, as_of_date, pr, tr, input_hash, gated FROM _ret
            ON CONFLICT (composite_figi, window_id, as_of_date) DO UPDATE
                SET pr = EXCLUDED.pr, tr = EXCLUDED.tr,
                    input_hash = EXCLUDED.input_hash, gated = EXCLUDED.gated
                WHERE fact_returns.input_hash IS DISTINCT FROM EXCLUDED.input_hash
                   OR fact_returns.gated IS DISTINCT FROM EXCLUDED.gated
            """
        )


@dataclass
class RecomputeSummary:
    securities: int = 0
    rows: int = 0


def load_returns(
    conn: psycopg.Connection,
    *,
    start_date: date,
    end_date: date,
    figis: Sequence[str] | None = None,
) -> RecomputeSummary:
    """Materialize PR + TR into fact_returns for as_of_dates in [start_date, end_date].

    Spans ALL securities including delisted (AR-8 survivorship invariant) — see
    ``_securities_for_returns``.
    """
    conn.autocommit = True  # per-figi durable commits
    wanted = set(figis) if figis is not None else None
    summary = RecomputeSummary()
    for figi, mic in _securities_for_returns(conn):
        if wanted is not None and figi not in wanted:
            continue
        calendar_version = current_calendar_version(conn, mic)
        if calendar_version is None:
            continue  # no calendar for this exchange (e.g. XNSE)
        sessions = _calendar_sessions(conn, mic)
        price_rows = _price_rows(conn, figi)
        adj = {d: adj_close for d, _close_raw, adj_close in price_rows}
        dividends = _dividends(conn, figi)
        tri = total_return_index(price_rows, dividends)
        gated_dates = _unreviewed_flag_dates(conn, figi)
        as_of_dates = [d for d in sorted(adj) if start_date <= d <= end_date]
        # Drop rows whose as-of date no longer has a price (e.g. an overwrite removed a
        # vendor-phantom bar) — the upsert alone never deletes, so they'd live forever.
        conn.execute(
            "DELETE FROM fact_returns WHERE composite_figi = %s "
            "AND as_of_date BETWEEN %s AND %s AND NOT (as_of_date = ANY(%s))",
            (figi, start_date, end_date, as_of_dates),
        )
        if not as_of_dates:
            continue
        rows = compute_return_rows(
            figi, as_of_dates, adj, tri, sessions, calendar_version, gated_dates,
            gated_div_dates=gated_dates & set(dividends),  # flags on dividend ex-dates
        )
        _upsert(conn, rows)
        summary.securities += 1
        summary.rows += len(rows)
    return summary


DEFAULT_LOOKBACK = timedelta(days=365)
