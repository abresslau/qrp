"""DB gateway for the rates module (reads the QRP-managed `rates` schema).

Country-aware: every read is scoped to one ``country`` (ISO-3166 alpha-2; the euro area fans out to
DE/FR/IT/ES + the ``EU`` aggregate). The UK (``GB``) keeps its rich curated spread set (real-curve
breakeven, gilt-OIS asset-swap); every other country gets generic curve spreads (2s10s / 5s30s /
2s5s10s fly) built from whatever its primary nominal curve publishes. ``compare_curves`` overlays a
standardized tenor axis across countries for cross-country comparison.
"""

from __future__ import annotations

import statistics as st
from datetime import date, timedelta

import psycopg

# UK curated spreads — legs are (country, curve_set, basis, rate_type, tenor); `fn` maps the ordered
# leg values (% p.a.) to the spread in `unit` ('bp' = a difference ×100; '%' = a level/breakeven).
_GB_SPREAD_SPECS: list[dict] = [
    {"key": "2s10s", "label": "2s10s (nominal)", "unit": "bp",
     "legs": [("GB", "glc", "nominal", "spot", 2.0), ("GB", "glc", "nominal", "spot", 10.0)],
     "fn": lambda v: (v[1] - v[0]) * 100.0},
    {"key": "2s5s10s", "label": "2s5s10s fly (nominal)", "unit": "bp",
     "legs": [("GB", "glc", "nominal", "spot", 2.0), ("GB", "glc", "nominal", "spot", 5.0),
              ("GB", "glc", "nominal", "spot", 10.0)],
     "fn": lambda v: (2.0 * v[1] - v[0] - v[2]) * 100.0},
    {"key": "be10y", "label": "10y breakeven (RPI)", "unit": "%",
     "legs": [("GB", "glc", "nominal", "spot", 10.0), ("GB", "glc", "real", "spot", 10.0)],
     "fn": lambda v: v[0] - v[1]},
    {"key": "asw10y", "label": "10y asset-swap proxy (gilt-OIS)", "unit": "bp",
     "legs": [("GB", "glc", "nominal", "spot", 10.0), ("GB", "ois", "nominal", "spot", 10.0)],
     "fn": lambda v: (v[0] - v[1]) * 100.0},
]
_WINDOWS = {"1Y": 365, "5Y": 365 * 5}  # MAX (or anything else) = no lower bound


class DbRatesGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    # ---- catalogue ---------------------------------------------------------------------------

    def countries(self) -> list[dict]:
        """Available countries with currency and the published date range — the country switcher's
        data. Deliberately NO ``count(DISTINCT as_of_date)``: that scans every row (6M+ for the UK)
        and is the documented distinct-count trap. ``min``/``max(as_of_date)`` are index-cheap."""
        rows = self._conn.execute(
            """
            SELECT country, max(currency) AS currency,
                   max(as_of_date) AS last, min(as_of_date) AS first
              FROM rates.curve_point
             GROUP BY country
             ORDER BY country
            """
        ).fetchall()
        return [
            {"country": r[0], "currency": r[1],
             "end_date": r[2].isoformat() if r[2] else None,
             "start_date": r[3].isoformat() if r[3] else None}
            for r in rows
        ]

    def curve_sets(self, country: str | None = None) -> list[dict]:
        """Available (country, curve_set, basis, rate_type) series + their day coverage."""
        rows = self._conn.execute(
            """
            SELECT country, curve_set, basis, rate_type, count(DISTINCT as_of_date) AS days,
                   min(as_of_date) AS first, max(as_of_date) AS last
              FROM rates.curve_point
             WHERE (%s::text IS NULL OR country = %s)
             GROUP BY country, curve_set, basis, rate_type
             ORDER BY country, curve_set, basis, rate_type
            """,
            (country, country),
        ).fetchall()
        return [
            {"country": r[0], "curve_set": r[1], "basis": r[2], "rate_type": r[3], "days": r[4],
             "start_date": r[5].isoformat() if r[5] else None,
             "end_date": r[6].isoformat() if r[6] else None}
            for r in rows
        ]

    def _primary_series(self, country: str) -> tuple[str, str, str] | None:
        """The country's headline nominal *level* curve = a (curve_set, basis, rate_type) preferring
        a level type (spot/par/yield, never forward) with the most tenors on its latest published
        day. Scoped to that one day (not all history) so it never scans the country's full row set —
        the UK alone has 6M+ rows, and a distinct-count over them is the documented trap."""
        row = self._conn.execute(
            """
            WITH latest AS (
                SELECT max(as_of_date) AS d FROM rates.curve_point
                 WHERE country = %s AND basis = 'nominal'
            )
            SELECT curve_set, basis, rate_type
              FROM rates.curve_point, latest
             WHERE country = %s AND basis = 'nominal' AND as_of_date = latest.d
             GROUP BY curve_set, basis, rate_type
             ORDER BY (rate_type = 'forward') ASC,
                      count(*) DESC,
                      CASE rate_type WHEN 'spot' THEN 0 WHEN 'par' THEN 1
                                     WHEN 'yield' THEN 2 ELSE 3 END,
                      curve_set
             LIMIT 1
            """,
            (country, country),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else None

    # ---- single-country curve ----------------------------------------------------------------

    def curve(
        self,
        country: str = "GB",
        curve_set: str = "glc",
        basis: str = "nominal",
        rate_type: str = "spot",
        as_of_date: date | None = None,
        *,
        vintage: str = "latest",
    ) -> dict:
        """The curve grid for one series as-of a date (<= as_of_date; latest if None).
        ``vintage='first'`` returns the immutable first-published values (PIT)."""
        anchor = self._conn.execute(
            """
            SELECT max(as_of_date) FROM rates.curve_point
             WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
               AND (%s::date IS NULL OR as_of_date <= %s::date)
            """,
            (country, curve_set, basis, rate_type, as_of_date, as_of_date),
        ).fetchone()
        anchored = anchor[0] if anchor else None
        base = {"country": country, "curve_set": curve_set, "basis": basis, "rate_type": rate_type,
                "vintage": vintage}
        if anchored is None:
            return {**base, "as_of_date": None, "source": None, "points": []}
        value_col = "first_value" if vintage == "first" else "value"
        rows = self._conn.execute(
            f"""
            SELECT tenor, {value_col}, source FROM rates.curve_point
             WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s AND as_of_date=%s
             ORDER BY tenor
            """,
            (country, curve_set, basis, rate_type, anchored),
        ).fetchall()
        # provenance: all nodes of one series/day share a source; surface it for the UI.
        source = rows[0][2] if rows else None
        return {**base, "as_of_date": anchored.isoformat(), "source": source,
                "points": [{"tenor": float(t), "value": float(v)} for t, v, _ in rows]}

    # ---- cross-country comparison ------------------------------------------------------------

    def compare_curves(
        self, countries: list[str], *, as_of_date: date | None = None
    ) -> list[dict]:
        """Each country's latest primary nominal curve on one tenor axis — the standardized overlay
        for cross-country comparison. Each country uses its own headline series (spot/par/yield are
        all nominal government rates to first order); the rate_type is labelled per country."""
        out: list[dict] = []
        for c in countries:
            primary = self._primary_series(c)
            if primary is None:
                continue
            cs, b, rt = primary
            curve = self.curve(c, cs, b, rt, as_of_date)
            cur = self._conn.execute(
                "SELECT max(currency) FROM rates.curve_point WHERE country=%s", (c,)
            ).fetchone()
            out.append({
                "country": c, "currency": cur[0] if cur else None,
                "curve_set": cs, "basis": b, "rate_type": rt,
                "as_of_date": curve["as_of_date"], "source": curve["source"],
                "points": curve["points"],
            })
        return out

    def compare_tenor(self, countries: list[str], tenor: float) -> list[dict]:
        """One tenor's daily history across countries (the primary nominal series each), for an
        overlaid time-series comparison (e.g. everyone's 10y)."""
        out: list[dict] = []
        for c in countries:
            primary = self._primary_series(c)
            if primary is None:
                continue
            cs, b, rt = primary
            rows = self._conn.execute(
                """
                SELECT as_of_date, value FROM rates.curve_point
                 WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
                   AND tenor=%s::numeric
                 ORDER BY as_of_date
                """,
                (c, cs, b, rt, tenor),
            ).fetchall()
            if rows:
                out.append({
                    "country": c, "curve_set": cs, "basis": b, "rate_type": rt, "tenor": tenor,
                    "points": [{"as_of_date": d.isoformat(), "value": float(v)} for d, v in rows],
                })
        return out

    # ---- derived spreads (derive-on-read; nothing persisted) ---------------------------------

    def _spread_specs(self, country: str) -> list[dict]:
        """UK keeps its curated set; every other country gets generic curve spreads built from its
        primary nominal series (2s10s / 5s30s / 2s5s10s fly), only where the legs are published."""
        if country == "GB":
            return _GB_SPREAD_SPECS
        primary = self._primary_series(country)
        if primary is None:
            return []
        cs, b, rt = primary
        tenors = {
            float(r[0]) for r in self._conn.execute(
                """
                SELECT DISTINCT tenor FROM rates.curve_point
                 WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
                """,
                (country, cs, b, rt),
            ).fetchall()
        }

        def leg(t: float) -> tuple:
            return (country, cs, b, rt, t)

        specs: list[dict] = []
        if {2.0, 10.0} <= tenors:
            specs.append({"key": "2s10s", "label": "2s10s", "unit": "bp",
                          "legs": [leg(2.0), leg(10.0)], "fn": lambda v: (v[1] - v[0]) * 100.0})
        if {2.0, 5.0, 10.0} <= tenors:
            specs.append({"key": "2s5s10s", "label": "2s5s10s fly", "unit": "bp",
                          "legs": [leg(2.0), leg(5.0), leg(10.0)],
                          "fn": lambda v: (2.0 * v[1] - v[0] - v[2]) * 100.0})
        if {5.0, 30.0} <= tenors:
            specs.append({"key": "5s30s", "label": "5s30s", "unit": "bp",
                          "legs": [leg(5.0), leg(30.0)], "fn": lambda v: (v[1] - v[0]) * 100.0})
        return specs

    def _spread_series(self, spec: dict) -> list[tuple[date, float]]:
        """One spread's full daily series. One query per distinct (country,set,basis,type) group;
        a date contributes only when all legs are present."""
        legs = spec["legs"]
        by_date: dict[date, dict[tuple, float]] = {}
        groups: dict[tuple[str, str, str, str], set[float]] = {}
        for co, cs, b, rt, tenor in legs:
            groups.setdefault((co, cs, b, rt), set()).add(tenor)
        for (co, cs, b, rt), tenors in groups.items():
            rows = self._conn.execute(
                # ``%s::numeric[]`` is load-bearing: tenor is NUMERIC and psycopg binds a Python
                # float list as float8[]; without the cast ``tenor = ANY(float8[])`` coerces and
                # bypasses the (…, tenor, …) index → a 1.2M-row seqscan per leg. The cast keeps it a
                # numeric=ANY(numeric[]) index probe (~0.3s vs ~3s).
                """
                SELECT as_of_date, tenor, value FROM rates.curve_point
                 WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
                   AND tenor = ANY(%s::numeric[])
                """,
                (co, cs, b, rt, list(tenors)),
            ).fetchall()
            for d, t, v in rows:
                by_date.setdefault(d, {})[(co, cs, b, rt, float(t))] = float(v)
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

    def spreads(self, country: str = "GB") -> list[dict]:
        """The country's spread set: current value + z-score + percentile (vs full stored history) +
        a compact sparkline. N/A (nulls) when a spread's legs aren't all published."""
        out: list[dict] = []
        for spec in self._spread_specs(country):
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

    def spread_history(self, key: str, window: str = "MAX", country: str = "GB") -> dict:
        """One spread's full daily history over a window (1Y/5Y/MAX) for the detail chart."""
        spec = next((s for s in self._spread_specs(country) if s["key"] == key), None)
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

    def curve_movie(
        self,
        country: str = "GB",
        curve_set: str = "glc",
        basis: str = "nominal",
        rate_type: str = "spot",
        frames: int = 120,
        start_date: date | None = None,
    ) -> dict:
        """A timelapse: up to ``frames`` curves evenly sampled (oldest→latest, first+last kept) over
        the history for one series. ``start_date`` bounds the window (else full history)."""
        frames = max(2, min(frames, 240))
        dates = [
            r[0]
            for r in self._conn.execute(
                """
                SELECT DISTINCT as_of_date FROM rates.curve_point
                 WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s ORDER BY as_of_date
                """,
                (country, curve_set, basis, rate_type),
            ).fetchall()
        ]
        if start_date is not None:
            dates = [d for d in dates if d >= start_date]
        out = {"country": country, "curve_set": curve_set, "basis": basis, "rate_type": rate_type,
               "frames": []}
        if not dates:
            return out
        if len(dates) <= frames:
            sampled = dates
        else:
            n = len(dates)
            idx = sorted({round(i * (n - 1) / (frames - 1)) for i in range(frames)})
            sampled = [dates[i] for i in idx]
        rows = self._conn.execute(
            """
            SELECT as_of_date, tenor, value FROM rates.curve_point
             WHERE country=%s AND curve_set=%s AND basis=%s AND rate_type=%s
               AND as_of_date = ANY(%s)
             ORDER BY as_of_date, tenor
            """,
            (country, curve_set, basis, rate_type, sampled),
        ).fetchall()
        by_date: dict = {}
        for d, t, v in rows:
            by_date.setdefault(d, []).append({"tenor": float(t), "value": float(v)})
        out["frames"] = [
            {"as_of_date": d.isoformat(), "points": by_date[d]} for d in sampled if d in by_date
        ]
        return out
