"""DB gateway for the backtest module (QRP-managed `backtest` schema)."""

from __future__ import annotations

from datetime import date

import psycopg

from backtest.engine import run_backtest


class DbBacktestGateway:
    def __init__(
        self, conn: psycopg.Connection, sym_conn: psycopg.Connection | None = None
    ) -> None:
        self._conn = conn          # backtest DB — runs/points (read + write)
        self._sym = sym_conn       # sym package — the engine's read-only source (run only)
        self._conn.autocommit = True

    def run(self, factor: str, universe_id: str, top_pct: float | None, portfolios_gw=None,
            start_date: date | None = None, end_date: date | None = None,
            top_n: int | None = None, weighting: str = "equal", rebalance: str = "monthly",
            alt_conn=None, macro_conn=None) -> dict:
        res = run_backtest(self._sym, self._conn, factor=factor, universe_id=universe_id,
                           top_pct=top_pct, top_n=top_n, weighting=weighting,
                           rebalance=rebalance, start_date=start_date, end_date=end_date,
                           alt_conn=alt_conn, macro_conn=macro_conn)
        # Q6.4: optionally materialise the run as a paper Portfolio (persisted via the
        # portfolios package's own writer — module ownership respected, no cross-DB write here).
        if portfolios_gw is not None and res.get("run_id") and res.get("weight_vectors"):
            pid = portfolios_gw.create(
                f"Backtest #{res['run_id']}: {factor} · {universe_id}", "(backtest)", "USD"
            )
            for iso, vec in sorted(res["weight_vectors"].items()):
                portfolios_gw.upload_weights(pid, date.fromisoformat(iso), [(f, w) for f, w in vec])
            res["portfolio_id"] = pid
        return res

    def runs(self, limit: int = 25) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT run_id, created_at, factor, universe_id, top_pct, rebalance,
                   start_date, end_date, n_days, n_rebalances, summary, spec
              FROM backtest.run ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [self._run_row(r) for r in rows]

    def get(self, run_id: int) -> dict | None:
        r = self._conn.execute(
            """
            SELECT run_id, created_at, factor, universe_id, top_pct, rebalance,
                   start_date, end_date, n_days, n_rebalances, summary, spec
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
            {"obs_date": d.isoformat(), "strat": float(s), "base": float(b)} for d, s, b in pts
        ]
        return out

    def _run_row(self, r: tuple) -> dict:
        (rid, created, factor, uni, top, rebal, sd, ed, nd, nr, summary, spec) = r
        return {
            "run_id": rid,
            "created_at": created.isoformat() if created else None,
            "factor": factor,
            "universe_id": uni,
            # 0.0 is the legacy NOT-NULL sentinel for top_n runs — never serve it as data
            "top_pct": float(top) if top else None,
            "rebalance": rebal,
            "start_date": sd.isoformat() if sd else None,
            "end_date": ed.isoformat() if ed else None,
            "n_days": nd,
            "n_rebalances": nr,
            "summary": summary,
            "spec": spec,
        }
