"""Read layer over ``commodities.price_daily`` — board snapshot + history. Derive-on-read.

The board returns, per commodity, the latest settle plus period changes (1D/1W/1M/YTD/1Y) and a
short sparkline — all computed in Python from a bounded recent window (the table is small: ~25
commodities × a few thousand days). History returns the full series for a charted detail view.
Commodity metadata (name/sector/unit/currency/exchange) is joined from the in-code universe.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

import psycopg

from .universe import BY_CODE, SECTOR_LABEL, sector_rank

SERIES = "continuous_front"


def _as_of(dates: list[date], settles: list[float], target: date) -> float | None:
    """Last settle on/before ``target`` (PIT-correct period anchor); None if before the start."""
    i = bisect_right(dates, target)
    return settles[i - 1] if i > 0 else None


def _pct(last: float, base: float | None) -> float | None:
    if base is None or base == 0:
        return None
    return (last / base - 1.0) * 100.0


def _minus_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28)


class DbCommoditiesGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    # ---- board: one row per commodity with latest + period changes + spark -------------------
    def board(self, *, spark_n: int = 120) -> list[dict]:
        max_row = self._conn.execute(
            "SELECT max(as_of_date) FROM commodities.price_daily WHERE series_type=%s", (SERIES,)
        ).fetchone()
        if not max_row or max_row[0] is None:
            return []
        window_start = max_row[0] - timedelta(days=430)
        rows = self._conn.execute(
            """
            SELECT commodity_code, as_of_date, settle, volume
              FROM commodities.price_daily
             WHERE series_type=%s AND as_of_date >= %s
             ORDER BY commodity_code, as_of_date
            """,
            (SERIES, window_start),
        ).fetchall()
        series: dict[str, tuple[list[date], list[float], list[float | None]]] = {}
        for code, d, settle, vol in rows:
            ds, ss, vs = series.setdefault(code, ([], [], []))
            ds.append(d)
            ss.append(float(settle))
            vs.append(float(vol) if vol is not None else None)

        out: list[dict] = []
        for code, (ds, ss, vs) in series.items():
            meta = BY_CODE.get(code)
            if meta is None or not ss:
                continue
            last_d, last = ds[-1], ss[-1]
            prev = ss[-2] if len(ss) >= 2 else None
            spark = ss[-spark_n:]
            out.append({
                "code": code,
                "name": meta.name,
                "sector": meta.sector,
                "sector_label": SECTOR_LABEL.get(meta.sector, meta.sector),
                "exchange": meta.exchange,
                "currency": meta.currency,
                "unit": meta.unit,
                "as_of_date": last_d.isoformat(),
                "last": last,
                "prev": prev,
                "chg_1d": (last - prev) if prev is not None else None,
                "pct_1d": _pct(last, prev),
                "pct_1w": _pct(last, _as_of(ds, ss, last_d - timedelta(days=7))),
                "pct_1m": _pct(last, _as_of(ds, ss, last_d - timedelta(days=30))),
                "pct_ytd": _pct(last, _as_of(ds, ss, date(last_d.year, 1, 1) - timedelta(days=1))),
                "pct_1y": _pct(last, _as_of(ds, ss, _minus_year(last_d))),
                "volume": vs[-1],
                "spark": spark,
            })
        out.sort(key=lambda r: (sector_rank(r["sector"]), r["name"]))
        return out

    # ---- history: full series for one commodity (charted detail) -----------------------------
    def history(self, code: str, window: str = "MAX") -> dict:
        meta = BY_CODE.get(code)
        cutoff: date | None = None
        if window in ("1Y", "5Y"):
            mx = self._conn.execute(
                "SELECT max(as_of_date) FROM commodities.price_daily "
                "WHERE commodity_code=%s AND series_type=%s",
                (code, SERIES),
            ).fetchone()
            if mx and mx[0] is not None:
                yrs = 1 if window == "1Y" else 5
                cutoff = mx[0] - timedelta(days=365 * yrs)
        rows = self._conn.execute(
            """
            SELECT as_of_date, settle, open, high, low, volume
              FROM commodities.price_daily
             WHERE commodity_code=%s AND series_type=%s
               AND (%s::date IS NULL OR as_of_date >= %s::date)
             ORDER BY as_of_date
            """,
            (code, SERIES, cutoff, cutoff),
        ).fetchall()
        return {
            "code": code,
            "name": meta.name if meta else code,
            "sector": meta.sector if meta else None,
            "unit": meta.unit if meta else None,
            "currency": meta.currency if meta else None,
            "exchange": meta.exchange if meta else None,
            "points": [
                {"as_of_date": d.isoformat(), "settle": float(s),
                 "open": float(o) if o is not None else None,
                 "high": float(h) if h is not None else None,
                 "low": float(low) if low is not None else None,
                 "volume": float(v) if v is not None else None}
                for d, s, o, h, low, v in rows
            ],
        }

    # ---- coverage: per-commodity day count + date range (data-monitor / validate) ------------
    def coverage(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT commodity_code, count(*) AS days, min(as_of_date) AS first,
                   max(as_of_date) AS last, max(source) AS source
              FROM commodities.price_daily WHERE series_type=%s
             GROUP BY commodity_code
            """,
            (SERIES,),
        ).fetchall()
        out = []
        for code, days, first, last, source in rows:
            meta = BY_CODE.get(code)
            out.append({
                "code": code,
                "name": meta.name if meta else code,
                "sector": meta.sector if meta else None,
                "days": days,
                "start_date": first.isoformat() if first else None,
                "end_date": last.isoformat() if last else None,
                "source": source,
            })
        out.sort(key=lambda r: (sector_rank(r["sector"] or ""), r["name"]))
        return out
