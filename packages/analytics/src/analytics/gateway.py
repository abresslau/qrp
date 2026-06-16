"""DB gateway for portfolio analytics.

Reads sym **read-only**: the portfolio's constituent daily returns (``fact_returns``
1D window, price return ``pr``) weighted by the portfolio's EFFECTIVE-DATED weight
history (Story Q5.2/Q4.5 — for each trading date the step-function vector, i.e. the
latest one with ``as_of_date <= date``; dates before the first vector are excluded,
never back-filled), and a benchmark daily series (``fact_index_returns`` 1D ``ret``
for an ``instrument`` of kind 'index'). Weights are held constant between rebalance
dates (weights-first platform: no intra-period drift modelling). Computes Sharpe,
annualised return/vol, beta, Jensen's alpha, benchmark-relative metrics, skill
metrics, and the FR-15 ``returns`` block: cumulative time-weighted return over the
window + PnL (= the portfolio's optional notional × cumulative return; no notional →
return-space only). Risk-free rate = 0. Never writes; never fabricates — coverage
gaps are reported.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import date, datetime, timezone

import psycopg
from portfolios.gateway import (
    portfolio_exists,
    read_latest_weights,
    read_portfolio_terms,
    read_weight_history,
)

from analytics import quotes
from analytics.quotes import QuoteSourceUnreachable

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

    def _portfolio_daily(
        self, pid: int
    ) -> tuple[date | None, dict[date, float], dict[date, float], list[str], list[date]]:
        """Daily portfolio return series under the EFFECTIVE-DATED weight history.

        Step-function convention (review-set, no look-ahead): a vector dated ``d`` is
        in force at the CLOSE of ``d``, so it earns from ``d+1`` — the return FOR a
        date (close d−1 → close d) belongs to the vector strictly BEFORE it. Dates on
        or before the first vector are excluded — those returns were earned before the
        portfolio existed, none are fabricated backwards. Weights are held constant
        between rebalance dates (weights-first: no intra-period drift modelling). A
        single-vector portfolio reproduces the previous latest-weights behavior for
        every date after its vector.

        Returns ``(latest as_of_date, {date: return}, {date: coverage fraction},
        currencies, dead_vector_dates)``. A date is included only when
        >= COVERAGE_FLOOR of the then-effective vector's ABSOLUTE weight is priced
        (signed sums would let an unpriced short book pass the floor);
        ``dead_vector_dates`` are vectors with non-positive absolute total whose era
        is unusable — surfaced as a warning, never silently compounded over.
        """
        # Weights through the OWNING package's seam (Story A.1) — the SQL has one
        # owner; the weight×return series is still assembled IN-APP (cross-database:
        # weights here, fact_returns in the sym package), never a cross-DB SQL join.
        history = read_weight_history(self._conn, pid)
        if not history:
            return None, {}, {}, [], []
        vectors = [
            (
                d,
                {f: float(w) for f, w in vec.items()},
                sum(abs(float(w)) for w in vec.values()),
            )
            for d, vec in history
        ]
        vector_dates = [d for d, _, _ in vectors]
        latest_as_of = vector_dates[-1]
        first_as_of = vector_dates[0]
        dead_vectors = [d for d, _, total_abs in vectors if total_abs <= 0]
        figis = sorted({f for _, vec, _ in vectors for f in vec})
        if not figis or len(dead_vectors) == len(vectors):
            return latest_as_of, {}, {}, [], dead_vectors

        currencies = [
            r[0]
            for r in self._sym.execute(
                "SELECT DISTINCT currency_code FROM securities WHERE composite_figi = ANY(%s)",
                (figis,),
            ).fetchall()
        ]

        rows = self._sym.execute(
            "SELECT as_of_date, composite_figi, pr FROM fact_returns "
            "WHERE composite_figi = ANY(%s) AND window_id = %s AND pr IS NOT NULL "
            "AND as_of_date > %s",
            (figis, _ONE_DAY_WINDOW, first_as_of),
        ).fetchall()
        # date -> [Σ weight·pr (signed), Σ |weight| priced]; the then-effective vector
        # index is a pure function of the date, kept in its own (typed) map.
        agg: dict[date, list[float]] = {}
        idx_by_date: dict[date, int] = {}
        for d, figi, pr in rows:
            # latest vector STRICTLY before d (in force at the close of its own date)
            idx = bisect_left(vector_dates, d) - 1
            if idx < 0:
                continue  # on/before the first vector: the portfolio didn't exist yet
            w = vectors[idx][1].get(figi)
            if w is None:
                continue
            idx_by_date[d] = idx
            acc = agg.setdefault(d, [0.0, 0.0])
            acc[0] += w * float(pr)
            acc[1] += abs(w)

        series: dict[date, float] = {}
        coverage: dict[date, float] = {}
        for d, (port_ret, covered_abs) in agg.items():
            total_abs = vectors[idx_by_date[d]][2]
            if total_abs <= 0:
                continue  # dead vector's era — reported via dead_vectors, never used
            cov = covered_abs / total_abs
            if cov >= COVERAGE_FLOOR and covered_abs > 0:
                series[d] = port_ret / covered_abs  # normalise by covered weight
                coverage[d] = cov
        return latest_as_of, series, coverage, sorted(c for c in currencies if c), dead_vectors

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

    def live_pnl(self, pid: int, *, now: float | None = None) -> dict:
        """Live portfolio PnL (Story QH.2): the EOD weight×return engine with the price source
        swapped to live quotes. Per constituent the live return = quote price / its own previous
        close − 1; the portfolio return is the SAME coverage-honest weighted sum the EOD path
        uses (``Σ w·r`` normalised by covered |weight|). Quotes are fetched externally and NEVER
        persisted. Freshness = worst across PRICED constituents; ``as_of`` = oldest priced quote.
        Raises LookupError (404) for a missing portfolio, QuoteSourceUnreachable (503) only when
        EVERY mappable constituent fails with a network error.
        """
        if not portfolio_exists(self._conn, pid):
            raise LookupError(f"portfolio {pid} not found")
        as_of, weights = read_latest_weights(self._conn, pid)
        terms = read_portfolio_terms(self._conn, pid)
        notional = float(terms[0]) if terms and terms[0] is not None else None
        base_ccy = terms[1] if terms else None
        result: dict = {
            "portfolio_id": pid,
            "weights_as_of": as_of.isoformat() if as_of else None,
            "as_of": None, "freshness": "unavailable",
            "n_constituents": len(weights), "n_priced": 0,
            "total_weight": 0.0, "covered_weight": 0.0,
            "live_return": None, "live_return_normalized": None,
            "notional": notional, "base_currency": base_ccy, "pnl": None,
            "constituents": [],
        }
        if not weights:
            return result

        figis = list(weights)
        meta = {
            f: (tk, mic)
            for f, tk, mic in self._sym.execute(
                """
                SELECT s.composite_figi, tk.symbol_value, s.mic
                  FROM securities s
                  LEFT JOIN LATERAL (
                      SELECT symbol_value FROM security_symbology y
                       WHERE y.composite_figi = s.composite_figi AND y.symbol_type = 'ticker'
                       ORDER BY (y.valid_to IS NULL) DESC, y.valid_from DESC LIMIT 1
                  ) tk ON TRUE
                 WHERE s.composite_figi = ANY(%s)
                """,
                (figis,),
            ).fetchall()
        }

        now = quotes.now_epoch() if now is None else now
        total_abs = covered_abs = port_ret = 0.0
        n_priced = attempted = net_errors = 0
        any_delayed = False
        oldest_epoch: int | None = None
        constituents: list[dict] = []
        for figi, wq in weights.items():
            w = float(wq)
            total_abs += abs(w)
            tk, mic = meta.get(figi, (None, None))
            ysym = quotes.yahoo_symbol_for(tk, mic)
            lr = None
            cfresh = "unavailable"
            if ysym is not None:
                attempted += 1
                try:
                    q = quotes.fetch_raw_quote(ysym)
                except QuoteSourceUnreachable:
                    net_errors += 1
                    q = None
                if q is not None:
                    lr = quotes.live_return(q.price, q.prev_close)
                    if lr is not None:
                        # Freshness is meaningful only for a PRICED name, and it stays in the
                        # {live,delayed,unavailable} vocabulary. classify_freshness(None) -> 'delayed',
                        # so a priced-but-timeless quote is 'delayed' — never silently 'live'.
                        cfresh, _ = quotes.classify_freshness(q.quote_epoch, now)
                        any_delayed = any_delayed or cfresh == "delayed"
                        if q.quote_epoch is not None:
                            oldest_epoch = (
                                q.quote_epoch if oldest_epoch is None
                                else min(oldest_epoch, q.quote_epoch)
                            )
            contrib = None
            if lr is not None:
                covered_abs += abs(w)
                port_ret += w * lr
                n_priced += 1
                contrib = w * lr
            constituents.append(
                {"figi": figi, "ticker": tk, "weight": w, "live_return": lr,
                 "contribution": contrib, "freshness": cfresh}
            )

        if attempted and net_errors == attempted:
            raise QuoteSourceUnreachable(
                f"quote provider unreachable ({net_errors}/{attempted} constituents)"
            )

        norm = (port_ret / covered_abs) if covered_abs > 0 else None
        constituents.sort(
            key=lambda x: abs(x["contribution"]) if x["contribution"] is not None else -1,
            reverse=True,
        )
        result.update(
            n_priced=n_priced,
            total_weight=total_abs,
            covered_weight=covered_abs,
            live_return=port_ret if covered_abs > 0 else None,
            live_return_normalized=norm,
            freshness=("unavailable" if n_priced == 0 else "delayed" if any_delayed else "live"),
            as_of=(
                datetime.fromtimestamp(oldest_epoch, tz=timezone.utc).isoformat()
                if oldest_epoch is not None else None
            ),
            pnl=(notional * norm) if (notional is not None and norm is not None) else None,
            constituents=constituents,
        )
        return result

    def analytics(self, pid: int, benchmark_id: int, window: str) -> dict:
        w = (window or "ALL").upper()
        if w not in VALID_WINDOWS:
            # Don't silently compute full-history metrics while echoing the bogus label.
            raise ValueError(f"unknown window {window!r} (one of {', '.join(VALID_WINDOWS)})")
        if not portfolio_exists(self._conn, pid):
            # Nonexistent portfolio is a 404, not an empty-metrics 200 — an
            # existing portfolio with no weights yet still gets the warning body.
            raise LookupError(f"portfolio {pid} not found")
        as_of_date, port_series, port_coverage, currencies, dead_vectors = (
            self._portfolio_daily(pid)
        )
        bench_meta, bench_series = self._benchmark_daily(benchmark_id)

        warnings: list[str] = []
        if dead_vectors:
            warnings.append(
                "weight vector(s) with non-positive total weight — their era is excluded: "
                + ", ".join(d.isoformat() for d in dead_vectors)
            )

        result: dict = {
            # the NEWEST stored vector's date (the series itself blends the full
            # effective-dated history) — see the response model comment
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "window": (window or "ALL").upper(),
            "benchmark": bench_meta,
            "portfolio_currencies": currencies,
            "n_days": 0,
            "start_date": None,
            "end_date": None,
            "returns": None,
            "metrics": None,
            "warning": "; ".join(warnings) if warnings else None,
        }
        if as_of_date is None:
            result["warning"] = "no weights stored for this portfolio"
            return result
        if bench_meta is None:
            warnings.append("unknown benchmark")
            result["warning"] = "; ".join(warnings)
            return result

        # FR-15 returns block (Story Q5.2, AC3 amended by review): the cumulative
        # time-weighted return compounds the portfolio's OWN window-filtered series —
        # benchmark-INDEPENDENT, because an absolute return/PnL figure must not change
        # with the benchmark picker (intersection days dropped would compound as 0%).
        # The relative metrics below keep the portfolio∩benchmark intersection.
        # pnl = notional × cumulative return when the operator stated a notional, else
        # return-space only — never a fabricated amount. Served even below the 20-obs
        # statistics floor (a cumulative return doesn't need 20 obs for meaning).
        port_dates = sorted(port_series)
        if port_dates:
            start = _window_start(window, port_dates[-1])
            if start is not None:
                port_dates = [d for d in port_dates if d >= start]
        if port_dates:
            terms = read_portfolio_terms(self._conn, pid)
            notional, base_ccy = terms if terms else (None, None)
            growth = 1.0
            below_full = 0
            min_cov = 1.0
            for d in port_dates:
                growth *= 1.0 + port_series[d]
                cov = port_coverage.get(d, 1.0)
                min_cov = min(min_cov, cov)
                if cov < 0.9999:
                    below_full += 1
            cumulative = growth - 1.0
            result["returns"] = {
                "cumulative_return": cumulative,
                "n_days": len(port_dates),
                # honesty: days below full coverage are renormalised (unpriced weight
                # implicitly earns the covered-average return) and compound into PnL
                "days_below_full_coverage": below_full,
                "min_coverage": min_cov,
                "notional": float(notional) if notional is not None else None,
                "base_currency": base_ccy,
                "pnl": float(notional) * cumulative if notional is not None else None,
            }

        # Overlapping trading dates, oldest first — the relative-metrics series.
        common = sorted(set(port_series) & set(bench_series))
        if common:
            start = _window_start(window, common[-1])
            if start is not None:
                common = [d for d in common if d >= start]

        if len(common) < 20:
            result["n_days"] = len(common)
            warnings.append(
                f"only {len(common)} overlapping daily observations "
                "(need >= 20 for stable statistics)"
            )
            result["warning"] = "; ".join(warnings)
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
            warnings.append(
                f"portfolio holds {', '.join(currencies)} names but the benchmark is in "
                f"{bench_meta['currency']}; local-currency price returns are compared directly "
                "(unhedged FX not adjusted)."
            )
        result["warning"] = "; ".join(warnings) if warnings else None
        return result
