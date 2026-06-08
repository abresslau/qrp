-- Revert sym:fx_views from pg

BEGIN;

DROP VIEW IF EXISTS v_fx_daily;
DROP VIEW IF EXISTS v_fx;

COMMIT;
