-- Deploy sym:index_extract to pg
-- requires: equity_extract

BEGIN;

-- Index/benchmark facts have been extracted into the `indices` peer package + database (DB-per-package
-- topology). The level series, the materialized index-returns + 52-week-extremes matrices, and the
-- universe→benchmark link are owned by the `indices` database now; the rows were copied there and every
-- consumer (the engine via sym cli/eod, the API sym gateway's index methods, data_monitor's
-- index_levels bucket, the lineage index_levels/fact_index_returns assets) reads the indices DB. Drop
-- the now-orphaned objects from the sym database.
--
-- STAYS in sym: instrument/instrument_xref (the sym_id identity bridge the index facts are keyed on —
-- read cross-DB), return_window (read by the sym API/portfolio/analytics; the indices DB has its own
-- seeded copy), securities/symbology/calendar/gics/fundamentals. sym_id (→ instrument) and universe_id
-- (→ universe) were SOFT references from the moved tables, so no FK ties them here.
-- Revert recreates the schema (empty) — the data lives in the indices database.

DROP TABLE IF EXISTS universe_benchmark;
DROP TABLE IF EXISTS fact_index_extremes;
DROP TABLE IF EXISTS fact_index_returns;
DROP TABLE IF EXISTS index_levels;

COMMIT;
