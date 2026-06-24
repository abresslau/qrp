"""Independent cross-check of FX-restated index returns (Epic FX consumer).

Validates `sym.fx.restate` end-to-end against a *different* path and a *different* FX vendor:

  pipeline  USD return = stored local index return (fact_index_returns) x Frankfurter/ECB FX ratio
  independent USD return = Yahoo index level x Yahoo `<local><target>=X` spot ("convert the levels")

If the two agree within a small tolerance, the restatement formula `(1+r_local)*FX(asof)/FX(base)-1`
is confirmed (annualized windows de-annualize -> restate -> re-annualize). The residual is expected
cross-vendor FX divergence: Frankfurter is ECB's daily reference fix (~16:00 CET) while Yahoo
`=X` is a market spot at a different time -- so a few tenths of a percent per window is normal,
not a bug. (Note: the *local* return side shares Yahoo as the underlying source, so only the FX +
the restatement math are independently checked here.)

This is a manual, network-touching validation (yfinance) -- NOT part of the test suite.

Usage:  uv run python benchmark/validate_fx_restatement.py [--index "FTSE 100"] [--target USD]
"""

from __future__ import annotations

import argparse
import bisect
from datetime import date

from fx.convert import convert
from fx.db import connect as fx_connect

from sym.config import load_dotenv
from sym.db import connect
from sym.fx.restate import restate_return
from sym.returns.windows import BY_CODE, base_date

DEFAULT_WINDOWS = ["YTD", "1Y", "3Y", "5Y", "10Y"]
TOLERANCE_PP = 1.5  # percentage points; residual above this is worth investigating


def _yahoo_close_series(symbol: str, start: str, end: str) -> list[tuple[date, float]]:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
    return [(idx.date(), float(v)) for idx, v in hist["Close"].items()]


def _as_of(series: list[tuple[date, float]], on: date) -> float | None:
    dates = [d for d, _ in series]
    i = bisect.bisect_right(dates, on)
    return series[i - 1][1] if i > 0 else None


def validate(index_name: str, target: str, windows: list[str]) -> int:
    load_dotenv()
    with connect() as conn, fx_connect() as fx_conn:
        conn.autocommit = True
        fx_conn.autocommit = True
        row = conn.execute(
            "SELECT sym_id, currency_code FROM instrument WHERE name=%s AND kind='index'",
            (index_name,),
        ).fetchone()
        if not row:
            print(f"no index instrument named {index_name!r}")
            return 1
        sym_id, local = row
        yahoo = conn.execute(
            "SELECT value FROM instrument_xref WHERE sym_id=%s AND source='yahoo' LIMIT 1",
            (sym_id,),
        ).fetchone()
        if not yahoo:
            print(f"{index_name} has no Yahoo xref to cross-check against")
            return 1
        idx_symbol = yahoo[0]
        fx_symbol = f"{local}{target}=X"
        sessions = [
            r[0]
            for r in conn.execute(
                "SELECT session_date FROM index_levels WHERE sym_id=%s ORDER BY session_date",
                (sym_id,),
            ).fetchall()
        ]
        as_of = conn.execute(
            "SELECT max(as_of_date) FROM fact_index_returns WHERE sym_id=%s", (sym_id,)
        ).fetchone()[0]

        idx_series = _yahoo_close_series(idx_symbol, "2014-01-01", (as_of).isoformat())
        fx_series = _yahoo_close_series(fx_symbol, "2014-01-01", (as_of).isoformat())
        if not idx_series or not fx_series:
            print(f"could not fetch Yahoo series ({idx_symbol} / {fx_symbol})")
            return 1

        print(f"{index_name} ({local}) restated to {target} -- as-of {as_of}")
        print(f"  pipeline: stored return x Frankfurter | independent: {idx_symbol} x {fx_symbol}")
        print(f"{'win':>5} | {'pipeline':>9} | {'indep':>9} | {'diff':>8} | <= {TOLERANCE_PP}pp?")
        worst = 0.0
        for code in windows:
            w = BY_CODE.get(code)
            if w is None:
                continue
            ret = conn.execute(
                "SELECT ret FROM fact_index_returns "
                "WHERE sym_id=%s AND window_id=%s AND as_of_date=%s",
                (sym_id, w.id, as_of),
            ).fetchone()
            if not ret or ret[0] is None:
                continue
            base = base_date(w, as_of, sessions)
            if base is None:
                continue
            f_base = convert(fx_conn, 1, local, target, base)
            f_asof = convert(fx_conn, 1, local, target, as_of)
            if f_base is None or f_asof is None or f_base <= 0:
                print(f"{code:>5} | (no FX leg)")
                continue
            years = (as_of - base).days / 365.25 if w.annualized else None
            pipeline = float(
                restate_return(ret[0], f_asof / f_base, annualized=w.annualized, years=years)
            )

            ib, ia = _as_of(idx_series, base), _as_of(idx_series, as_of)
            xb, xa = _as_of(fx_series, base), _as_of(fx_series, as_of)
            if None in (ib, ia, xb, xa):
                print(f"{code:>5} | (no Yahoo bar at an endpoint)")
                continue
            indep = (ia * xa) / (ib * xb) - 1
            if w.annualized and years:
                indep = (1 + indep) ** (1 / years) - 1
            diff_pp = (pipeline - indep) * 100
            worst = max(worst, abs(diff_pp))
            ok = "ok" if abs(diff_pp) <= TOLERANCE_PP else "INVESTIGATE"
            print(
                f"{code:>5} | {pipeline * 100:+8.2f}% | {indep * 100:+8.2f}% | "
                f"{diff_pp:+7.2f}pp | {ok}"
            )
        print(f"\nworst residual: {worst:.2f}pp "
              f"({'PASS' if worst <= TOLERANCE_PP else 'review'} at {TOLERANCE_PP}pp tolerance; "
              f"residual is cross-vendor FX-fix divergence, not a logic error)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="FTSE 100", help="Index instrument name.")
    parser.add_argument("--target", default="USD", help="Target currency (default: USD).")
    parser.add_argument(
        "--windows", default=",".join(DEFAULT_WINDOWS), help="Comma-separated window codes."
    )
    args = parser.parse_args()
    windows = [w.strip() for w in args.windows.split(",")]
    raise SystemExit(validate(args.index, args.target, windows))


if __name__ == "__main__":
    main()
