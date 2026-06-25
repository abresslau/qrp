"""One-time data migration: copy the equity tables sym -> equity (non-destructive).

Streams each moved table from the sym DB into the equity DB via psycopg binary COPY (the fx-split
playbook). FK-safe order; currency is upserted first so prices_raw/corporate_actions FKs resolve;
pipeline_run_log's GENERATED-ALWAYS identity is copied with OVERRIDING SYSTEM VALUE and its sequence
reset afterwards. Idempotent-ish: skips a table if the equity side already has >= the sym row count
(so a re-run after a partial copy is safe to resume per-table by TRUNCATE+recopy).

Run:  uv run python tools/migrate_equity_data.py
"""

from __future__ import annotations

import io
import sys

from equity.db import connect as eq_connect
from sym.db import connect as sym_connect

# FK-safe order: currency first (FK target), prices_raw before prices_review (composite FK).
TABLES = [
    "prices_raw",
    "corporate_actions",
    "price_gaps",
    "pipeline_backfill_progress",
    "pipeline_run_log",
    "fact_returns",
    "fact_price_extremes",
    "prices_review",
]


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 (static list)


def main() -> int:
    sym = sym_connect()
    eq = eq_connect()
    eq.autocommit = False

    # 1. currency superset: ensure every code referenced by prices/actions exists in equity.
    rows = sym.execute("SELECT code, name FROM currency").fetchall()
    with eq.cursor() as cur:
        cur.executemany(
            "INSERT INTO currency (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING", rows
        )
    eq.commit()
    print(f"currency: ensured {len(rows)} codes in equity")

    # 2. per-table binary COPY (TRUNCATE the equity side first so a re-run is clean).
    for table in TABLES:
        src_n = _count(sym, table)
        dst_n = _count(eq, table)
        if dst_n and dst_n == src_n:
            print(f"{table}: equity already has {dst_n:,} (== sym) — skip")
            continue
        with eq.cursor() as cur:
            cur.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608 (static list)
        # COPY FROM loads a GENERATED ALWAYS identity column (run_id) directly — no OVERRIDING needed
        # (that clause is an INSERT-only modifier and is a syntax error on COPY).
        buf = io.BytesIO()
        with sym.cursor() as scur, scur.copy(f"COPY {table} TO STDOUT (FORMAT binary)") as cp:
            for data in cp:
                buf.write(data)
        buf.seek(0)
        with eq.cursor() as dcur, dcur.copy(
            f"COPY {table} FROM STDIN (FORMAT binary)"  # noqa: S608 (static list)
        ) as cp:
            cp.write(buf.read())
        eq.commit()
        got = _count(eq, table)
        status = "OK" if got == src_n else "MISMATCH"
        print(f"{table}: {src_n:,} -> {got:,} [{status}]")
        if got != src_n:
            print("  ABORT: row-count mismatch", file=sys.stderr)
            return 1

    # 3. advance pipeline_run_log identity past the migrated max so new loads don't collide.
    with eq.cursor() as cur:
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('pipeline_run_log','run_id'), "
            "COALESCE((SELECT max(run_id) FROM pipeline_run_log), 1))"
        )
    eq.commit()
    print("pipeline_run_log identity sequence advanced")

    sym.close()
    eq.close()
    print("migration complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
