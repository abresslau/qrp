"""DB gateway for the signal module (reads the QRP-managed `signal` schema + sym labels)."""

from __future__ import annotations

import psycopg


class DbSignalGateway:
    def __init__(
        self, conn: psycopg.Connection, sym_conn: psycopg.Connection | None = None
    ) -> None:
        self._conn = conn      # signal DB — this package's own factors + scores
        self._sym = sym_conn   # sym DB (the sym package) — security labels, enriched in-app

    def _labels(self, figis: list[str]) -> tuple[dict, dict]:
        """Ticker + name for ``figis`` read from the sym package and merged in Python.

        Cross-package read pattern under DB-per-package: signal owns scores in its own
        database, sym owns the labels in another — so we read each and assemble in the service
        layer rather than via a cross-database SQL join (live DuckDB federation would be the
        alternative; either way the join leaves the database).
        """
        if not self._sym or not figis:
            return {}, {}
        tickers = dict(
            self._sym.execute(
                "SELECT DISTINCT ON (composite_figi) composite_figi, symbol_value "
                "FROM security_symbology WHERE composite_figi = ANY(%s) AND symbol_type = 'ticker' "
                "ORDER BY composite_figi, (valid_to IS NULL) DESC, valid_from DESC",
                (figis,),
            ).fetchall()
        )
        names = dict(
            self._sym.execute(
                "SELECT DISTINCT ON (composite_figi) composite_figi, name "
                "FROM security_names WHERE composite_figi = ANY(%s) "
                "ORDER BY composite_figi, (valid_to IS NULL) DESC, valid_from DESC",
                (figis,),
            ).fetchall()
        )
        return tickers, names

    def factors(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT f.factor_key, f.name, f.description, f.direction,
                   count(DISTINCT s.universe_id) AS universes,
                   count(*) AS scores, max(s.as_of_date) AS as_of_date
              FROM signals.factor f
              LEFT JOIN signals.score s USING (factor_key)
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
                "as_of_date": ao.isoformat() if ao else None,
            }
            for k, name, desc, direction, u, sc, ao in rows
        ]

    def universes_for(self, factor_key: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT universe_id FROM signals.score WHERE factor_key=%s ORDER BY 1",
            (factor_key,),
        ).fetchall()
        return [r[0] for r in rows]

    def ranked(self, factor_key: str, universe_id: str, limit: int, bottom: bool) -> dict | None:
        meta = self._conn.execute(
            "SELECT factor_key, name, description, direction FROM signals.factor WHERE factor_key=%s",
            (factor_key,),
        ).fetchone()
        if not meta:
            return None
        as_of_date = self._conn.execute(
            "SELECT max(as_of_date) FROM signals.score WHERE factor_key=%s AND universe_id=%s",
            (factor_key, universe_id),
        ).fetchone()[0]
        order = "DESC" if bottom else "ASC"  # rank 1 = most favourable; bottom = least favourable
        rows = self._conn.execute(
            f"""
            SELECT composite_figi, raw, zscore, rank, pctile
              FROM signals.score
             WHERE factor_key=%s AND universe_id=%s AND as_of_date=%s
             ORDER BY rank {order}
             LIMIT %s
            """,
            (factor_key, universe_id, as_of_date, limit),
        ).fetchall()
        tickers, names = self._labels([r[0] for r in rows])  # enrich from the sym package, in-app
        return {
            "factor_key": meta[0],
            "name": meta[1],
            "description": meta[2],
            "direction": meta[3],
            "universe_id": universe_id,
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "bottom": bottom,
            "constituents": [
                {
                    "ticker": tickers.get(figi, figi),
                    "name": names.get(figi),
                    "raw": float(raw),
                    "zscore": float(z) if z is not None else None,
                    "rank": rk,
                    "pctile": float(p) if p is not None else None,
                }
                for figi, raw, z, rk, p in rows
            ],
        }
