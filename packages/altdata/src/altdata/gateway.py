"""DB gateway for the altdata module (QRP-managed `altdata` schema)."""

from __future__ import annotations

import psycopg

# Window comparison: sum over the trailing window ÷ window DAYS (calendar-day average with
# implicit zeros). The anchor follows each source's missing-day semantics:
# - sec_edgar (true-zero counts): anchored on CURRENT_DATE — a day without filings is a real
#   zero all the way to today, so an idle filer's 7d rate honestly decays to 0 and a spike
#   appears only when there WAS recent activity. Anchoring on the series' own last obs would
#   guarantee an event inside the 7d window (a quarterly filer would read a perpetual
#   ~30/7 ≈ 4.29× "spike"). NULL sums coalesce to 0 for the same reason.
# - wikipedia (observation-lagged, missing ≠ zero): anchored on the series' OWN latest
#   obs_date — the feed trails today by a few days and a global/today anchor would deflate
#   the rate with days that are missing, not zero. For gapless daily data this matches a
#   plain average; a mid-window gap deflates it slightly (documented, accepted).
# A future true-zero source extends the CASE predicates (or promotes the flag to a schema
# column — ledgered).
_SERIES_SQL = """
WITH bounds AS (
    SELECT composite_figi, source, metric, max(obs_date) AS last_date, count(*) AS n_obs
      FROM altdata.observation
     GROUP BY 1, 2, 3
), anchored AS (
    SELECT b.*,
           CASE WHEN b.source = 'sec_edgar' THEN CURRENT_DATE ELSE b.last_date END AS anchor,
           (b.source = 'sec_edgar') AS zero_fill
      FROM bounds b
), rates AS (
    SELECT a.composite_figi, a.source, a.metric, a.last_date, a.n_obs,
           CASE WHEN a.zero_fill
                THEN coalesce(sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 7), 0) / 7.0
                ELSE sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 7) / 7.0
           END AS avg7,
           CASE WHEN a.zero_fill
                THEN coalesce(sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 30), 0) / 30.0
                ELSE sum(o.value) FILTER (WHERE o.obs_date > a.anchor - 30) / 30.0
           END AS avg30,
           max(o.value) FILTER (WHERE o.obs_date = a.last_date) AS latest_value
      FROM anchored a
      JOIN altdata.observation o USING (composite_figi, source, metric)
     GROUP BY a.composite_figi, a.source, a.metric, a.last_date, a.n_obs, a.anchor, a.zero_fill
)
SELECT s.composite_figi, s.ticker, s.name, s.source, s.metric, s.detail, s.unit,
       coalesce(r.n_obs, 0) AS n_obs, r.last_date, r.latest_value, r.avg7, r.avg30
  FROM altdata.series s
  LEFT JOIN rates r USING (composite_figi, source, metric)
 ORDER BY s.ticker, s.source, s.metric
"""


class DbAltdataGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def series(self) -> list[dict]:
        """All series with latest value + 7d/30d calendar-day rates and the spike ratio."""
        rows = self._conn.execute(_SERIES_SQL).fetchall()
        out = []
        for figi, tk, name, source, metric, detail, unit, n, last, latest, a7, a30 in rows:
            spike = (
                float(a7) / float(a30)
                if a7 is not None and a30 is not None and float(a30) > 0
                else None
            )
            out.append({
                "composite_figi": figi,
                "ticker": tk,
                "name": name,
                "source": source,
                "metric": metric,
                "detail": detail,
                "unit": unit,
                "n_obs": n,
                "as_of_date": last.isoformat() if last else None,
                "latest_value": float(latest) if latest is not None else None,
                "avg7": float(a7) if a7 is not None else None,
                "avg30": float(a30) if a30 is not None else None,
                "attention_spike": spike,
            })
        return out

    def observations(self, figi: str, source: str, metric: str) -> dict | None:
        meta = self._conn.execute(
            "SELECT composite_figi, ticker, name, source, metric, detail, unit "
            "FROM altdata.series WHERE composite_figi=%s AND source=%s AND metric=%s",
            (figi, source, metric),
        ).fetchone()
        if not meta:
            return None
        obs = self._conn.execute(
            "SELECT obs_date, value FROM altdata.observation "
            "WHERE composite_figi=%s AND source=%s AND metric=%s ORDER BY obs_date",
            (figi, source, metric),
        ).fetchall()
        return {
            "composite_figi": meta[0],
            "ticker": meta[1],
            "name": meta[2],
            "source": meta[3],
            "metric": meta[4],
            "detail": meta[5],
            "unit": meta[6],
            "observations": [{"obs_date": d.isoformat(), "value": float(v)} for d, v in obs],
        }
