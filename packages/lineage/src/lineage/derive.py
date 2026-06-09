"""Automatically derive lineage from the SQL statements a loader executes.

QRP's transforms are Python compute (read via ``SELECT``, write via ``INSERT…VALUES`` with
numpy-computed values), so the read→write link lives in the *run*, not in any single statement.
We classify each captured statement with sqlglot, then correlate reads↔writes within a run into
**table-level** edges — the derivation + cross-DB edges that foreign keys cannot express.

Edge ``basis`` distinguishes confidence:
* ``"sql"`` — a direct ``INSERT…SELECT``/CTAS edge, provable from one statement;
* ``"run-correlation"`` — a ``VALUES``/compute write paired with reads that occurred *before* it
  in the same run (the link is in Python, so this is a table-level inference).

Column level is automatic only for **pass-through join keys** (``composite_figi``, ``sym_id``):
a read table carries a key if that column exists in its schema (so ``SELECT *`` and unqualified
columns still resolve). Computed measures are produced in Python and are not recoverable.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

# The cross-package join keys we can trace at the column level (they pass through unchanged).
KEY_COLUMNS = {"composite_figi", "sym_id"}

_NAMED_PLACEHOLDER = re.compile(r"%\([^)]*\)s")
_PCT_SENTINEL = "\x00PCT\x00"


def pg_schema(conn) -> dict:
    """Build ``{table: {column: type}}`` from ``information_schema`` (the leverage-Postgres hook).

    Keyed by bare table name (matches what sqlglot sees in SQL). On a Postgres-per-package
    instance, same-named tables in different DBs are queried separately; within one DB, names are
    unique. Used for pass-through-key detection (does a read table carry composite_figi/sym_id?).
    """
    rows = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
        "ORDER BY table_name, ordinal_position"
    ).fetchall()
    out: dict = {}
    for table, col, dtype in rows:
        out.setdefault(table, {})[col] = dtype
    return out


def _norm(sql: str) -> str:
    """Neutralize psycopg placeholders for the parser without corrupting ``%%`` literals."""
    sql = sql.replace("%%", _PCT_SENTINEL)        # protect escaped percent
    sql = _NAMED_PLACEHOLDER.sub("NULL", sql)     # %(name)s -> NULL
    sql = sql.replace("%s", "NULL")               # %s -> NULL
    return sql.replace(_PCT_SENTINEL, "%")        # restore a literal percent (valid modulo/LIKE)


def _real_tables(node, cte_names: set[str]) -> set[str]:
    """Table names referenced in ``node``, excluding CTE aliases (which are not real tables)."""
    return {t.name for t in node.find_all(exp.Table) if t.name not in cte_names}


def classify(sql: str, dialect: str = "postgres") -> dict | None:
    """Classify one statement. Returns a dict with ``kind`` in {"read","write"} or None.

    write: ``{kind, target, target_cols, sources, source_cols, basis}`` where ``basis`` is
    ``"sql"`` (INSERT…SELECT / CTAS — sources proven in-statement) or ``"values"`` (no inline
    select — sources come from run correlation).
    read:  ``{kind, tables, cols}``.
    """
    try:
        tree = sqlglot.parse_one(_norm(sql), dialect=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    cte_names = {c.alias_or_name for c in tree.find_all(exp.CTE)}

    def _target_of(this) -> tuple[str | None, list[str]]:
        if isinstance(this, exp.Schema):
            tbl = this.this.name if isinstance(this.this, exp.Table) else None
            return tbl, [e.name for e in this.expressions]
        if isinstance(this, exp.Table):
            return this.name, []
        return None, []

    # --- writes ---
    if isinstance(tree, exp.Insert):
        target, target_cols = _target_of(tree.this)
        if tree.find(exp.Select) is not None:  # INSERT…SELECT — sources span the WHOLE tree
            return {"kind": "write", "target": target, "target_cols": target_cols,
                    "sources": _real_tables(tree, cte_names) - {target},  # incl. CTE bodies
                    "source_cols": {c.name for c in tree.find_all(exp.Column)}, "basis": "sql"}
        return {"kind": "write", "target": target, "target_cols": target_cols,
                "sources": set(), "source_cols": set(), "basis": "values"}

    if isinstance(tree, exp.Create) and tree.find(exp.Select) is not None:  # CTAS
        target, target_cols = _target_of(tree.this)
        return {"kind": "write", "target": target, "target_cols": target_cols,
                "sources": _real_tables(tree, cte_names) - {target},
                "source_cols": {c.name for c in tree.find_all(exp.Column)}, "basis": "sql"}

    if isinstance(tree, (exp.Update, exp.Delete, exp.Merge)):
        tbl = tree.find(exp.Table)
        target = tbl.name if tbl is not None else None
        # basis is always "sql": these derive ONLY from their own in-statement FROM/USING sources,
        # never from unrelated prior reads. A plain DELETE / no-FROM UPDATE has no sources -> no
        # edges (prevents fabricating run-correlation edges to every prior read).
        return {"kind": "write", "target": target, "target_cols": [],
                "sources": _real_tables(tree, cte_names) - {target},
                "source_cols": {c.name for c in tree.find_all(exp.Column)}, "basis": "sql"}

    # --- reads ---
    if isinstance(tree, exp.Select) or tree.find(exp.Select) is not None:
        return {"kind": "read",
                "tables": _real_tables(tree, cte_names),
                "cols": {c.name for c in tree.find_all(exp.Column)}}
    return None


def _table_keys(table: str, referenced_cols: set[str], schema: dict | None) -> set[str]:
    """Pass-through keys a table carries: from its schema (preferred) ∪ referenced columns."""
    keys = {k for k in KEY_COLUMNS if k in referenced_cols}
    if schema and table in schema:
        keys |= {k for k in KEY_COLUMNS if k in schema[table]}
    return keys


def derive_edges(statements: list[str], schema: dict | None = None,
                 dialect: str = "postgres") -> list[dict]:
    """Correlate captured statements (one run, in order) into table-level lineage edges.

    Returns dicts: ``{"from", "to", "keys": [pass-through key cols], "basis"}``. Reads are
    accumulated in statement order; a VALUES/compute write is linked only to reads seen *before*
    it. INSERT…SELECT/CTAS writes get direct in-statement edges.
    """
    reads_before: dict[str, set[str]] = {}   # table -> pass-through keys carried (so far)
    edges: list[dict] = []

    for sql in statements:
        c = classify(sql, dialect)
        if not c:
            continue
        if c["kind"] == "read":
            for t in c["tables"]:
                reads_before.setdefault(t, set())
                reads_before[t] |= _table_keys(t, c["cols"], schema)
            continue

        # write
        target = c["target"]
        wkeys = set(c["target_cols"]) & KEY_COLUMNS
        if c["basis"] == "sql":  # direct, in-statement sources
            for s in c["sources"]:
                skeys = _table_keys(s, c["source_cols"], schema)
                edges.append({"from": s, "to": target,
                              "keys": sorted(wkeys & skeys if wkeys else skeys & KEY_COLUMNS),
                              "basis": "sql (INSERT...SELECT/CTAS)"})
            # an INSERT…SELECT source also counts as a read for later writes
            for s in c["sources"]:
                reads_before.setdefault(s, set())
                reads_before[s] |= _table_keys(s, c["source_cols"], schema)
        else:  # values/compute write — correlate with reads seen before it
            for s, skeys in sorted(reads_before.items()):
                if s == target:
                    continue
                edges.append({"from": s, "to": target,
                              "keys": sorted(wkeys & skeys),
                              "basis": "run-correlation (read+write in same run)"})

    # dedup, unioning keys for repeated (from,to,basis)
    merged: dict[tuple, set[str]] = {}
    order: list[tuple] = []
    for e in edges:
        k = (e["from"], e["to"], e["basis"])
        if k not in merged:
            merged[k] = set()
            order.append(k)
        merged[k] |= set(e["keys"])
    return [{"from": f, "to": t, "basis": b, "keys": sorted(merged[(f, t, b)])}
            for (f, t, b) in order]


def to_dagster_metadata(edges: list[dict], target_table: str):
    """Build ``(deps, column_lineage)`` for one target table's key columns, ready for an asset.

    Note: ``target_table`` is a bare name; the Dagster wiring step resolves bare names to full
    asset keys via an explicit table→asset-key index to avoid cross-package collisions.
    """
    deps = sorted({e["from"] for e in edges if e["to"] == target_table})
    col_lineage: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for e in edges:
        if e["to"] != target_table:
            continue
        for key in e["keys"]:
            if (key, e["from"]) in seen:
                continue
            seen.add((key, e["from"]))
            col_lineage.setdefault(key, []).append({"asset": e["from"], "column": key})
    return deps, col_lineage
