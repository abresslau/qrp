-- Revert sym:securities from pg

BEGIN;

DROP TABLE IF EXISTS securities;

COMMIT;
