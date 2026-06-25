"""One-time data migration: copy the index tables sym -> indices (non-destructive).

Streams each moved table from the sym DB into the indices DB via psycopg binary COPY (the
fx/equity-split playbook). The four index tables — index_levels, fact_index_returns,
fact_index_extremes, universe_benchmark — are small (~25 index instruments × dates), so this is
seconds, not the equity slog. No inter-table FKs among the four, and return_window is seeded by the
indices schema migration, so order is immaterial. Idempotent-ish: skips a table if the indices side
already has == the sym row count (re-run after a partial copy is safe to resume per-table by
TRUNCATE+recopy). Run AFTER deploy_all --only indices and BEFORE the sym:index_extract drop.

Run:  uv run python tools/migrate_indices_data.py
"""

from __future__ import annotations

import sys

from indices.db import connect as indices_connect
from indices.db import sym_connect

TABLES = [
    "index_levels",
    "fact_index_returns",
    "fact_index_extremes",
    "universe_benchmark",
]


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 (static list)


def main() -> int:
    sym = sym_connect()
    ix = indices_connect()
    ix.autocommit = False  # atomic per-table TRUNCATE+COPY (connect() returns a clean autocommit conn)

    for table in TABLES:
        # source tables live in the sym public schema; the indices side resolves via search_path.
        src_n = sym.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
        dst_n = _count(ix, table)
        if dst_n and dst_n == src_n:
            print(f"{table}: indices already has {dst_n:,} (== sym) — skip", flush=True)
            continue
        with ix.cursor() as cur:
            cur.execute(f"TRUNCATE indices.{table}")  # noqa: S608 (static list)
        with ix.cursor() as dcur, sym.cursor() as scur:
            with (
                scur.copy(f"COPY {table} TO STDOUT (FORMAT binary)") as src,  # noqa: S608
                dcur.copy(f"COPY indices.{table} FROM STDIN (FORMAT binary)") as dst,  # noqa: S608
            ):
                for chunk in src:
                    dst.write(chunk)
        ix.commit()
        got = _count(ix, table)
        status = "OK" if got == src_n else "MISMATCH"
        print(f"{table}: {src_n:,} -> {got:,} [{status}]", flush=True)
        if got != src_n:
            print("  ABORT: row-count mismatch", file=sys.stderr)
            return 1

    sym.close()
    ix.close()
    print("migration complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
