"""Offline lineage generator (QL-2, option A).

Runs each downstream engine package's **read path** under a :class:`CaptureSession` (no writes
executed — write targets are synthesized from the live schema), derives table-level + key-column
lineage with :mod:`lineage.derive`, and writes ``derived_lineage.py`` — a generated map that
``assets.py`` imports to replace hand-declared deps for the downstream (cross-package) assets.

Run:  ``uv run python -m lineage.generate``

Scope: downstream engines (optimiser, signals, backtest, altdata) — they read the ``sym`` package
and write their own DB. sym-internal lineage stays declared (QL-3). Recipes call each engine's
read helpers best-effort: capture happens at ``execute()``, so sparse data / arg mismatches that
error *after* the query still yield the captured SQL.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import psycopg

from .derive import derive_edges, pg_schema, to_dagster_metadata
from .sql_capture import CaptureSession

_FIGI = ["BBG000B9XRY4"]
_UNIV = "sp500"
_D = date(2024, 6, 3)


def _try(fn):
    try:
        fn()
    except Exception:
        pass  # the SQL is captured at execute(); post-processing errors are irrelevant here


def _r_optimiser(sym):
    from optimiser import engine as e
    _try(lambda: e._select_names(sym, _UNIV, 5))
    _try(lambda: e._return_matrix(sym, _FIGI, 60))
    _try(lambda: e._tickers(sym, _FIGI))


def _r_signals(sym):
    from signals import compute as c
    _try(lambda: c._members(sym, _UNIV, _D))
    _try(lambda: c._raw_momentum(sym, _FIGI, _D))
    _try(lambda: c._raw_vol(sym, _FIGI, _D))
    _try(lambda: c._raw_size(sym, _FIGI))


def _r_backtest(sym):
    from backtest import engine as e
    _try(lambda: e._members(sym, _UNIV))
    _try(lambda: e._trading_days(sym, _FIGI, date(2024, 1, 1), _D))
    _try(lambda: e._factor_at(sym, _FIGI, _D, "mom_12_1"))  # real factor key (not "momentum")
    _try(lambda: e._daily_mean(sym, _FIGI, date(2024, 1, 1), _D))


def _r_altdata(sym):
    from altdata import ingest as a
    _try(lambda: a._resolve_figi(sym, "AAPL"))


RECIPES = [
    {"pkg": "optimiser", "outputs": ["solution", "weight"], "run": _r_optimiser},
    {"pkg": "signals", "outputs": ["score"], "run": _r_signals},
    {"pkg": "backtest", "outputs": ["run", "point"], "run": _r_backtest},
    {"pkg": "altdata", "outputs": ["wiki_map", "pageview"], "run": _r_altdata},
]

# DBs whose schemas/FKs we introspect (read sources live in sym; targets in each pkg DB).
_DBS = ["sym", "macro", "signals", "backtest", "optimiser", "altdata", "portfolios", "qrp"]

# Sqitch's own registry tables — never part of the data model.
_SQITCH = {"projects", "changes", "tags", "dependencies", "events", "releases"}

# The tables modeled as assets (bare names). FK edges are kept only among these — unmodeled sym
# side-tables (price_gaps, prices_review, instrument_xref, currency, exchange, …) are excluded.
_MODELED = {
    "securities", "security_names", "instrument", "security_symbology",
    "trading_calendar_version", "prices_raw", "fx_rate", "index_levels", "fact_returns",
    "fact_index_returns", "gics_scd", "fundamentals", "universe", "membership_event",
    "universe_member_resolution", "universe_membership", "pipeline_run_log",
    "series", "observation", "factor", "score", "run", "point", "solution", "weight",
    "portfolio", "portfolio_weight", "wiki_map", "pageview", "job",
}

# pg_catalog gives exactly one row per FK constraint. (information_schema.constraint_column_usage
# returns one row per referenced COLUMN — double-counting/misattributing composite & multi-FKs.)
_FK_SQL = """
SELECT c.relname AS child, p.relname AS parent
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_class p ON p.oid = con.confrelid
WHERE con.contype = 'f'
"""


def _fk_referential(base: dict) -> dict:
    """Auto-derive intra-DB referential edges from Postgres FKs (child references parent →
    parent is upstream). Kept only among modeled tables; Sqitch registry + self-refs excluded.
    Returns {child_table: [parent_tables]}."""
    out: dict = {}
    for db in _DBS:
        try:
            with psycopg.connect(**base, dbname=db) as c:
                rows = c.execute(_FK_SQL).fetchall()
        except Exception as e:
            print(f"  WARNING: FK introspection skipped for DB '{db}': {str(e)[:60]}")
            continue
        for child, parent in rows:
            if child in _SQITCH or parent in _SQITCH or child == parent:
                continue
            if child in _MODELED and parent in _MODELED:
                out.setdefault(child, set()).add(parent)
    return {k: sorted(v) for k, v in out.items()}


def _dsn() -> dict:
    # FULL (privileged) creds, by design — NOT the qrp_readonly role (Story QH.3). lineage
    # is an offline introspection generator, not a serving-path consumer: it reads sym-
    # INTERNAL relations and introspects pg_catalog across ALL package DBs (_combined_schema /
    # _fk_referential below), which the surface-only, sym-only read role cannot serve. It is
    # the documented exception to the read-only-role discipline (it only ever SELECTs; the
    # topology gate also excludes it from CONSUMER_PACKAGES). See deferred-work.md (QH.3).
    from qrp_api.config import _load_dotenv
    _load_dotenv()
    return dict(host=os.environ.get("PGHOST", "localhost"), port=os.environ.get("PGPORT", "5432"),
                user=os.environ.get("PGUSER", "postgres"), password=os.environ.get("PGPASSWORD", ""))


def _combined_schema(base: dict) -> dict:
    schema: dict = {}
    for db in _DBS:
        try:
            with psycopg.connect(**base, dbname=db) as c:
                for table, cols in pg_schema(c).items():
                    schema.setdefault(table, {}).update(cols)
        except Exception as e:
            print(f"  WARNING: schema introspection skipped for DB '{db}': {str(e)[:60]}")
    return schema


def generate() -> dict:
    base = _dsn()
    schema = _combined_schema(base)
    out: dict = {}
    for r in RECIPES:
        sess = CaptureSession()
        conn = None
        try:
            conn = psycopg.connect(**base, dbname="sym")
            r["run"](sess.wrap(conn))
        except Exception as exc:  # noqa: BLE001 — one recipe's failure (engine import,
            # query drift) must not abort generation for every other package.
            print(f"  WARNING: recipe '{r['pkg']}' failed: {type(exc).__name__}: {exc}")
            continue
        finally:
            if conn is not None:
                conn.close()
        # Surface silent degradation: a recipe that captured nothing (helper signature drift, no
        # data) would otherwise just emit no lineage with no signal.
        if not sess.captured:
            print(f"  WARNING: recipe '{r['pkg']}' captured 0 statements — lineage for "
                  f"{r['outputs']} not derived (read-helper drift or missing data?)")
        # synthesize a write per output table from its live columns (no write executed)
        synth = []
        for t in r["outputs"]:
            cols = list(schema.get(t, {}))
            if cols:
                synth.append(f"INSERT INTO {t} ({','.join(cols)}) "
                             f"VALUES ({','.join(['NULL'] * len(cols))})")
            else:
                print(f"  WARNING: output table '{t}' not found in schema — no write synthesized")
        edges = derive_edges(sess.captured + synth, schema=schema)
        for t in r["outputs"]:
            deps, col = to_dagster_metadata(edges, t)
            if deps:
                out[t] = {"deps": sorted(deps),
                          "column_lineage": {k: sorted(d["asset"] for d in v)
                                             for k, v in col.items()}}
            else:
                print(f"  WARNING: no deps derived for '{t}' — leaving hand-declared")
    fk = _fk_referential(base)
    # Clobber guards: a fully-empty run (DB unreachable) keeps the file; an empty DERIVED
    # with a non-empty FK side (every recipe silently captured nothing — signature drift)
    # must ALSO not wipe previously-derived transform lineage.
    if not out and not fk:
        print("  WARNING: generation produced nothing — keeping existing derived_lineage.py")
    elif not out:
        print(
            "  WARNING: zero transform lineage derived (FK side only) — keeping existing "
            "derived_lineage.py; investigate recipe/capture drift before regenerating"
        )
    else:
        _write(out, fk)
    return {"derived": out, "fk_referential": fk}


def _write(out: dict, fk: dict) -> None:
    path = Path(__file__).with_name("derived_lineage.py")
    lines = ['"""AUTO-GENERATED by `lineage.generate` — do not hand-edit.',
             "DERIVED: table-level + key-column lineage from downstream engines' captured SQL.",
             "FK_REFERENTIAL: intra-DB referential edges from Postgres foreign keys.",
             '"""', "", "DERIVED = {"]
    for t in sorted(out):
        lines.append(f"    {t!r}: {out[t]!r},")
    lines += ["}", "", "FK_REFERENTIAL = {"]
    for t in sorted(fk):
        lines.append(f"    {t!r}: {fk[t]!r},")
    lines += ["}", ""]
    # Atomic swap: a process killed mid-write must not leave a half-written module that
    # breaks the next `lineage.assets` import (and with it the whole code location).
    tmp = path.with_suffix(".py.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    result = generate()
    d, fk = result["derived"], result["fk_referential"]
    print(f"derived (transform) lineage for {len(d)} downstream tables:")
    for t in sorted(d):
        print(f"  {t:10} <- {d[t]['deps']}  keys={list(d[t]['column_lineage'])}")
    print(f"FK referential edges for {len(fk)} tables:")
    for t in sorted(fk):
        print(f"  {t:26} <- {fk[t]}")
