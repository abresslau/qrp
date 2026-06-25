-- Deploy sym:equity_extract to pg
-- requires: universe_extract

BEGIN;

-- Equity prices/returns/corporate-actions have been extracted into the `equity` peer package +
-- database (DB-per-package topology). The OHLCV, factors, gap/anomaly logs, the per-figi ingest
-- cursor + run log, the deterministic v_prices_adjusted view, and the materialized PR/TR + 52-week
-- matrices are owned by the `equity` database now; the rows were copied there and every consumer
-- (the engine via sym cli/eod, backtest/signals/optimiser, analytics/portfolios, the API sym
-- gateway, data_monitor, operate /history, the lineage equity_prices/calculations buckets) reads
-- the equity DB. Drop the now-orphaned objects from the sym database.
--
-- STAYS in sym: securities/symbology/names/review-queue (identity), currency/exchange/
-- trading_calendar (reference), gics_* (classification), instrument/instrument_xref (the sym_id
-- bridge), fundamentals, return_window (the index facts FK it), index_levels/fact_index_returns/
-- fact_index_extremes/universe_benchmark (index/benchmark, keyed on sym_id). composite_figi was a
-- SOFT reference from the moved tables, so no FK ties them here.
-- Revert recreates the schema (empty) — the data lives in the equity database.

DROP VIEW IF EXISTS v_prices_adjusted;
DROP TABLE IF EXISTS prices_review;       -- composite FK -> prices_raw: drop before it
DROP TABLE IF EXISTS fact_price_extremes;
DROP TABLE IF EXISTS fact_returns;
DROP TABLE IF EXISTS price_gaps;
DROP TABLE IF EXISTS pipeline_backfill_progress;
DROP TABLE IF EXISTS pipeline_run_log;
DROP TABLE IF EXISTS corporate_actions;
DROP TABLE IF EXISTS prices_raw;
-- product() was used only by v_prices_adjusted (now gone); the equity DB has its own.
DROP AGGREGATE IF EXISTS product(numeric);

COMMIT;
