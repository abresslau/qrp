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


# Every window code analytics understands; anything else is a 422 at the router.
VALID_WINDOWS = ("ALL", "SI", "MAX", "YTD", "1M", "3M", "6M", "1Y", "2Y", "3Y")


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
    def __init__(self, conn: psycopg.Connection, sym_conn: psycopg.Connection | None = None) -> None:
        self._conn = conn      # qrp DB — portfolio weights
        self._sym = sym_conn    # sym package — fact_returns / fact_index_returns / instrument / securities

    def benchmarks(self) -> list[dict]:
        """Index instruments that have a daily (1D) return series, for the selector."""
        rows = self._sym.execute(
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

        Returns (as_of_date of the weights, {date: portfolio_return}, currencies held).
        A date is included only when >= COVERAGE_FLOOR of weight is priced that day.
        """
        # Weights through the OWNING package's seam (Story A.1) — the SQL has one
        # owner; the weight×return series is still assembled IN-APP (cross-database:
        # weights here, fact_returns in the sym package), never a cross-DB SQL join.
        from portfolios.gateway import read_latest_weights

        as_of_date, raw_weights = read_latest_weights(self._conn, pid)
        if as_of_date is None:
            return None, {}, []
        weights = {f: float(w) for f, w in raw_weights.items()}
        figis = list(weights)
        total_w = sum(weights.values())
        if not figis or total_w <= 0:
            return as_of_date, {}, []

        currencies = [
            r[0]
            for r in self._sym.execute(
                "SELECT DISTINCT currency_code FROM securities WHERE composite_figi = ANY(%s)",
                (figis,),
            ).fetchall()
        ]

        rows = self._sym.execute(
            "SELECT as_of_date, composite_figi, pr FROM fact_returns "
            "WHERE composite_figi = ANY(%s) AND window_id = %s AND pr IS NOT NULL",
            (figis, _ONE_DAY_WINDOW),
        ).fetchall()
        # date -> [Σ weight·pr, Σ weight] over priced constituents
        agg: dict[date, list[float]] = {}
        for d, figi, pr in rows:
            w = weights.get(figi)
            if w is None:
                continue
            acc = agg.setdefault(d, [0.0, 0.0])
            acc[0] += w * float(pr)
            acc[1] += w

        series: dict[date, float] = {}
        for d, (port_ret, covered_w) in agg.items():
            if covered_w / total_w >= COVERAGE_FLOOR:
                series[d] = port_ret / covered_w  # normalise by covered weight
        return as_of_date, series, sorted(c for c in currencies if c)

    def _benchmark_daily(self, benchmark_id: int) -> tuple[dict | None, dict[date, float]]:
        meta = self._sym.execute(
            "SELECT sym_id, name, currency_code FROM instrument WHERE sym_id = %s AND kind = 'index'",
            (benchmark_id,),
        ).fetchone()
        if not meta:
            return None, {}
        rows = self._sym.execute(
            "SELECT as_of_date, ret FROM fact_index_returns "
            "WHERE sym_id = %s AND window_id = %s AND ret IS NOT NULL",
            (benchmark_id, _ONE_DAY_WINDOW),
        ).fetchall()
        return (
            {"id": meta[0], "name": meta[1], "currency": meta[2]},
            {d: float(r) for d, r in rows},
        )

    def analytics(self, pid: int, benchmark_id: int, window: str) -> dict:
        w = (window or "ALL").upper()
        if w not in VALID_WINDOWS:
            # Don't silently compute full-history metrics while echoing the bogus label.
            raise ValueError(f"unknown window {window!r} (one of {', '.join(VALID_WINDOWS)})")
        as_of_date, port_series, currencies = self._portfolio_daily(pid)
        bench_meta, bench_series = self._benchmark_daily(benchmark_id)

        result: dict = {
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "window": (window or "ALL").upper(),
            "benchmark": bench_meta,
            "portfolio_currencies": currencies,
            "n_days": 0,
            "start_date": None,
            "end_date": None,
            "metrics": None,
            "warning": None,
        }
        if as_of_date is None:
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
                result["start_date"] = common[0].isoformat()
                result["end_date"] = common[-1].isoformat()
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

        # Skill metrics (FR-16), from the daily portfolio series p and active series (p - bench):
        #   hit ratio       = share of periods the portfolio is positive
        #   batting average = share of periods the portfolio beats the benchmark (active > 0)
        #   slugging ratio  = average winning active return / average losing active magnitude
        hit_ratio = sum(1 for x in p if x > 0) / n
        batting_average = sum(1 for x in active if x > 0) / n
        wins = [x for x in active if x > 0]
        losses = [-x for x in active if x < 0]
        slugging_ratio = (_mean(wins) / _mean(losses)) if wins and losses else None

        result["n_days"] = n
        result["start_date"] = common[0].isoformat()
        result["end_date"] = common[-1].isoformat()
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
            "hit_ratio": hit_ratio,
            "batting_average": batting_average,
            "slugging_ratio": slugging_ratio,
        }
        # Honest FX caveat: constituent returns are local-currency price returns.
        if bench_meta["currency"] and any(c != bench_meta["currency"] for c in currencies):
            result["warning"] = (
                f"portfolio holds {', '.join(currencies)} names but the benchmark is in "
                f"{bench_meta['currency']}; local-currency price returns are compared directly "
                "(unhedged FX not adjusted)."
            )
        return result
