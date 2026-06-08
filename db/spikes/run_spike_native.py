"""DuckDB federation spike — env-adapted runner (the one that produced the 2026-06-08 findings).

Proves DuckDB cross-DATABASE ATTACH + native 3-part-name joins + READ_ONLY on REAL sym data
materialized into two DuckDB-native databases (sym hub + a separate signal db) — the
*materialized / heavy-path* federation mode. Use this when the live postgres_scanner extension
is unavailable (e.g. extensions.duckdb.org unreachable); for the live-PG path see run_spike_live.py.

Run:  SYM_DB_PASSWORD=... uv run --with duckdb --with "psycopg[binary]" python run_spike_native.py
Non-destructive: scratch DuckDB files under this dir, deleted at the end. sym is read-only.
"""
from __future__ import annotations
import os, sys, time, hashlib, pathlib
import psycopg, duckdb

PW = os.environ.get("SYM_DB_PASSWORD")
if not PW:
    sys.exit("set SYM_DB_PASSWORD (see the repo .env) before running")
SYM = f"host=localhost port=5432 dbname=sym user=postgres password={PW}"
HERE = pathlib.Path(__file__).resolve().parent
SYMDB, SIGDB = HERE / "_sym.duckdb", HERE / "_signal.duckdb"
for p in (SYMDB, SIGDB):
    p.unlink(missing_ok=True)
N = 50

def hsum(rows):
    h = hashlib.sha256()
    for r in rows: h.update(repr(tuple(r)).encode())
    return h.hexdigest()[:12]

def timed(fn, n=N):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); fn(); ts.append(time.perf_counter()-t)
    ts.sort(); return ts[len(ts)//2], ts[int(len(ts)*0.95)]

pg = psycopg.connect(SYM)
uni = pg.execute("SELECT universe_id FROM signal.score GROUP BY 1 ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
fac = pg.execute("SELECT factor_key FROM signal.score WHERE universe_id=%s GROUP BY 1 ORDER BY count(*) DESC LIMIT 1",(uni,)).fetchone()[0]
wid = (pg.execute("SELECT window_id FROM return_window WHERE code='YTD'").fetchone()
       or pg.execute("SELECT window_id FROM return_window LIMIT 1").fetchone())[0]
print(f"universe={uni}  factor={fac}  window_id={wid}", flush=True)

members = pg.execute("SELECT DISTINCT composite_figi FROM universe_member_resolution WHERE universe_id=%s",(uni,)).fetchall()
funds   = pg.execute("""SELECT DISTINCT ON (composite_figi) composite_figi, market_cap_usd
                          FROM fundamentals WHERE market_cap_usd IS NOT NULL
                         ORDER BY composite_figi, as_of_date DESC""").fetchall()
rets    = pg.execute("""SELECT composite_figi, pr FROM fact_returns
                         WHERE window_id=%s AND as_of_date=(SELECT max(as_of_date) FROM fact_returns WHERE window_id=%s)""",(wid,wid)).fetchall()
scores  = pg.execute("SELECT composite_figi, zscore FROM signal.score WHERE universe_id=%s AND factor_key=%s",(uni,fac)).fetchall()
pg.close()
print(f"pulled: members={len(members)} fundamentals={len(funds)} returns={len(rets)} scores={len(scores)}", flush=True)

# two independent DuckDB databases (sym hub + a separate signal db)
d = duckdb.connect(str(SYMDB))
d.execute("CREATE TABLE members(composite_figi VARCHAR)"); d.executemany("INSERT INTO members VALUES (?)", members)
d.execute("CREATE TABLE fundamentals(composite_figi VARCHAR, market_cap_usd DOUBLE)"); d.executemany("INSERT INTO fundamentals VALUES (?,?)", funds)
d.execute("CREATE TABLE fact_returns(composite_figi VARCHAR, pr DOUBLE)"); d.executemany("INSERT INTO fact_returns VALUES (?,?)", rets)
d.close()
d = duckdb.connect(str(SIGDB))
d.execute("CREATE TABLE score(composite_figi VARCHAR, zscore DOUBLE)"); d.executemany("INSERT INTO score VALUES (?,?)", scores)
d.close()

con = duckdb.connect()
con.execute(f"ATTACH '{SYMDB}' AS sym (READ_ONLY);")
con.execute(f"ATTACH '{SIGDB}' AS sig (READ_ONLY);")

# Cross-DATABASE join, native 3-part names (sym.* + sig.*) — Snowflake-style ergonomics.
Q = """
SELECT m.composite_figi, f.market_cap_usd, r.pr AS window_return, sc.zscore AS factor_z
  FROM sym.main.members m
  LEFT JOIN sym.main.fundamentals f ON f.composite_figi = m.composite_figi
  LEFT JOIN sym.main.fact_returns r ON r.composite_figi = m.composite_figi
  LEFT JOIN sig.main.score       sc ON sc.composite_figi = m.composite_figi
 ORDER BY f.market_cap_usd DESC NULLS LAST"""

print("\n=== 1. ergonomics: native cross-database 3-part join ===", flush=True)
rows = con.execute(Q).fetchall()
nz = sum(1 for x in rows if x[3] is not None)
print(f"returned {len(rows)} rows; {nz} carry a cross-DB signal z-score; top: {rows[0]}", flush=True)

print("\n=== 2. tie-out (signal from separate db vs same data) ===", flush=True)
con.execute(f"ATTACH '{SIGDB}' AS sig2 (READ_ONLY);")
fed = con.execute(Q).fetchall()
same = con.execute(Q.replace("sig.main.score", "sig2.main.score")).fetchall()
print("TIE-OUT:", "PASS" if hsum(fed)==hsum(same) and len(fed)==len(same) else "FAIL", flush=True)

print("\n=== 3. latency on materialized federation (p50/p95, %d runs) ===" % N, flush=True)
p50, p95 = timed(lambda: con.execute(Q).fetchall())
print(f"cross-DB join: p50={p50*1000:.2f} ms  p95={p95*1000:.2f} ms  ({len(rows)} rows)", flush=True)

print("\n=== 4. READ_ONLY boundary ===", flush=True)
try:
    con.execute("INSERT INTO sym.main.fundamentals VALUES ('XXXXXXXXXXXX', 0)")
    print("READ_ONLY: FAIL (write allowed!)", flush=True)
except Exception as e:
    print(f"READ_ONLY: PASS (refused: {str(e).splitlines()[0][:70]})", flush=True)

con.close()
for p in (SYMDB, SIGDB): p.unlink(missing_ok=True)
print("\ncleanup done.", flush=True)
