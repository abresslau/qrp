"""DuckDB live-attach federation spike — re-runnable (Story QH.5).

The 2026-06-08 architecture revision chose Postgres-per-package + DuckDB federation and
deferred this spike to "a network-enabled env". That blocker is gone: re-run any time
with ``uv run python tools/duckdb_spike.py``. The spike proves the three claims the
architecture rests on:

1. the postgres extension installs (extension egress reachable);
2. ``ATTACH … (TYPE postgres, READ_ONLY)`` gives native cross-DATABASE joins over the
   independent per-package stores (the Snowflake-style ergonomics);
3. writes through the attachment are PHYSICALLY refused (reads-are-read-only enforced
   by the engine, not by convention).

Finding (2026-06-11, recorded in architecture-qrp.md + the ledger): all three hold
live. Adopting DuckDB in serving paths is its own future story — until then app-side
psycopg assembly remains the implementation and this spike is the proof the option is
real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    env = _env()
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    print("1. postgres extension installed + loaded")
    dsn = (
        f"host={env.get('PGHOST', 'localhost')} port={env.get('PGPORT', '5432')} "
        f"user={env.get('PGUSER', 'postgres')} password={env['PGPASSWORD']}"
    )
    for db in ("sym", "signals", "macro"):
        con.execute(f"ATTACH 'dbname={db} {dsn}' AS {db} (TYPE postgres, READ_ONLY)")
    rows = con.execute(
        """
        SELECT s.factor_key, sy.symbol_value AS ticker, s.rank
          FROM signals.signals.score s
          JOIN sym.public.security_symbology sy
            ON sy.composite_figi = s.composite_figi
           AND sy.symbol_type = 'ticker' AND sy.valid_to IS NULL
         WHERE s.universe_id = 'sp500' AND s.rank <= 3
         ORDER BY s.factor_key, s.rank
        """
    ).fetchall()
    if not rows:
        print("2. cross-DB join returned NO rows — compute signals first")
        return 1
    # correctness, not just non-emptiness: each factor contributes exactly ranks 1..3
    # with a resolvable (non-null) ticker — a fanned-out or mismatched join fails here
    by_factor: dict[str, list[int]] = {}
    for factor, ticker, rank in rows:
        if ticker is None:
            print(f"2. join produced a NULL ticker for {factor} rank {rank} — BROKEN")
            return 1
        by_factor.setdefault(factor, []).append(rank)
    bad = {f: r for f, r in by_factor.items() if sorted(r) != [1, 2, 3]}
    if bad:
        print(f"2. join shape wrong (expected ranks 1..3 per factor): {bad}")
        return 1
    print(f"2. native cross-DATABASE join (signals x sym) CORRECT: "
          f"{len(by_factor)} factors x ranks 1..3, e.g. {rows[0]}")
    try:
        con.execute("DELETE FROM macro.macro.observation WHERE series_id = 'NOPE'")
        print("3. WRITE SUCCEEDED THROUGH A READ_ONLY ATTACH — the architecture claim is BROKEN")
        return 1
    except duckdb.Error as exc:
        # explicit check (an assert would vanish under -O and bless ANY error)
        if "read-only" not in str(exc):
            print(f"3. write failed for the WRONG reason (not read-only): {str(exc)[:120]}")
            return 1
        print("3. write physically refused (READ_ONLY enforced by the engine)")
    print("\nspike PASSED — the federation option is live-verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
