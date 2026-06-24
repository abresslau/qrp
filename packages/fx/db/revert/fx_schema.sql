-- Revert fx:fx_schema from pg

BEGIN;

DROP VIEW IF EXISTS fx.v_fx_daily;
DROP VIEW IF EXISTS fx.v_fx;
DROP FUNCTION IF EXISTS fx.fx_source_rank(TEXT);
DROP TABLE IF EXISTS fx.fx_rate_review;
DROP TABLE IF EXISTS fx.fx_rate;
DROP TABLE IF EXISTS fx.currency;
DROP FUNCTION IF EXISTS fx.set_updated_at();
DROP SCHEMA IF EXISTS fx;

COMMIT;
