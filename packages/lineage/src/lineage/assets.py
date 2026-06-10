"""The QRP data DAG, modeled as Dagster assets — with column schemas + column lineage.

Two kinds of node:

* **Runnable sym assets** (``@asset`` with a body) — tables sym owns and produces through a
  clean CLI command. Materializing one runs the real ``sym`` CLI (see ``sym_run``).
* **External assets** (``AssetSpec``) — tables produced outside Dagster's control (API/engine
  driven packages, config/manual inputs, code-backfilled sym tables). Lineage + docs only.

Every node carries:
* table-level docs: owning ``database``, ``table``, ``produced_by``, external ``source``;
* ``dagster/column_schema`` — the real columns (from the Sqitch migrations), so join keys like
  ``composite_figi`` and ``sym_id`` are visible per asset;
* ``dagster/column_lineage`` (where derivable) — column-level edges for the join keys and key
  measures. NOTE: the *visual* cross-asset column-lineage graph is a Dagster+ feature; in OSS the
  schema renders per asset and this lineage metadata is stored + GraphQL-queryable.

Edges (table and column) are taken from a verified trace of the codebase — no fabricated deps.

Key-space note: the equity chain keys on ``composite_figi`` and the instrument/index chain on
``sym_id``. They are bridged by ``instrument_xref`` (a ``composite_figi`` xref per equity
instrument; see docs/data-conventions.md §3), but that cross-key edge is not yet drawn here —
the two key-spaces still render as separate sub-graphs in this DAG.
"""

from __future__ import annotations

from dagster import (
    AssetKey,
    AssetSpec,
    TableColumn,
    TableColumnDep,
    TableColumnLineage,
    TableSchema,
    asset,
)

from .sym_run import run_sym

try:  # auto-derived lineage (lineage.generate); absent until first generation
    from . import derived_lineage as _dl
    DERIVED = getattr(_dl, "DERIVED", {})            # cross-package transform edges
    FK_REFERENTIAL = getattr(_dl, "FK_REFERENTIAL", {})  # intra-DB referential edges (FKs)
except ModuleNotFoundError:  # not yet generated — fall back to hand-declared
    DERIVED, FK_REFERENTIAL = {}, {}


def _k(*parts: str) -> AssetKey:
    return AssetKey(list(parts))


def _cols(*cols) -> TableSchema:
    """Build a TableSchema from (name, type[, 'PK']) tuples."""
    out = []
    for c in cols:
        is_pk = len(c) > 2 and c[2] == "PK"
        out.append(TableColumn(name=c[0], type=c[1],
                               description="primary key" if is_pk else None))
    return TableSchema(columns=out)


def _lin(**deps) -> TableColumnLineage:
    """Build TableColumnLineage from column -> [((db, table), upstream_col), ...]."""
    return TableColumnLineage(deps_by_column={
        col: [TableColumnDep(asset_key=_k(*ak), column_name=uc) for ak, uc in pairs]
        for col, pairs in deps.items()
    })


# --------------------------------------------------------------------------------------------
# Real column schemas (from the Sqitch migrations).
# --------------------------------------------------------------------------------------------

SCHEMAS = {
    # --- sym ---
    ("sym", "securities"): _cols(
        ("composite_figi", "char(12)", "PK"), ("share_class_figi", "char(12)"),
        ("status", "text"), ("delist_date", "date"), ("mic", "char(4)"),
        ("currency_code", "char(3)"), ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "security_names"): _cols(
        ("name_id", "bigint", "PK"), ("composite_figi", "char(12)"), ("name", "text"),
        ("source", "text"), ("valid_from", "date"), ("valid_to", "date"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "instrument"): _cols(
        ("sym_id", "bigint", "PK"), ("kind", "text"), ("name", "text"),
        ("currency_code", "char(3)"), ("status", "text"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "security_symbology"): _cols(
        ("symbology_id", "bigint", "PK"), ("composite_figi", "char(12)"),
        ("symbol_type", "text"), ("symbol_value", "text"), ("mic", "char(4)"),
        ("country_iso", "char(2)"), ("valid_from", "date"), ("valid_to", "date"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "trading_calendar_version"): _cols(
        ("calendar_version", "bigint", "PK"), ("mic", "char(4)"), ("library", "text"),
        ("library_version", "text"), ("content_hash", "text"), ("session_count", "integer"),
        ("first_session_date", "date"), ("last_session_date", "date"), ("is_current", "boolean"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "prices_raw"): _cols(
        ("composite_figi", "char(12)", "PK"), ("session_date", "date", "PK"),
        ("open", "numeric"), ("high", "numeric"), ("low", "numeric"), ("close", "numeric"),
        ("volume", "bigint"), ("currency_code", "char(3)"), ("source", "text"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "fx_rate"): _cols(
        ("base_currency", "char(3)", "PK"), ("quote_currency", "char(3)", "PK"),
        ("as_of_date", "date", "PK"), ("rate", "numeric"), ("source", "text", "PK"),
        ("inserted_at", "timestamptz"),
    ),
    ("sym", "index_levels"): _cols(
        ("sym_id", "bigint", "PK"), ("session_date", "date", "PK"),
        ("level", "numeric"), ("source", "text"), ("created_at", "timestamptz"),
    ),
    ("sym", "fact_returns"): _cols(
        ("composite_figi", "char(12)", "PK"), ("window_id", "integer", "PK"),
        ("as_of_date", "date", "PK"), ("pr", "numeric"), ("tr", "numeric"), ("input_hash", "text"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"), ("gated", "boolean"),
    ),
    ("sym", "fact_index_returns"): _cols(
        ("sym_id", "bigint", "PK"), ("window_id", "integer", "PK"),
        ("as_of_date", "date", "PK"), ("ret", "numeric"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "gics_scd"): _cols(
        ("gics_id", "bigint", "PK"), ("composite_figi", "char(12)"),
        ("sector_code", "text"), ("sector_name", "text"), ("industry_group_code", "text"),
        ("industry_group_name", "text"), ("industry_code", "text"), ("industry_name", "text"),
        ("sub_industry_code", "text"), ("sub_industry_name", "text"), ("source", "text"),
        ("valid_from", "date"), ("valid_to", "date"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "fundamentals"): _cols(
        ("composite_figi", "char(12)", "PK"), ("as_of_date", "date", "PK"),
        ("market_cap_lcy", "numeric"), ("market_cap_usd", "numeric"),
        ("shares_outstanding", "numeric"), ("currency_code", "char(3)"), ("source", "text"),
        ("detail", "jsonb"), ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "universe"): _cols(
        ("universe_id", "text", "PK"), ("name", "text"), ("kind", "text"), ("config", "jsonb"),
        ("pit_valid_from", "date"), ("source_pref", "jsonb"),
        ("created_at", "timestamptz"), ("updated_at", "timestamptz"),
    ),
    ("sym", "membership_event"): _cols(
        ("event_id", "bigint", "PK"), ("universe_id", "text"), ("raw_identifier", "text"),
        ("change", "text"), ("effective_date", "date"), ("effective_date_precision", "text"),
        ("source", "text"), ("provenance", "jsonb"), ("recorded_at", "timestamptz"),
    ),
    ("sym", "universe_member_resolution"): _cols(
        ("universe_id", "text", "PK"), ("raw_identifier", "text", "PK"),
        ("composite_figi", "char(12)"), ("share_class_figi", "char(12)"),
        ("resolution_status", "text"), ("detail", "text"), ("resolved_at", "timestamptz"),
    ),
    ("sym", "universe_membership"): _cols(
        ("universe_id", "text"), ("composite_figi", "char(12)"), ("raw_identifier", "text"),
        ("valid_from", "date"), ("valid_to", "date"), ("source", "text"),
    ),
    ("sym", "pipeline_run_log"): _cols(
        ("run_id", "bigint", "PK"), ("mode", "text"), ("source", "text"),
        ("started_at", "timestamptz"), ("finished_at", "timestamptz"), ("attempted", "integer"),
        ("loaded", "integer"), ("skipped", "integer"), ("errored", "integer"),
        ("rows_written", "bigint"), ("anomaly_flags", "integer"), ("gaps", "integer"),
        ("status", "text"), ("detail", "text"), ("created_at", "timestamptz"),
    ),
    # --- macro ---
    ("macro", "series"): _cols(
        ("series_id", "text", "PK"), ("source", "text"), ("name", "text"), ("geo", "text"),
        ("unit", "text"), ("frequency", "text"), ("updated_at", "timestamptz"),
    ),
    ("macro", "observation"): _cols(
        ("series_id", "text", "PK"), ("obs_date", "date", "PK"), ("value", "double precision"),
    ),
    # --- signals ---
    ("signals", "factor"): _cols(
        ("factor_key", "text", "PK"), ("name", "text"), ("description", "text"),
        ("direction", "text"),
    ),
    ("signals", "score"): _cols(
        ("universe_id", "text", "PK"), ("as_of_date", "date", "PK"),
        ("factor_key", "text", "PK"), ("composite_figi", "char(12)", "PK"),
        ("raw", "double precision"), ("zscore", "double precision"), ("rank", "integer"),
        ("pctile", "double precision"),
    ),
    # --- backtest ---
    ("backtest", "run"): _cols(
        ("run_id", "bigint", "PK"), ("created_at", "timestamptz"), ("factor", "text"),
        ("universe_id", "text"), ("top_pct", "double precision"), ("rebalance", "text"),
        ("start_date", "date"), ("end_date", "date"), ("n_days", "integer"),
        ("n_rebalances", "integer"), ("summary", "jsonb"),
    ),
    ("backtest", "point"): _cols(
        ("run_id", "bigint", "PK"), ("obs_date", "date", "PK"),
        ("strat_cum", "double precision"), ("base_cum", "double precision"),
    ),
    # --- optimiser ---
    ("optimiser", "solution"): _cols(
        ("solution_id", "bigint", "PK"), ("created_at", "timestamptz"), ("universe_id", "text"),
        ("method", "text"), ("n_assets", "integer"), ("lookback_days", "integer"),
        ("exp_return", "double precision"), ("exp_vol", "double precision"),
        ("sharpe", "double precision"), ("ew_vol", "double precision"), ("summary", "jsonb"),
    ),
    ("optimiser", "weight"): _cols(
        ("solution_id", "bigint", "PK"), ("composite_figi", "char(12)", "PK"),
        ("ticker", "text"), ("weight", "double precision"),
    ),
    # --- portfolios ---
    ("portfolios", "portfolio"): _cols(
        ("portfolio_id", "bigint", "PK"), ("client", "text"), ("name", "text"),
        ("base_currency", "char(3)"), ("created_at", "timestamptz"),
    ),
    ("portfolios", "portfolio_weight"): _cols(
        ("portfolio_id", "bigint", "PK"), ("as_of_date", "date", "PK"),
        ("composite_figi", "char(12)", "PK"), ("weight", "numeric"),
    ),
    # --- altdata ---
    ("altdata", "wiki_map"): _cols(
        ("composite_figi", "char(12)", "PK"), ("ticker", "text"), ("name", "text"),
        ("article", "text"),
    ),
    ("altdata", "pageview"): _cols(
        ("composite_figi", "char(12)", "PK"), ("obs_date", "date", "PK"), ("views", "bigint"),
    ),
    # --- operate ---
    ("operate", "job"): _cols(
        ("job_id", "bigint", "PK"), ("op", "text"), ("args", "jsonb"), ("status", "text"),
        ("exit_code", "integer"), ("output", "text"), ("error", "text"),
        ("created_at", "timestamptz"), ("started_at", "timestamptz"),
        ("finished_at", "timestamptz"),
    ),
}


# --------------------------------------------------------------------------------------------
# Column lineage — composite_figi chain, sym_id chain, and key measures.
# --------------------------------------------------------------------------------------------

LINEAGE = {
    # composite_figi propagation (equity chain)
    ("sym", "security_names"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("sym", "security_symbology"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("sym", "prices_raw"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("sym", "gics_scd"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("sym", "fundamentals"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")],
        market_cap_usd=[(("sym", "fx_rate"), "rate")],  # USD recompute via FX
    ),
    ("sym", "universe_member_resolution"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("sym", "fact_returns"): _lin(
        composite_figi=[(("sym", "prices_raw"), "composite_figi")],
        pr=[(("sym", "prices_raw"), "close")],
        tr=[(("sym", "prices_raw"), "close")],
    ),
    ("sym", "universe_membership"): _lin(
        composite_figi=[(("sym", "universe_member_resolution"), "composite_figi")]),
    ("signals", "score"): _lin(
        composite_figi=[(("sym", "fact_returns"), "composite_figi"),
                        (("sym", "universe_membership"), "composite_figi")],
        raw=[(("sym", "fact_returns"), "pr"), (("sym", "fundamentals"), "market_cap")],
    ),
    ("optimiser", "weight"): _lin(
        composite_figi=[(("sym", "fact_returns"), "composite_figi"),
                        (("sym", "fundamentals"), "composite_figi"),
                        (("sym", "security_symbology"), "composite_figi"),
                        (("sym", "universe_membership"), "composite_figi")],
        weight=[(("sym", "fact_returns"), "pr")],
    ),
    ("portfolios", "portfolio_weight"): _lin(
        composite_figi=[(("sym", "securities"), "composite_figi")]),
    ("altdata", "wiki_map"): _lin(
        composite_figi=[(("sym", "security_symbology"), "composite_figi")]),
    ("altdata", "pageview"): _lin(
        composite_figi=[(("altdata", "wiki_map"), "composite_figi")]),
    # sym_id propagation (instrument / index chain)
    ("sym", "index_levels"): _lin(
        sym_id=[(("sym", "instrument"), "sym_id")]),
    ("sym", "fact_index_returns"): _lin(
        sym_id=[(("sym", "index_levels"), "sym_id")],
        ret=[(("sym", "index_levels"), "level")],
    ),
}


_NAME_INDEX = {t: (db, t) for (db, t) in SCHEMAS}


def _resolve(name: str) -> tuple[str, str] | None:
    """Bare source-table name -> a KNOWN (db, table) asset key, or None if not a modeled asset
    (never fabricate a key — that would create a dangling Dagster dependency)."""
    return _NAME_INDEX.get(name)


def _dedup(items: list) -> list:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _fk_parents(table: str) -> list[tuple[str, str]]:
    """Referential parents of a table from Postgres FKs, resolved to known asset keys.

    Drops one side of a direct 2-cycle (mutual FKs A<->B) deterministically, so the merged dep
    graph can't go cyclic. (Broader cycles would fail loudly at `dagster definitions validate`.)
    """
    out = []
    for p in FK_REFERENTIAL.get(table, []):
        if table in FK_REFERENTIAL.get(p, []) and p > table:
            continue  # mutual FK: keep only the edge into the lexicographically-smaller table
        if (r := _resolve(p)):
            out.append(r)
    return out


_EDGE_LIST: list[tuple[str, str, str]] = []  # (from_table, to_table, basis) — for the diagram


def _record_edges(deps: list, target: str, basis: str) -> None:
    for d in deps:
        _EDGE_LIST.append((d[1], target, basis))


def edges() -> list[tuple[str, str, str]]:
    """All table-level lineage edges (from_table, to_table, basis), deduped — for diagram/export
    (deduped because `_EDGE_LIST` is appended at import and could double on a module reload)."""
    seen, out = set(), []
    for e in _EDGE_LIST:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def key_tables(key: str) -> set[str]:
    """Tables whose schema carries a given column (e.g. composite_figi / sym_id)."""
    return {t for (db, t), sch in SCHEMAS.items() if any(c.name == key for c in sch.columns)}


def _md(key_tuple, database, table, produced_by, source=None, note=None) -> dict:
    md = {"database": database, "table": table, "produced_by": produced_by}
    if source:
        md["source"] = source
    if note:
        md["note"] = note
    if key_tuple in SCHEMAS:
        md["dagster/column_schema"] = SCHEMAS[key_tuple]
    if key_tuple in LINEAGE:
        md["dagster/column_lineage"] = LINEAGE[key_tuple]
    return md


# --------------------------------------------------------------------------------------------
# Runnable sym assets — materializing these runs the identical `sym` CLI an operator would type.
# --------------------------------------------------------------------------------------------

def _sym_asset(slug, key_tuple, deps, description, metadata, sym_args):
    fk = _fk_parents(key_tuple[-1])  # auto FK referential parents
    _record_edges(deps, key_tuple[-1], "declared")
    _record_edges(fk, key_tuple[-1], "referential")
    deps = _dedup(list(deps) + fk)

    def fn(context):
        return run_sym(context, *sym_args)

    fn.__name__ = f"sym_{slug}"
    return asset(
        key=_k(*key_tuple),
        deps=[_k(*d) for d in deps],
        description=description,
        metadata=metadata,
        group_name="sym",
        kinds={"postgres"},
    )(fn)


_RUNNABLE_SYM = [
    _sym_asset(
        "securities", ("sym", "securities"), [],
        "Security master — instruments resolved to composite FIGIs.",
        _md(("sym", "securities"), "sym", "securities", "`sym resolve`", source="OpenFIGI API"),
        ["resolve"],
    ),
    _sym_asset(
        "security_names", ("sym", "security_names"), [("sym", "securities")],
        "Point-in-time security display names.",
        _md(("sym", "security_names"), "sym", "security_names", "`sym names`",
            source="OpenFIGI API"),
        ["names"],
    ),
    _sym_asset(
        "trading_calendar_version", ("sym", "trading_calendar_version"), [],
        "Snapshotted exchange trading calendars (versioned for deterministic recompute).",
        _md(("sym", "trading_calendar_version"), "sym", "trading_calendar_version",
            "`sym snapshot-calendar`", source="exchange_calendars"),
        ["snapshot-calendar"],
    ),
    _sym_asset(
        "prices_raw", ("sym", "prices_raw"), [("sym", "securities")],
        "True-raw OHLCV bars (split/div un-adjusted), source-stamped and immutable.",
        _md(("sym", "prices_raw"), "sym", "prices_raw",
            "`sym load` (fill / --overwrite)", source="yfinance (swappable adapter)"),
        ["load"],
    ),
    _sym_asset(
        "fx_rate", ("sym", "fx_rate"), [],
        "USD-base FX rates, multi-source with reconciliation; immutable per source/pair/date.",
        _md(("sym", "fx_rate"), "sym", "fx_rate", "`sym fx load` (fill)",
            source="Frankfurter · ECB SDMX · fawazahmed0"),
        ["fx", "load"],
    ),
    _sym_asset(
        "index_levels", ("sym", "index_levels"), [],
        "Benchmark index level series (keyed by sym_id).",
        _md(("sym", "index_levels"), "sym", "index_levels",
            "`sym benchmarks` / `sym msci-import`", source="Yahoo indices · MSCI files"),
        ["benchmarks"],
    ),
    _sym_asset(
        "fact_returns", ("sym", "fact_returns"),
        [("sym", "prices_raw"), ("sym", "trading_calendar_version")],
        "Materialized PR/TR return matrix; recomputed deterministically via input_hash.",
        _md(("sym", "fact_returns"), "sym", "fact_returns", "`sym recompute`",
            note="inputs: prices_raw + pinned calendar version"),
        ["recompute"],
    ),
    _sym_asset(
        "gics_scd", ("sym", "gics_scd"), [("sym", "securities")],
        "GICS sector/industry classification, slowly-changing (SCD).",
        _md(("sym", "gics_scd"), "sym", "gics_scd", "`sym classify`",
            source="financedatabase GICS"),
        ["classify"],
    ),
    _sym_asset(
        "fundamentals", ("sym", "fundamentals"),
        [("sym", "securities"), ("sym", "fx_rate")],
        "Shares outstanding + market cap (local and USD via fx_rate).",
        _md(("sym", "fundamentals"), "sym", "fundamentals",
            "`sym fundamentals` (+ market_cap_usd recompute)", source="yfinance"),
        ["fundamentals"],
    ),
    _sym_asset(
        "membership_event", ("sym", "membership_event"), [("sym", "universe")],
        "Append-only universe join/leave event log.",
        _md(("sym", "membership_event"), "sym", "membership_event", "`sym universe monitor`",
            source="universe provider (config-driven)"),
        ["universe", "monitor"],
    ),
    _sym_asset(
        "universe_membership", ("sym", "universe_membership"),
        [("sym", "membership_event"), ("sym", "universe_member_resolution")],
        "Point-in-time membership intervals, projected from the event log.",
        _md(("sym", "universe_membership"), "sym", "universe_membership",
            "`sym universe refresh` (rebuild_projection)"),
        ["universe", "refresh"],
    ),
]


# --------------------------------------------------------------------------------------------
# External assets — produced outside Dagster (API/engine/config/code-backfill). Lineage only.
# --------------------------------------------------------------------------------------------

def _spec(key_tuple, deps, group, description, database, table, produced_by,
          source=None, note=None, kinds=("postgres",)) -> AssetSpec:
    md = _md(key_tuple, database, table, produced_by, source=source, note=note)
    derived = DERIVED.get(table)
    if derived:
        # UNION auto-derived cross-package sources with the hand-declared deps — derived ADDS or
        # confirms, never silently removes a hand-declared edge (guards incomplete derivation).
        # Unknown source names are dropped, not fabricated into ("sym", name) dangling keys.
        cross = [r for s in derived["deps"] if (r := _resolve(s))]
        deps = _dedup(cross + list(deps))
        if derived.get("column_lineage"):
            # derived column_lineage carries ONLY pass-through KEY_COLUMNS (composite_figi/sym_id),
            # so the upstream column name == the key (column_name=k) by construction.
            md["dagster/column_lineage"] = TableColumnLineage(deps_by_column={
                k: [TableColumnDep(asset_key=_k(*r), column_name=k)
                    for s in srcs if (r := _resolve(s))]
                for k, srcs in derived["column_lineage"].items()})
        md["lineage_basis"] = "auto-derived (lineage.generate)"
    fk = _fk_parents(table)  # auto FK referential parents
    _record_edges(deps, table, "auto-derived" if derived else "declared")
    _record_edges(fk, table, "referential")
    deps = _dedup(list(deps) + fk)
    return AssetSpec(
        key=_k(*key_tuple),
        deps=[_k(*d) for d in deps],
        group_name=group,
        description=description,
        metadata=md,
        kinds=set(kinds),
    )


_EXTERNAL = [
    # --- sym: code-backfilled / config / provenance side-tables ---
    _spec(("sym", "instrument"), [("sym", "securities")], "sym",
          "Canonical instrument records (sym_id surrogate; index chain root).",
          "sym", "instrument", "code backfill (identity layer)"),
    _spec(("sym", "security_symbology"), [("sym", "securities")], "sym",
          "Resolved ticker/exchange symbology for instruments.",
          "sym", "security_symbology", "identity layer (`sym resolve`)"),
    _spec(("sym", "universe"), [], "sym",
          "Universe registry (index/custom-list definitions).",
          "sym", "universe", "`sym universe add`", source="user JSON config"),
    _spec(("sym", "universe_member_resolution"), [("sym", "membership_event")], "sym",
          "Resolved members per universe refresh (feeds the projection).",
          "sym", "universe_member_resolution", "`sym universe refresh`"),
    _spec(("sym", "fact_index_returns"), [("sym", "index_levels")], "sym",
          "Benchmark index returns, derived from index_levels (sym_id chain).",
          "sym", "fact_index_returns", "`sym benchmarks` (recompute_index_returns)"),
    _spec(("sym", "pipeline_run_log"), [], "sym",
          "Run-level ingestion provenance (mode, source, rows, status, timing). "
          "The existing what/source/when audit log.",
          "sym", "pipeline_run_log", "every `sym` load run",
          note="existing run-level provenance"),
    # --- macro ---
    _spec(("macro", "series"), [], "macro", "Macro series catalog.",
          "macro", "series", "macro ingest", source="World Bank · ECB Data Portal"),
    _spec(("macro", "observation"), [("macro", "series")], "macro",
          "Macro observations per series.",
          "macro", "observation", "macro ingest", source="World Bank · ECB"),
    # --- signals ---
    _spec(("signals", "factor"), [], "signals",
          "Factor catalog (momentum, volatility, size, ...).",
          "signals", "factor", "signals compute (catalog ensure)"),
    _spec(("signals", "score"),
          [("sym", "fact_returns"), ("sym", "fundamentals"),
           ("sym", "universe_membership"), ("signals", "factor")],
          "signals", "Cross-sectional factor scores per universe/asof.",
          "signals", "score", "signals.compute_universe()",
          note="reads sym fact_returns + fundamentals + membership"),
    # --- backtest ---
    _spec(("backtest", "run"), [], "backtest", "Backtest run metadata.",
          "backtest", "run", "backtest engine"),
    _spec(("backtest", "point"),
          [("backtest", "run"), ("sym", "fact_returns"), ("sym", "universe_membership")],
          "backtest", "Backtest equity-curve points.",
          "backtest", "point", "backtest.run_backtest()",
          note="reads sym fact_returns + membership"),
    # --- optimiser ---
    _spec(("optimiser", "solution"), [], "optimiser", "Optimisation solution metadata.",
          "optimiser", "solution", "optimiser engine"),
    _spec(("optimiser", "weight"),
          [("optimiser", "solution"), ("sym", "fact_returns"), ("sym", "fundamentals"),
           ("sym", "security_symbology"), ("sym", "universe_membership")],
          "optimiser", "Optimised portfolio weights (mean-variance over a return covariance).",
          "optimiser", "weight", "optimiser.compute_solution()",
          note="reads sym fact_returns + fundamentals + security_symbology + membership"),
    # --- portfolios ---
    _spec(("portfolios", "portfolio"), [], "portfolios", "Client portfolio definitions.",
          "portfolios", "portfolio", "API POST /api/portfolios", source="user input"),
    _spec(("portfolios", "portfolio_weight"),
          [("portfolios", "portfolio"), ("sym", "securities")],
          "portfolios", "Portfolio holdings/weights (tickers resolved via sym).",
          "portfolios", "portfolio_weight", "API POST /api/portfolios/{id}/weights"),
    # --- altdata ---
    _spec(("altdata", "wiki_map"), [("sym", "security_symbology")], "altdata",
          "Composite-FIGI ↔ Wikipedia article mapping.",
          "altdata", "wiki_map", "altdata.load_attention()",
          note="resolves figis via sym security_symbology (ticker lookup)"),
    _spec(("altdata", "pageview"), [("altdata", "wiki_map")], "altdata",
          "Wikipedia pageview attention series.",
          "altdata", "pageview", "altdata.load_attention()",
          source="Wikimedia pageviews API"),
    # --- analytics (computed, not persisted) ---
    _spec(("analytics", "metrics"),
          [("portfolios", "portfolio_weight"), ("sym", "fact_returns"),
           ("sym", "fact_index_returns")],
          "analytics",
          "Portfolio risk/return analytics (Sharpe, alpha, beta, tracking error). "
          "Computed on request — not persisted to a table.",
          "analytics", "(computed)", "analytics gateway",
          note="reads portfolio_weight + sym returns/index returns", kinds=("python",)),
    # --- operate (control plane) ---
    _spec(("operate", "job"), [], "operate",
          "Operate job ledger — orchestrates sym ops as subprocesses (control plane, "
          "orthogonal to the data DAG).",
          "qrp", "job", "operate gateway"),
]


def all_assets():
    """Every node in the QRP data DAG: runnable sym assets + external assets."""
    return [*_RUNNABLE_SYM, *_EXTERNAL]
