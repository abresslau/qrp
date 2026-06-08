"""DB gateway for the macro module (reads the QRP-managed `macro` schema)."""

from __future__ import annotations

import psycopg


class DbMacroGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def series(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT s.series_id, s.source, s.name, s.geo, s.unit, s.frequency,
                   count(o.*) AS n_obs, min(o.obs_date) AS first, max(o.obs_date) AS last,
                   (SELECT value FROM macro.observation o2
                     WHERE o2.series_id = s.series_id ORDER BY o2.obs_date DESC LIMIT 1) AS latest
              FROM macro.series s
              LEFT JOIN macro.observation o USING (series_id)
             GROUP BY s.series_id, s.source, s.name, s.geo, s.unit, s.frequency
             ORDER BY s.name, s.geo
            """
        ).fetchall()
        return [
            {
                "series_id": sid,
                "source": src,
                "name": name,
                "geo": geo,
                "unit": unit,
                "frequency": freq,
                "n_obs": n,
                "first": f.isoformat() if f else None,
                "last": l.isoformat() if l else None,
                "latest": float(latest) if latest is not None else None,
            }
            for sid, src, name, geo, unit, freq, n, f, l, latest in rows
        ]

    def observations(self, series_id: str) -> dict | None:
        meta = self._conn.execute(
            "SELECT series_id, source, name, geo, unit, frequency FROM macro.series "
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
            "observations": [{"date": d.isoformat(), "value": float(v)} for d, v in obs],
        }
