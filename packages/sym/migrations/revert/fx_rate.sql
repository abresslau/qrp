-- Revert sym:fx_rate from pg

BEGIN;

DROP TABLE IF EXISTS fx_rate;

COMMIT;
