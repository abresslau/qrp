"""DB gateway for portfolio analytics.

Reads sym **read-only**: the portfolio's constituent daily returns (``fact_returns``
1D window, price return ``pr``) weighted by the latest stored weights, and a benchmark
daily series (``fact_index_returns`` 1D ``ret`` for an ``instrument`` of kind 'index').
Computes Sharpe, annualised return/vol, beta, Jensen's alpha, and benchmark-relative
metrics (active return, tracking error, information ratio) over the overlapping daily
series. Risk-free rate = 0. Never writes; never fabricates — coverage gaps are reported.
"""

from __future__ import annotations

import math
from datetime import date

import psycopg

# Annualisation: trading days per year (daily return series).
ANN = 252
# A trading date enters the portfolio series only when essentially all weight is priced,
# so the daily portfolio return isn't biased by a missing constituent.
COVERAGE_FLOOR = 0.99

# 1D window — a single daily return per as_of_date (see return_window).
_ONE_DAY_WINDOW = 1


def _window_start(window: str, max_date: date) -> date | None:
    """Map a window code to a start date (inclusive), or None for the full series."""
    w = (window or "ALL").upper()
    if w in ("ALL", "SI", "MAX"):
        return None
    if w == "YTD":
        return date(max_date.year, 1, 1)
    days = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "2Y": 730, "3Y": 1095}.get(w)
    if days is None:
        return None
    return date.fromordinal(max_date.toordinal() - days)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _sample_var(xs: list[float], mu: float) -> float:
    if len(xs) < 2:
        return 0.0
    return sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)


def _ann_return(daily: list[float]) -> float | None:
    """Geometric annualised return from a daily simple-return series."""
    if not daily:
        return None
    growth = 1.0
    for r in daily:
        growth *= 1.0 + r
    if growth <= 0:
        return None
    return growth ** (ANN / len(daily)) - 1.0


class DbAnalyticsGateway:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def benchmarks(self) -> list[dict]:
        """Index instruments that have a daily (1D) return series, for the selector."""
        rows = self._conn.execute(
            """
            SELECT i.sym_id, i.name, i.currency_code
              FROM instrument i
             WHERE i.kind = 'index'
               AND EXISTS (
                   SELECT 1 FROM fact_index_returns f
                    WHERE f.sym_id = i.sym_id AND f.window_id = %s AND f.ret IS NOT NULL
               )
             ORDER BY i.name
            """,
            (_ONE_DAY_WINDOW,),
        ).fetchall()
        return [{"id": sid, "name": name, "currency": ccy} for sid, name, ccy in rows]

    def _portfolio_daily(self, pid: int) -> tuple[date | None, dict[date, float], list[str]]:
        """Daily portfolio return series under the latest stored weights.

        Returns (as_of of the weights, {date: portfolio_return}, currencies held).
        A date is included only when >= COVERAGE_FLOOR of weight is priced that day.
        """
        asof = self._conn.execute(
            "SELECT max(as_of_date) FROM qrp.portfolio_weight WHERE portfolio_id = %s", (pid,)
        ).fetchone()[0]
        if asof is None:
            return None, {}, []

        total_w = float(
            self._conn.execute(
                "SELECT coalesce(sum(weight), 0) FROM qrp.portfolio_weight "
                "WHERE portfolio_id = %s AND as_of_date = %s",
                (pid, asof),
            ).fetchone()[0]
        )
        currencies = [
            r[0]
            for r in self._conn.execute(
                """
                SELECT DISTINCT s.currency_code
                  FROM qrp.portfolio_weight pw
                  JOIN securities s ON s.composite_figi = pw.composite_figi
                 WHERE pw.portfolio_id = %s AND pw.as_of_date = %s
                """,
                (pid, asof),
            ).fetchall()
        ]

        rows = self._conn.execute(
            """
            WITH w AS (
                SELECT composite_figi, weight
                  FROM qrp.portfolio_weight
                 WHERE portfolio_id = %s AND as_of_date = %s
            )
            SELECT fr.as_of_date,
                   sum(w.weight * fr.pr)  AS port_ret,
                   sum(w.weight)          AS covered_w
              FROM w
              JOIN fact_returns fr
                ON fr.composite_figi = w.composite_figi
               AND fr.window_id = %s
               AND fr.pr IS NOT NULL
             GROUP BY fr.as_of_date
            """,
            (pid, asof, _ONE_DAY_WINDOW),
        ).fetchall()

        series: dict[date, float] = {}
        if total_w > 0:
            for d, port_ret, covered_w in rows:
                if float(covered_w) / total_w >= COVERAGE_FLOOR:
                    # normalise by covered weight so the series is a pure return
                    series[d] = float(port_ret) / float(covered_w)
        return asof, series, sorted(c for c in currencies if c)

    def _benchmark_daily(self, benchmark_id: int) -> tuple[dict | None, dict[date, float]]:
        meta = self._conn.execute(
            "SELECT sym_id, name, currency_code FROM instrument WHERE sym_id = %s AND kind = 'index'",
            (benchmark_id,),
        ).fetchone()
        if not meta:
            return None, {}
        rows = self._conn.execute(
            "SELECT as_of_date, ret FROM fact_index_returns "
            "WHERE sym_id = %s AND window_id = %s AND ret IS NOT NULL",
            (benchmark_id, _ONE_DAY_WINDOW),
        ).fetchall()
        return (
            {"id": meta[0], "name": meta[1], "currency": meta[2]},
            {d: float(r) for d, r in rows},
        )

    def analytics(self, pid: int, benchmark_id: int, window: str) -> dict:
        asof, port_series, currencies = self._portfolio_daily(pid)
        bench_meta, bench_series = self._benchmark_daily(benchmark_id)

        result: dict = {
            "as_of": asof.isoformat() if asof else None,
            "window": (window or "ALL").upper(),
            "benchmark": bench_meta,
            "portfolio_currencies": currencies,
            "n_days": 0,
            "start": None,
            "end": None,
            "metrics": None,
            "warning": None,
        }
        if asof is None:
            result["warning"] = "no weights stored for this portfolio"
            return result
        if bench_meta is None:
            result["warning"] = "unknown benchmark"
            return result

        # Overlapping trading dates, oldest first.
        common = sorted(set(port_series) & set(bench_series))
        if common:
            start = _window_start(window, common[-1])
            if start is not None:
                common = [d for d in common if d >= start]

        if len(common) < 20:
            result["n_days"] = len(common)
            result["warning"] = (
                f"only {len(common)} overlapping daily observations "
                "(need >= 20 for stable statistics)"
            )
            if common:
                result["start"], result["end"] = common[0].isoformat(), common[-1].isoformat()
            return result

        p = [port_series[d] for d in common]
        b = [bench_series[d] for d in common]
        n = len(common)
        mp, mb = _mean(p), _mean(b)
        vp, vb = _sample_var(p, mp), _sample_var(b, mb)
        sp, sb = math.sqrt(vp), math.sqrt(vb)
        cov = sum((p[i] - mp) * (b[i] - mb) for i in range(n)) / (n - 1)
        beta = cov / vb if vb > 0 else None
        active = [p[i] - b[i] for i in range(n)]
        te = math.sqrt(_sample_var(active, _mean(active))) * math.sqrt(ANN)
        ann_p = _ann_return(p)
        ann_b = _ann_return(b)
        active_ann = (ann_p - ann_b) if (ann_p is not None and ann_b is not None) else None
        alpha_ann = (mp - beta * mb) * ANN if beta is not None else None

        result["n_days"] = n
        result["start"], result["end"] = common[0].isoformat(), common[-1].isoformat()
        result["metrics"] = {
            "ann_return": ann_p,
            "ann_vol": sp * math.sqrt(ANN),
            "sharpe": (mp / sp * math.sqrt(ANN)) if sp > 0 else None,
            "beta": beta,
            "alpha_ann": alpha_ann,
            "correlation": (cov / (sp * sb)) if sp > 0 and sb > 0 else None,
            "bench_ann_return": ann_b,
            "bench_ann_vol": sb * math.sqrt(ANN),
            "bench_sharpe": (mb / sb * math.sqrt(ANN)) if sb > 0 else None,
            "active_return": active_ann,
            "tracking_error": te,
            "information_ratio": (active_ann / te) if (active_ann is not None and te > 0) else None,
        }
        # Honest FX caveat: constituent returns are local-currency price returns.
        if bench_meta["currency"] and any(c != bench_meta["currency"] for c in currencies):
            result["warning"] = (
                f"portfolio holds {', '.join(currencies)} names but the benchmark is in "
                f"{bench_meta['currency']}; local-currency price returns are compared directly "
                "(unhedged FX not adjusted)."
            )
        return result
