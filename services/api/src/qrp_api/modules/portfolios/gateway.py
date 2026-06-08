"""DB gateway for the portfolios module.

Writes ONLY to the QRP-own `qrp` schema; reads sym (securities, symbology, fact_returns,
return_window) read-only. Never mutates sym. Weights resolve to sym_id at upload;
unresolved identifiers are reported, never fabricated.
"""

from __future__ import annotations

from datetime import date

import psycopg


class DbPortfolioGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self._conn.autocommit = True  # portfolios are small interactive writes

    # ---- portfolios ----
    def create(self, name: str, client: str = "", base_currency: str = "USD") -> int:
        row = self._conn.execute(
            "INSERT INTO qrp.portfolio (name, client, base_currency) VALUES (%s, %s, %s) "
            "RETURNING portfolio_id",
            (name, client, base_currency),
        ).fetchone()
        return int(row[0])

    def list(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT p.portfolio_id, p.name, p.client, p.base_currency, p.created_at,
                   count(w.composite_figi) AS n_weights,
                   max(w.as_of_date) AS latest_as_of
              FROM qrp.portfolio p
              LEFT JOIN qrp.portfolio_weight w USING (portfolio_id)
             GROUP BY p.portfolio_id, p.name, p.client, p.base_currency, p.created_at
             ORDER BY p.created_at DESC
            """
        ).fetchall()
        return [
            {
                "portfolio_id": pid,
                "name": name,
                "client": client,
                "base_currency": ccy,
                "created_at": ca.isoformat() if ca else None,
                "n_weights": n,
                "latest_as_of": la.isoformat() if la else None,
            }
            for pid, name, client, ccy, ca, n, la in rows
        ]

    def get(self, pid: int) -> dict | None:
        meta = self._conn.execute(
            "SELECT portfolio_id, name, client, base_currency, created_at "
            "FROM qrp.portfolio WHERE portfolio_id = %s",
            (pid,),
        ).fetchone()
        if not meta:
            return None
        dates = [
            d.isoformat()
            for (d,) in self._conn.execute(
                "SELECT DISTINCT as_of_date FROM qrp.portfolio_weight "
                "WHERE portfolio_id = %s ORDER BY as_of_date DESC",
                (pid,),
            ).fetchall()
        ]
        latest = dates[0] if dates else None
        weights: list[dict] = []
        if latest:
            weights = [
                {
                    "figi": figi,
                    "ticker": tk or figi,
                    "name": nm,
                    "weight": float(w),
                }
                for figi, tk, nm, w in self._conn.execute(
                    """
                    SELECT pw.composite_figi,
                           coalesce(tk.symbol_value, pw.composite_figi),
                           sn.name, pw.weight
                      FROM qrp.portfolio_weight pw
                      LEFT JOIN LATERAL (
                          SELECT symbol_value FROM security_symbology y
                           WHERE y.composite_figi = pw.composite_figi AND y.symbol_type = 'ticker'
                           ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
                      ) tk ON TRUE
                      LEFT JOIN LATERAL (
                          SELECT name FROM security_names z
                           WHERE z.composite_figi = pw.composite_figi
                           ORDER BY (z.valid_to IS NULL) DESC, z.valid_from DESC LIMIT 1
                      ) sn ON TRUE
                     WHERE pw.portfolio_id = %s AND pw.as_of_date = %s
                     ORDER BY pw.weight DESC
                    """,
                    (pid, latest),
                ).fetchall()
            ]
        return {
            "portfolio_id": meta[0],
            "name": meta[1],
            "client": meta[2],
            "base_currency": meta[3],
            "created_at": meta[4].isoformat() if meta[4] else None,
            "as_of_dates": dates,
            "latest_as_of": latest,
            "weights": weights,
        }

    # ---- weights ----
    def _resolve_figi(self, ident: str) -> str | None:
        ident = ident.strip()
        if not ident:
            return None
        direct = self._conn.execute(
            "SELECT composite_figi FROM securities WHERE composite_figi = %s", (ident,)
        ).fetchone()
        if direct:
            return direct[0]
        row = self._conn.execute(
            "SELECT composite_figi FROM security_symbology WHERE symbol_type = 'ticker' "
            "AND upper(symbol_value) = upper(%s) "
            "ORDER BY (valid_to IS NULL) DESC, valid_from DESC LIMIT 1",
            (ident,),
        ).fetchone()
        return row[0] if row else None

    def upload_weights(
        self, pid: int, as_of: date, items: list[tuple[str, float]]
    ) -> dict:
        stored = 0
        unresolved: list[str] = []
        for ident, weight in items:
            figi = self._resolve_figi(ident)
            if not figi:
                unresolved.append(ident)
                continue
            self._conn.execute(
                "INSERT INTO qrp.portfolio_weight (portfolio_id, as_of_date, composite_figi, weight) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (portfolio_id, as_of_date, composite_figi) DO UPDATE SET weight = EXCLUDED.weight",
                (pid, as_of, figi, weight),
            )
            stored += 1
        return {"stored": stored, "unresolved": unresolved, "as_of": as_of.isoformat()}

    # ---- returns / PnL engine ----
    def returns(self, pid: int, window_code: str) -> dict:
        c = self._conn
        asof = c.execute(
            "SELECT max(as_of_date) FROM qrp.portfolio_weight WHERE portfolio_id = %s", (pid,)
        ).fetchone()[0]
        wrow = c.execute(
            "SELECT window_id, code FROM return_window WHERE code = %s", (window_code,)
        ).fetchone()
        if not wrow:
            wrow = c.execute(
                "SELECT window_id, code FROM return_window WHERE code = 'YTD'"
            ).fetchone()
        window_id, window = wrow
        if asof is None:
            return {"window": window, "as_of": None, "constituents": [], "n_constituents": 0,
                    "n_with_return": 0, "total_weight": 0.0, "covered_weight": 0.0,
                    "portfolio_return": None, "portfolio_return_normalized": None}

        rows = c.execute(
            """
            SELECT pw.composite_figi,
                   coalesce(tk.symbol_value, pw.composite_figi) AS ticker,
                   pw.weight, fr.pr
              FROM qrp.portfolio_weight pw
              LEFT JOIN LATERAL (
                  SELECT symbol_value FROM security_symbology y
                   WHERE y.composite_figi = pw.composite_figi AND y.symbol_type = 'ticker'
                   ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
              ) tk ON TRUE
              LEFT JOIN LATERAL (
                  SELECT pr FROM fact_returns x
                   WHERE x.composite_figi = pw.composite_figi AND x.window_id = %s
                   ORDER BY as_of_date DESC LIMIT 1
              ) fr ON TRUE
             WHERE pw.portfolio_id = %s AND pw.as_of_date = %s
            """,
            (window_id, pid, asof),
        ).fetchall()

        total_w = 0.0
        covered_w = 0.0
        port_ret = 0.0
        constituents = []
        for figi, ticker, weight, pr in rows:
            w = float(weight)
            total_w += w
            contrib = None
            if pr is not None:
                covered_w += w
                contrib = w * float(pr)
                port_ret += contrib
            constituents.append(
                {"ticker": ticker, "weight": w, "ret": float(pr) if pr is not None else None,
                 "contribution": contrib}
            )
        constituents.sort(key=lambda x: abs(x["contribution"]) if x["contribution"] is not None else -1,
                          reverse=True)
        return {
            "window": window,
            "as_of": asof.isoformat(),
            "n_constituents": len(rows),
            "n_with_return": sum(1 for _ in rows if _[3] is not None),
            "total_weight": total_w,
            "covered_weight": covered_w,
            "portfolio_return": port_ret if covered_w > 0 else None,
            "portfolio_return_normalized": (port_ret / covered_w) if covered_w > 0 else None,
            "constituents": constituents,
        }
