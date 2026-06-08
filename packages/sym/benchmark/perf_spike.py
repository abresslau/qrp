"""View-performance spike at ~20M rows (Story 3.3, GATING / OI-1 / SM-4).

Builds a throwaway ``bench`` schema (unlogged synthetic tables mirroring
``prices_raw`` + ``corporate_actions`` + a ``v_prices_adjusted``-equivalent view),
loads ~20M rows, and times the query patterns that matter:

  1. cross-sectional snapshot from the view (one asof, all securities) -- SM-4,
  2. cross-sectional single-window return (view joined to itself at the base date),
  3. full-view scan (the recompute-from-view cost).

The gate (AC #1): the cross-sectional queries must be < 10s. The real warehouse is
never touched; the bench schema is dropped at the end (use --keep to retain it).

Run: ``uv run python benchmark/perf_spike.py [--securities N --days N]``
"""

from __future__ import annotations

import argparse
import time

from sym.db import connect

BOUND_SECONDS = 10.0


def _timed(conn, label, sql):
    start = time.perf_counter()
    row = conn.execute(sql).fetchone()
    elapsed = time.perf_counter() - start
    verdict = "PASS" if elapsed < BOUND_SECONDS else "FAIL"
    print(f"  {label:42} {elapsed:7.2f}s  [{verdict if 'cross' in label else 'info'}]  -> {row}")
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="v_prices_adjusted perf spike (~20M rows).")
    parser.add_argument("--securities", type=int, default=4000)
    parser.add_argument("--days", type=int, default=5000)
    parser.add_argument("--keep", action="store_true", help="keep the bench schema")
    args = parser.parse_args()
    target_rows = args.securities * args.days

    with connect() as conn:
        conn.autocommit = True
        print(
            f"building bench: {args.securities} securities x {args.days} sessions "
            f"= {target_rows:,} rows"
        )
        conn.execute("DROP SCHEMA IF EXISTS bench CASCADE")
        conn.execute("CREATE SCHEMA bench")
        conn.execute(
            "CREATE UNLOGGED TABLE bench.prices_raw "
            "(composite_figi text, session_date date, close numeric)"
        )
        conn.execute(
            "CREATE UNLOGGED TABLE bench.corporate_actions "
            "(composite_figi text, ex_date date, action_type text, value numeric)"
        )

        t0 = time.perf_counter()
        conn.execute(
            """
            INSERT INTO bench.prices_raw (composite_figi, session_date, close)
            SELECT 'BENCH' || lpad(s::text, 8, '0'),
                   date '2005-01-03' + d,
                   (50 + (s %% 500) + d * 0.01)::numeric
            FROM generate_series(1, %s) s, generate_series(0, %s - 1) d
            """,
            (args.securities, args.days),
        )
        # ~2 splits per security
        conn.execute(
            """
            INSERT INTO bench.corporate_actions (composite_figi, ex_date, action_type, value)
            SELECT 'BENCH' || lpad(s::text, 8, '0'), date '2011-06-15', 'split', 2
            FROM generate_series(1, %s) s
            UNION ALL
            SELECT 'BENCH' || lpad(s::text, 8, '0'), date '2016-06-15', 'split', 4
            FROM generate_series(1, %s) s
            """,
            (args.securities, args.securities),
        )
        print(f"  loaded in {time.perf_counter() - t0:.1f}s; indexing...")
        t0 = time.perf_counter()
        conn.execute(
            "CREATE UNIQUE INDEX ON bench.prices_raw (composite_figi, session_date)"
        )
        conn.execute("CREATE INDEX ON bench.prices_raw (session_date)")
        conn.execute(
            "CREATE UNIQUE INDEX ON bench.corporate_actions (composite_figi, ex_date, action_type)"
        )
        conn.execute("ANALYZE bench.prices_raw")
        conn.execute("ANALYZE bench.corporate_actions")
        conn.execute(
            """
            CREATE VIEW bench.v_adj AS
            SELECT p.composite_figi, p.session_date, p.close AS close_raw,
                   f.split_factor, p.close / f.split_factor AS adj_close
            FROM bench.prices_raw p
            CROSS JOIN LATERAL (
                SELECT COALESCE(product(ca.value), 1) AS split_factor
                FROM bench.corporate_actions ca
                WHERE ca.composite_figi = p.composite_figi
                  AND ca.action_type = 'split'
                  AND ca.ex_date > p.session_date
            ) f
            """
        )
        actual = conn.execute("SELECT count(*) FROM bench.prices_raw").fetchone()[0]
        print(f"  indexed in {time.perf_counter() - t0:.1f}s; {actual:,} rows. timing:")

        asof = "date '2014-01-15'"
        base = "date '2013-01-15'"
        results = {
            "cross-sectional snapshot (view, 1 asof)": _timed(
                conn, "cross-sectional snapshot (view, 1 asof)",
                "SELECT count(*), round(avg(adj_close), 4) "
                f"FROM bench.v_adj WHERE session_date = {asof}",
            ),
            "cross-sectional 1Y return (view self-join)": _timed(
                conn, "cross-sectional 1Y return (view self-join)",
                f"""SELECT count(*) FROM (
                    SELECT a.composite_figi, a.adj_close / b.adj_close - 1 AS ret
                    FROM bench.v_adj a JOIN bench.v_adj b USING (composite_figi)
                    WHERE a.session_date = {asof} AND b.session_date = {base}
                ) x""",
            ),
            "full-view scan (recompute-from-view)": _timed(
                conn, "full-view scan (recompute-from-view)",
                "SELECT count(*), round(sum(adj_close), 0) FROM bench.v_adj",
            ),
        }

        cross = [v for k, v in results.items() if k.startswith("cross")]
        gate = "PASS" if all(t < BOUND_SECONDS for t in cross) else "FAIL"
        print(f"\nGATE (SM-4 cross-sectional < {BOUND_SECONDS:.0f}s): {gate}")
        print(f"  slowest cross-sectional: {max(cross):.2f}s")

        if not args.keep:
            conn.execute("DROP SCHEMA IF EXISTS bench CASCADE")
            print("  bench schema dropped.")
    return 0 if gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
