"""DB gateway for the altdata module (QRP-managed `altdata` schema)."""

from __future__ import annotations

import psycopg


class DbAltdataGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def series(self) -> list[dict]:
        """Mapped names with latest pageviews + an attention-spike ratio (7d avg / 30d avg)."""
        rows = self._conn.execute(
            """
            WITH latest AS (SELECT max(obs_date) AS d FROM altdata.pageview)
            SELECT m.composite_figi, m.ticker, m.name, m.article,
                   count(p.*) AS n_obs, max(p.obs_date) AS last,
                   (SELECT views FROM altdata.pageview x
                     WHERE x.composite_figi=m.composite_figi ORDER BY obs_date DESC LIMIT 1) AS latest,
                   avg(p.views) FILTER (WHERE p.obs_date > (SELECT d FROM latest) - 7)  AS avg7,
                   avg(p.views) FILTER (WHERE p.obs_date > (SELECT d FROM latest) - 30) AS avg30
              FROM altdata.wiki_map m
              LEFT JOIN altdata.pageview p USING (composite_figi)
             GROUP BY m.composite_figi, m.ticker, m.name, m.article
             ORDER BY latest DESC NULLS LAST
            """
        ).fetchall()
        out = []
        for figi, tk, name, article, n, last, latest, a7, a30 in rows:
            spike = (float(a7) / float(a30)) if a7 and a30 and float(a30) > 0 else None
            out.append({
                "composite_figi": figi,
                "ticker": tk,
                "name": name,
                "article": article,
                "n_obs": n,
                "last": last.isoformat() if last else None,
                "latest_views": int(latest) if latest is not None else None,
                "avg7": float(a7) if a7 is not None else None,
                "avg30": float(a30) if a30 is not None else None,
                "attention_spike": spike,
            })
        return out

    def observations(self, figi: str) -> dict | None:
        meta = self._conn.execute(
            "SELECT composite_figi, ticker, name, article FROM altdata.wiki_map "
            "WHERE composite_figi = %s",
            (figi,),
        ).fetchone()
        if not meta:
            return None
        obs = self._conn.execute(
            "SELECT obs_date, views FROM altdata.pageview WHERE composite_figi=%s ORDER BY obs_date",
            (figi,),
        ).fetchall()
        return {
            "composite_figi": meta[0],
            "ticker": meta[1],
            "name": meta[2],
            "article": meta[3],
            "observations": [{"date": d.isoformat(), "views": int(v)} for d, v in obs],
        }
