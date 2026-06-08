"""DB gateway for the backtest module (QRP-managed `backtest` schema)."""

from __future__ import annotations

from datetime import date

import psycopg

from qrp_api.modules.backtest.engine import run_backtest


class DbBacktestGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self._conn.autocommit = True

    def run(self, factor: str, universe_id: str, top_pct: float) -> dict:
        start: date | None = None
        return run_backtest(self._conn, factor=factor, universe_id=universe_id,
                            top_pct=top_pct, start=start)

    def runs(self, limit: int = 25) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT run_id, created_at, factor, universe_id, top_pct, rebalance,
                   start_date, end_date, n_days, n_rebalances, summary
              FROM backtest.run ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [self._run_row(r) for r in rows]

    def get(self, run_id: int) -> dict | None:
        r = self._conn.execute(
            """
            SELECT run_id, created_at, factor, universe_id, top_pct, rebalance,
                   start_date, end_date, n_days, n_rebalances, summary
              FROM backtest.run WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
        if not r:
            return None
        out = self._run_row(r)
        pts = self._conn.execute(
            "SELECT obs_date, strat_cum, base_cum FROM backtest.point "
            "WHERE run_id = %s ORDER BY obs_date",
            (run_id,),
        ).fetchall()
        out["curve"] = [
            {"date": d.isoformat(), "strat": float(s), "base": float(b)} for d, s, b in pts
        ]
        return out

    def _run_row(self, r: tuple) -> dict:
        (rid, created, factor, uni, top, rebal, sd, ed, nd, nr, summary) = r
        return {
            "run_id": rid,
            "created_at": created.isoformat() if created else None,
            "factor": factor,
            "universe_id": uni,
            "top_pct": float(top),
            "rebalance": rebal,
            "start_date": sd.isoformat() if sd else None,
            "end_date": ed.isoformat() if ed else None,
            "n_days": nd,
            "n_rebalances": nr,
            "summary": summary,
        }
