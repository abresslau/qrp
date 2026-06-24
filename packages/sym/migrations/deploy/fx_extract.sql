-- Deploy sym:fx_extract to pg
-- requires: fx_rate_review_superseded

BEGIN;

-- FX has been extracted into its own `fx` peer package + database (DB-per-package topology).
-- The fx observations/views/function are now owned by the `fx` database; the rows were copied
-- there and every consumer (marketcap, fundamentals recompute, eod fx step, validate coverage,
-- the API FX matrix, the lineage fx bucket) now reads the fx DB. Drop the now-orphaned fx objects
-- from the sym database. `currency` STAYS (corporate_actions / exchange / prices_raw / securities
-- still FK it). Revert recreates the schema (empty) — the data lives in the fx database.

DROP VIEW IF EXISTS v_fx_daily;
DROP VIEW IF EXISTS v_fx;
DROP FUNCTION IF EXISTS fx_source_rank(TEXT);
DROP TABLE IF EXISTS fx_rate_review;
DROP TABLE IF EXISTS fx_rate;

COMMIT;
