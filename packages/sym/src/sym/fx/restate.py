"""FX restatement (Epic FX consumer) — prices + returns in any target currency.

The downstream consumer of the FX layer. Two operations, both **on-demand** (no per-currency
materialization — a thin primitive; usage pulls features):

- ``price_in_currency`` — an adjusted close folded to a target currency as-of its date.
- ``returns_in_currency`` — a security's return windows restated into a target currency.

**The correct method (not naive spot × return):** an unhedged return in currency *X* is
``(1 + r_local) · (FX_X(as_of) / FX_X(base)) − 1`` where ``FX_X(t)`` = target per unit of local
(``convert(1, local, X, t)``). That is identical to converting the price *levels* at both window
endpoints and recomputing — it folds in the FX move over the window, never just the spot. For an
*annualized* window the local rate is de-annualized to cumulative, restated, then re-annualized
over the same elapsed years. TR is restated by the same endpoint FX ratio (standard unhedged
approximation; intra-window dividend-timing FX is a second-order effect).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg

from sym.fx.convert import convert
from sym.returns.loader import _calendar_sessions
from sym.returns.windows import WINDOWS, base_date, period_years

_ONE = Decimal(1)


def restate_return(
    local_return: Decimal | None,
    fx_ratio: Decimal | None,
    *,
    annualized: bool = False,
    years: Decimal | float | None = None,
) -> Decimal | None:
    """Restate a local return into a target currency given the window's FX ratio (pure).

    ``fx_ratio`` = ``FX_X(as_of) / FX_X(base)`` (target-per-local at the two window endpoints).
    Cumulative: ``(1+r)·ratio − 1``. Annualized: de-annualize → restate → re-annualize over
    ``years`` (actual elapsed years). Returns ``None`` on missing inputs.
    """
    if local_return is None or fx_ratio is None or fx_ratio <= 0:
        return None
    if not annualized:
        return (_ONE + local_return) * fx_ratio - _ONE
    if not years or Decimal(years) <= 0:
        return None
    yrs = Decimal(years)
    cum_local = ((_ONE + local_return).ln() * yrs).exp() - _ONE
    cum_restated = (_ONE + cum_local) * fx_ratio - _ONE
    if (_ONE + cum_restated) <= 0:
        return None
    return ((_ONE + cum_restated).ln() / yrs).exp() - _ONE


def price_in_currency(
    conn: psycopg.Connection, figi: str, on_date: date, target: str
) -> Decimal | None:
    """The adjusted close of ``figi`` on ``on_date`` folded to ``target`` (None on any gap)."""
    row = conn.execute(
        "SELECT adj_close FROM v_prices_adjusted WHERE composite_figi=%s AND session_date=%s",
        (figi, on_date),
    ).fetchone()
    if not row or row[0] is None:
        return None
    sec = conn.execute(
        "SELECT currency_code FROM securities WHERE composite_figi=%s", (figi,)
    ).fetchone()
    if not sec or not sec[0]:
        return None
    return convert(conn, row[0], sec[0].strip(), target, on_date)


def returns_in_currency(
    conn: psycopg.Connection, figi: str, as_of: date, target: str
) -> dict[str, dict[str, Decimal | None]]:
    """Restate every materialized return window for ``(figi, as_of)`` into ``target``.

    Returns ``{window_code: {'pr': …, 'tr': …}}``. A window whose base date or FX leg can't
    resolve yields ``None`` for that window. If the security is already in ``target``, the local
    returns pass through unchanged.
    """
    sec = conn.execute(
        "SELECT currency_code, mic FROM securities WHERE composite_figi=%s", (figi,)
    ).fetchone()
    if not sec or not sec[0]:
        return {}
    local = sec[0].strip()
    mic = sec[1].strip() if isinstance(sec[1], str) else sec[1]
    rows = conn.execute(
        "SELECT window_id, pr, tr FROM fact_returns WHERE composite_figi=%s AND as_of_date=%s",
        (figi, as_of),
    ).fetchall()
    by_id = {w.id: w for w in WINDOWS}
    out: dict[str, dict[str, Decimal | None]] = {}
    if local == target:  # already in the target currency — pass through
        for wid, pr, tr in rows:
            w = by_id.get(wid)
            if w:
                out[w.code] = {"pr": pr, "tr": tr}
        return out
    sessions = _calendar_sessions(conn, mic)
    f_asof = convert(conn, _ONE, local, target, as_of)
    for wid, pr, tr in rows:
        w = by_id.get(wid)
        if w is None:
            continue
        base = base_date(w, as_of, sessions)
        f_base = convert(conn, _ONE, local, target, base) if base is not None else None
        if f_asof is None or f_base is None or f_base <= 0:
            out[w.code] = {"pr": None, "tr": None}
            continue
        ratio = f_asof / f_base
        years = period_years(as_of, base) if (w.annualized and base) else None
        out[w.code] = {
            "pr": restate_return(pr, ratio, annualized=w.annualized, years=years),
            "tr": restate_return(tr, ratio, annualized=w.annualized, years=years),
        }
    return out
