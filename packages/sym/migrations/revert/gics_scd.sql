-- Revert sym:gics_scd from pg

BEGIN;

DROP TABLE IF EXISTS gics_scd;

COMMIT;
