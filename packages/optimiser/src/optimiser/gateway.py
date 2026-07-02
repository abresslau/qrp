"""DB gateway for the optimiser module (QRP-managed `optimiser` schema)."""

from __future__ import annotations

import psycopg

from optimiser.engine import solve as _solve


class DbOptimiserGateway:
    def __init__(
        self, conn: psycopg.Connection, sym_conn: psycopg.Connection | None = None
    ) -> None:
        self._conn = conn          # optimiser DB — solutions/weights (read + write)
        self._sym = sym_conn       # sym package — the engine's read-only source (solve only)
        self._conn.autocommit = True

    def solve(self, universe_id: str, method: str, n: int, lookback: int,
              max_weight: float | None = None, signal_tilt: dict | None = None,
              holdout_days: int = 0, cov_method: str = "shrinkage", portfolios_gw=None,
              factor: str = "sharpe_tr", long_n: int | None = None, long_pct: float | None = None,
              short_n: int | None = None, short_pct: float | None = None,
              net_target: float = 0.0, gross_target: float = 1.0,
              alt_conn=None, macro_conn=None) -> dict:
        # Membership lives in the universe DB; fact_returns in the equity DB — open both for the
        # solve (roster-fetch + return matrix), scoped to this call.
        from optimiser.db import connect

        with connect("universe") as u_conn, connect("equity") as eq_conn:
            return _solve(self._sym, self._conn, universe_id=universe_id, method=method, n=n,
                          lookback=lookback, max_weight=max_weight, signal_tilt=signal_tilt,
                          holdout_days=holdout_days, cov_method=cov_method,
                          portfolios_gw=portfolios_gw, factor=factor, long_n=long_n,
                          long_pct=long_pct, short_n=short_n, short_pct=short_pct,
                          net_target=net_target, gross_target=gross_target,
                          alt_conn=alt_conn, macro_conn=macro_conn,
                          u_conn=u_conn, eq_conn=eq_conn)

    def solutions(self, limit: int = 25) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT solution_id, created_at, universe_id, method, n_assets, lookback_days,
                   exp_return, exp_vol, sharpe, ew_vol, summary, spec
              FROM optimiser.solution ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, solution_id: int) -> dict | None:
        r = self._conn.execute(
            """
            SELECT solution_id, created_at, universe_id, method, n_assets, lookback_days,
                   exp_return, exp_vol, sharpe, ew_vol, summary, spec
              FROM optimiser.solution WHERE solution_id = %s
            """,
            (solution_id,),
        ).fetchone()
        if not r:
            return None
        out = self._row(r)
        w = self._conn.execute(
            "SELECT composite_figi, ticker, weight FROM optimiser.weight "
            "WHERE solution_id = %s ORDER BY weight DESC",
            (solution_id,),
        ).fetchall()
        out["weights"] = [
            {"figi": f, "ticker": tk, "weight": float(wt)} for f, tk, wt in w
        ]
        return out

    def _row(self, r: tuple) -> dict:
        (sid, created, uni, method, n, lb, er, ev, sh, ew, summary, spec) = r
        return {
            "solution_id": sid,
            "created_at": created.isoformat() if created else None,
            "universe_id": uni,
            "method": method,
            "n_assets": n,
            "lookback_days": lb,
            "exp_return": float(er) if er is not None else None,
            "exp_vol": float(ev) if ev is not None else None,
            "sharpe": float(sh) if sh is not None else None,
            "ew_vol": float(ew) if ew is not None else None,
            "summary": summary,
            "spec": spec,
        }
