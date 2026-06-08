"""DB gateway for the signal module (reads the QRP-managed `signal` schema + sym labels)."""

from __future__ import annotations

import psycopg


class DbSignalGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def factors(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT f.factor_key, f.name, f.description, f.direction,
                   count(DISTINCT s.universe_id) AS universes,
                   count(*) AS scores, max(s.as_of_date) AS as_of
              FROM signal.factor f
              LEFT JOIN signal.score s USING (factor_key)
             GROUP BY f.factor_key, f.name, f.description, f.direction
             ORDER BY f.name
            """
        ).fetchall()
        return [
            {
                "factor_key": k,
                "name": name,
                "description": desc,
                "direction": direction,
                "universes": u,
                "scores": sc,
                "as_of": ao.isoformat() if ao else None,
            }
            for k, name, desc, direction, u, sc, ao in rows
        ]

    def universes_for(self, factor_key: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT universe_id FROM signal.score WHERE factor_key=%s ORDER BY 1",
            (factor_key,),
        ).fetchall()
        return [r[0] for r in rows]

    def ranked(self, factor_key: str, universe_id: str, limit: int, bottom: bool) -> dict | None:
        meta = self._conn.execute(
            "SELECT factor_key, name, description, direction FROM signal.factor WHERE factor_key=%s",
            (factor_key,),
        ).fetchone()
        if not meta:
            return None
        as_of = self._conn.execute(
            "SELECT max(as_of_date) FROM signal.score WHERE factor_key=%s AND universe_id=%s",
            (factor_key, universe_id),
        ).fetchone()[0]
        order = "DESC" if bottom else "ASC"  # rank 1 = most favourable; bottom = least favourable
        rows = self._conn.execute(
            f"""
            SELECT s.composite_figi,
                   coalesce(tk.symbol_value, s.composite_figi) AS ticker,
                   sn.name, s.raw, s.zscore, s.rank, s.pctile
              FROM signal.score s
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = s.composite_figi AND y.symbol_type='ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
              LEFT JOIN LATERAL (
                  SELECT name FROM security_names z
                   WHERE z.composite_figi = s.composite_figi
                   ORDER BY (z.valid_to IS NULL) DESC, z.valid_from DESC LIMIT 1
              ) sn ON TRUE
             WHERE s.factor_key=%s AND s.universe_id=%s AND s.as_of_date=%s
             ORDER BY s.rank {order}
             LIMIT %s
            """,
            (factor_key, universe_id, as_of, limit),
        ).fetchall()
        return {
            "factor_key": meta[0],
            "name": meta[1],
            "description": meta[2],
            "direction": meta[3],
            "universe_id": universe_id,
            "as_of": as_of.isoformat() if as_of else None,
            "bottom": bottom,
            "constituents": [
                {
                    "ticker": tk,
                    "name": nm,
                    "raw": float(raw),
                    "zscore": float(z) if z is not None else None,
                    "rank": rk,
                    "pctile": float(p) if p is not None else None,
                }
                for _figi, tk, nm, raw, z, rk, p in rows
            ],
        }
