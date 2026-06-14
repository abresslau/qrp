"""DB gateway for the macro module (reads the QRP-managed `macro` schema)."""

from __future__ import annotations

import psycopg


class DbMacroGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def series(self) -> list[dict]:
        """Series catalog enriched for the research dashboard: latest value, point-in-time
        deltas (1m/3m/12m and year-to-date) anchored to each series' OWN latest observation
        date (the series have different frequencies and end dates), and a compact recent
        sparkline. All computed in one indexed lateral-join pass — no per-series round trips.
        Deltas are absolute (latest − prior), the natural change column for rate/%/index
        series alike; NULL when there is no comparison point that far back."""
        rows = self._conn.execute(
            """
            SELECT s.series_id, s.source, s.name, s.geo, s.unit, s.frequency, s.category,
                   agg.n_obs, agg.first, l.obs_date AS last, l.value AS latest,
                   v1.value AS v_1m, v3.value AS v_3m, v12.value AS v_12m, vye.value AS v_ye,
                   sp.spark
              FROM macro.series s
              LEFT JOIN LATERAL (
                  SELECT count(*) AS n_obs, min(obs_date) AS first
                    FROM macro.observation WHERE series_id = s.series_id
              ) agg ON TRUE
              LEFT JOIN LATERAL (
                  SELECT obs_date, value FROM macro.observation
                   WHERE series_id = s.series_id ORDER BY obs_date DESC LIMIT 1
              ) l ON TRUE
              LEFT JOIN LATERAL (
                  SELECT value FROM macro.observation
                   WHERE series_id = s.series_id AND obs_date <= l.obs_date - INTERVAL '1 month'
                   ORDER BY obs_date DESC LIMIT 1
              ) v1 ON TRUE
              LEFT JOIN LATERAL (
                  SELECT value FROM macro.observation
                   WHERE series_id = s.series_id AND obs_date <= l.obs_date - INTERVAL '3 months'
                   ORDER BY obs_date DESC LIMIT 1
              ) v3 ON TRUE
              LEFT JOIN LATERAL (
                  SELECT value FROM macro.observation
                   WHERE series_id = s.series_id AND obs_date <= l.obs_date - INTERVAL '12 months'
                   ORDER BY obs_date DESC LIMIT 1
              ) v12 ON TRUE
              LEFT JOIN LATERAL (
                  SELECT value FROM macro.observation
                   WHERE series_id = s.series_id AND obs_date < date_trunc('year', l.obs_date)
                   ORDER BY obs_date DESC LIMIT 1
              ) vye ON TRUE
              LEFT JOIN LATERAL (
                  SELECT array_agg(value ORDER BY obs_date) AS spark FROM (
                      SELECT obs_date, value FROM macro.observation
                       WHERE series_id = s.series_id ORDER BY obs_date DESC LIMIT 48
                  ) recent
              ) sp ON TRUE
             ORDER BY s.name, s.geo
            """
        ).fetchall()

        def _f(v) -> float | None:
            return float(v) if v is not None else None

        def _delta(latest, prior) -> float | None:
            if latest is None or prior is None:
                return None
            return float(latest) - float(prior)

        return [
            {
                "series_id": sid,
                "source": src,
                "name": name,
                "geo": geo,
                "unit": unit,
                "frequency": freq,
                "category": category,
                "n_obs": n,
                "start_date": f.isoformat() if f else None,
                "end_date": last.isoformat() if last else None,
                "latest": _f(latest),
                "chg_1m": _delta(latest, v1),
                "chg_3m": _delta(latest, v3),
                "chg_12m": _delta(latest, v12),
                "chg_ytd": _delta(latest, vye),
                "spark": [float(x) for x in spark] if spark else [],
            }
            for (sid, src, name, geo, unit, freq, category, n, f, last, latest,
                 v1, v3, v12, vye, spark) in rows
        ]

    def categories(self) -> list[dict]:
        """Distinct declared categories with series counts — read from the DB, never a
        hardcoded list, so the console submenu cannot drift from the data. NULL (a series
        ingested before categorisation, or whose last categorising fetch failed) is
        excluded: the submenu only offers categories that actually resolve."""
        rows = self._conn.execute(
            """
            SELECT category, count(*) AS n_series
              FROM macro.series
             WHERE category IS NOT NULL
             GROUP BY category
             ORDER BY category
            """
        ).fetchall()
        return [{"category": c, "n_series": n} for c, n in rows]

    def observations(self, series_id: str) -> dict | None:
        meta = self._conn.execute(
            "SELECT series_id, source, name, geo, unit, frequency, category FROM macro.series "
            "WHERE series_id = %s",
            (series_id,),
        ).fetchone()
        if not meta:
            return None
        obs = self._conn.execute(
            "SELECT obs_date, value FROM macro.observation WHERE series_id = %s ORDER BY obs_date",
            (series_id,),
        ).fetchall()
        return {
            "series_id": meta[0],
            "source": meta[1],
            "name": meta[2],
            "geo": meta[3],
            "unit": meta[4],
            "frequency": meta[5],
            "category": meta[6],
            "observations": [{"obs_date": d.isoformat(), "value": float(v)} for d, v in obs],
        }
