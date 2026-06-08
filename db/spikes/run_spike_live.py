"""DuckDB federation spike — LIVE Postgres-attach runner (for a network-enabled env).

The real target test: DuckDB ATTACH READ_ONLY to two independent *Postgres* databases (sym hub +
a carved signal_spike DB) and run the heat-map cross-package join straight off live PG — exercising
the postgres_scanner read path + filter PUSHDOWN, the one piece run_spike_native.py cannot cover.

REQUIRES the DuckDB `postgres` extension (downloads from extensions.duckdb.org). If that host is
unreachable (as in the 2026-06-08 simulated env → HTTP 503), this exits 3 with a clear message;
use run_spike_native.py instead and defer the pushdown measurement.

Run:  SYM_DB_PASSWORD=... uv run --with duckdb --with "psycopg[binary]" python run_spike_live.py
Non-destructive: scratch Postgres DB `signal_spike`, dropped at the end. sym is attached READ_ONLY.
"""
from __future__ import annotations
import os, sys, time, hashlib
import psycopg, duckdb

PW = os.environ.get("SYM_DB_PASSWORD")
if not PW:
    sys.exit("set SYM_DB_PASSWORD (see the repo .env) before running")
BASE = f"host=localhost port=5432 user=postgres password={PW}"
SYM, SPK = BASE + " dbname=sym", BASE + " dbname=signal_spike"
N = 20

def hsum(rows):
    h = hashlib.sha256()
    for r in rows: h.update(repr(tuple(r)).encode())
    return h.hexdigest()[:12]

def timed(fn, n=N):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); fn(); ts.append(time.perf_counter()-t)
    ts.sort(); return ts[len(ts)//2], ts[int(len(ts)*0.95)]

adm = psycopg.connect(SYM, autocommit=True)
adm.execute("DROP DATABASE IF EXISTS signal_spike"); adm.execute("CREATE DATABASE signal_spike")

con = duckdb.connect()
try:
    con.execute("INSTALL postgres; LOAD postgres;")
except Exception as e:
    print(f"!! postgres extension unavailable: {e}", flush=True)
    adm.execute("DROP DATABASE IF EXISTS signal_spike")
    sys.exit(3)

# sym READ_ONLY throughout; sig rw only for the one-time carve, then re-attached read-only.
con.execute(f"ATTACH '{SYM}' AS sym (TYPE postgres, READ_ONLY);")
con.execute(f"ATTACH '{SPK}' AS sig (TYPE postgres);")
con.execute("CREATE SCHEMA IF NOT EXISTS sig.signal;")
con.execute("CREATE TABLE sig.signal.score AS SELECT * FROM sym.signal.score;")
con.execute("DETACH sig;")
con.execute(f"ATTACH '{SPK}' AS sig (TYPE postgres, READ_ONLY);")

uni = con.execute("SELECT universe_id FROM sym.signal.score GROUP BY 1 ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
fac = con.execute("SELECT factor_key FROM sym.signal.score WHERE universe_id=? GROUP BY 1 ORDER BY count(*) DESC LIMIT 1",[uni]).fetchone()[0]
wid = (con.execute("SELECT window_id FROM sym.return_window WHERE code='YTD'").fetchone()
       or con.execute("SELECT window_id FROM sym.return_window LIMIT 1").fetchone())[0]
print(f"universe={uni}  factor={fac}  window_id={wid}", flush=True)

def q(sig_ref: str) -> str:
    return f"""
    WITH members AS (SELECT DISTINCT composite_figi FROM sym.public.universe_member_resolution WHERE universe_id='{uni}'),
    f AS (SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd FROM sym.public.fundamentals
           WHERE market_cap_usd IS NOT NULL ORDER BY composite_figi, as_of_date DESC),
    ret AS (SELECT composite_figi, pr FROM sym.public.fact_returns WHERE window_id={wid}
             AND as_of_date=(SELECT max(as_of_date) FROM sym.public.fact_returns WHERE window_id={wid}))
    SELECT m.composite_figi, f.market_cap_usd, ret.pr AS window_return, sc.zscore AS factor_z
      FROM members m
      LEFT JOIN f ON f.composite_figi=m.composite_figi
      LEFT JOIN ret ON ret.composite_figi=m.composite_figi
      LEFT JOIN {sig_ref} sc ON sc.composite_figi=m.composite_figi AND sc.universe_id='{uni}' AND sc.factor_key='{fac}'
     ORDER BY f.market_cap_usd DESC NULLS LAST"""

print("\n=== 1. cross-DB ergonomics + tie-out ===", flush=True)
fed = con.execute(q("sig.signal.score")).fetchall()
base = con.execute(q("sym.signal.score")).fetchall()
print(f"federated rows={len(fed)} csum={hsum(fed)} ; sym-only rows={len(base)} csum={hsum(base)}", flush=True)
print("TIE-OUT:", "PASS" if hsum(fed)==hsum(base) and len(fed)==len(base) else "FAIL", flush=True)

print("\n=== 2. latency (live PG attach) ===", flush=True)
p50f, p95f = timed(lambda: con.execute(q("sig.signal.score")).fetchall())
print(f"DuckDB federated (live PG): p50={p50f*1000:.1f} ms  p95={p95f*1000:.1f} ms", flush=True)

print("\n=== 3. pushdown (EXPLAIN) ===", flush=True)
try:
    plan = "\n".join(str(r[-1]) for r in con.execute("EXPLAIN " + q("sig.signal.score")).fetchall())
    print("filters reach PG scan:", ("universe_id" in plan or "filter" in plan.lower()), flush=True)
    print(plan[:1200], flush=True)
except Exception as e:
    print(f"EXPLAIN error: {e}", flush=True)

print("\n=== 4. READ_ONLY boundary ===", flush=True)
try:
    con.execute("UPDATE sym.public.fundamentals SET market_cap_usd=0 WHERE false")
    print("READ_ONLY: FAIL (write allowed!)", flush=True)
except Exception as e:
    print(f"READ_ONLY: PASS (refused: {str(e).splitlines()[0][:70]})", flush=True)

con.close()
adm.execute("DROP DATABASE IF EXISTS signal_spike")
print("\nsignal_spike dropped. done.", flush=True)
