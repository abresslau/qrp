"""DB gateway for the rates module (reads the QRP-managed `rates` schema)."""

from __future__ import annotations

import statistics as st
from datetime import date, timedelta

import psycopg

# Standard derived spread set (derive-on-read). Each leg = (curve_set, basis, rate_type, tenor);
# `fn` maps the ordered leg values (% p.a.) to the spread value in `unit`. `bp` = a difference
# scaled ×100; `%` = a level (breakeven). A spread with any unpublished leg reads N/A (null).
_SPREAD_SPECS: list[dict] = [
    {"key": "2s10s", "label": "2s10s (nominal)", "unit": "bp",
     "legs": [("glc", "nominal", "spot", 2.0), ("glc", "nominal", "spot", 10.0)],
     "fn": lambda v: (v[1] - v[0]) * 100.0},
    {"key": "2s5s10s", "label": "2s5s10s fly (nominal)", "unit": "bp",
     "legs": [("glc", "nominal", "spot", 2.0), ("glc", "nominal", "spot", 5.0),
              ("glc", "nominal", "spot", 10.0)],
     "fn": lambda v: (2.0 * v[1] - v[0] - v[2]) * 100.0},
    {"key": "be10y", "label": "10y breakeven (RPI)", "unit": "%",
     "legs": [("glc", "nominal", "spot", 10.0), ("glc", "real", "spot", 10.0)],
     "fn": lambda v: v[0] - v[1]},
    {"key": "asw10y", "label": "10y asset-swap proxy (gilt-OIS)", "unit": "bp",
     "legs": [("glc", "nominal", "spot", 10.0), ("ois", "nominal", "spot", 10.0)],
     "fn": lambda v: (v[0] - v[1]) * 100.0},
]
_SPEC_BY_KEY = {s["key"]: s for s in _SPREAD_SPECS}
_WINDOWS = {"1Y": 365, "5Y": 365 * 5}  # MAX (or anything else) = no lower bound


class DbRatesGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def curve_sets(self) -> list[dict]:
        """Available (curve_set, basis, rate_type) series with their day/node coverage."""
        rows = self._conn.execute(
            """
            SELECT curve_set, basis, rate_type, count(DISTINCT as_of_date) AS days,
                   min(as_of_date) AS first, max(as_of_date) AS last
              FROM rates.curve_point
             GROUP BY curve_set, basis, rate_type
             ORDER BY curve_set, basis, rate_type
            """
        ).fetchall()
        return [
            {
                "curve_set": r[0], "basis": r[1], "rate_type": r[2], "days": r[3],
                "start_date": r[4].isoformat() if r[4] else None,
                "end_date": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]

    def curve(
        self,
        curve_set: str = "glc",
        basis: str = "nominal",
        rate_type: str = "spot",
        as_of_date: date | None = None,
        *,
        vintage: str = "latest",
    ) -> dict:
        """The curve grid for one (curve_set, basis, rate_type) as-of a date (<= as_of_date; latest
        if None). ``vintage='first'`` returns the immutable first-published values (PIT)."""
        anchor = self._conn.execute(
            """
            SELECT max(as_of_date) FROM rates.curve_point
             WHERE curve_set=%s AND basis=%s AND rate_type=%s
               AND (%s::date IS NULL OR as_of_date <= %s::date)
            """,
            (curve_set, basis, rate_type, as_of_date, as_of_date),
        ).fetchone()
        anchored = anchor[0] if anchor else None
        if anchored is None:
            return {
                "curve_set": curve_set, "basis": basis, "rate_type": rate_type,
                "vintage": vintage, "as_of_date": None, "points": [],
            }
        value_col = "first_value" if vintage == "first" else "value"
        rows = self._conn.execute(
            f"""
            SELECT tenor, {value_col}, first_published_at, last_changed_at
              FROM rates.curve_point
             WHERE curve_set=%s AND basis=%s AND rate_type=%s AND as_of_date=%s
             ORDER BY tenor
            """,
            (curve_set, basis, rate_type, anchored),
        ).fetchall()
        return {
            "curve_set": curve_set, "basis": basis, "rate_type": rate_type, "vintage": vintage,
            "as_of_date": anchored.isoformat(),
            "points": [{"tenor": float(t), "value": float(v)} for t, v, _, _ in rows],
        }

    # ---- derived analytics (derive-on-read; nothing persisted) -------------------------------

    def _spread_series(self, spec: dict) -> list[tuple[date, float]]:
        """Compute one spread's full daily series. One query per distinct (set,basis,type) leg-group
        (no per-date round trips); a date contributes only when all legs are present."""
        legs = spec["legs"]
        # {as_of_date: {(cs,b,rt,tenor): value}}
        by_date: dict[date, dict[tuple, float]] = {}
        groups: dict[tuple[str, str, str], set[float]] = {}
        for cs, b, rt, tenor in legs:
            groups.setdefault((cs, b, rt), set()).add(tenor)
        for (cs, b, rt), tenors in groups.items():
            rows = self._conn.execute(
                """
                SELECT as_of_date, tenor, value FROM rates.curve_point
                 WHERE curve_set=%s AND basis=%s AND rate_type=%s AND tenor = ANY(%s)
                """,
                (cs, b, rt, list(tenors)),
            ).fetchall()
            for d, t, v in rows:
                by_date.setdefault(d, {})[(cs, b, rt, float(t))] = float(v)
        series: list[tuple[date, float]] = []
        for d in sorted(by_date):
            vals = [by_date[d].get(leg) for leg in legs]
            if all(x is not None for x in vals):
                series.append((d, spec["fn"](vals)))
        return series

    @staticmethod
    def _zscore_percentile(
        values: list[float], current: float
    ) -> tuple[float | None, float | None]:
        if len(values) < 2:
            return None, None
        mu = st.mean(values)
        sd = st.pstdev(values)
        z = (current - mu) / sd if sd > 0 else 0.0
        pctile = 100.0 * sum(1 for v in values if v <= current) / len(values)
        return z, pctile

    def spreads(self) -> list[dict]:
        """The standard spread set: current value + z-score + percentile (vs the full stored
        history) + a compact sparkline. N/A (nulls) when a spread's legs aren't all published."""
        out: list[dict] = []
        for spec in _SPREAD_SPECS:
            series = self._spread_series(spec)
            row = {"key": spec["key"], "label": spec["label"], "unit": spec["unit"],
                   "value": None, "zscore": None, "percentile": None, "as_of_date": None,
                   "history": []}
            if series:
                values = [v for _, v in series]
                cur_date, cur_val = series[-1]
                z, pct = self._zscore_percentile(values, cur_val)
                row.update(
                    value=cur_val, zscore=z, percentile=pct, as_of_date=cur_date.isoformat(),
                    history=[{"as_of_date": d.isoformat(), "value": v} for d, v in series[-60:]],
                )
            out.append(row)
        return out

    def spread_history(self, key: str, window: str = "MAX") -> dict:
        """One spread's full daily history over a window (1Y/5Y/MAX) for the detail chart."""
        spec = _SPEC_BY_KEY.get(key)
        if spec is None:
            return {"key": key, "label": key, "unit": "bp", "points": []}
        series = self._spread_series(spec)
        days = _WINDOWS.get(window)
        if days and series:
            floor = series[-1][0] - timedelta(days=days)
            series = [(d, v) for d, v in series if d >= floor]
        return {
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "points": [{"as_of_date": d.isoformat(), "value": v} for d, v in series],
        }
