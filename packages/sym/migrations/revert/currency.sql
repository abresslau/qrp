-- Revert sym:currency from pg

BEGIN;

DROP TABLE IF EXISTS currency;

COMMIT;
