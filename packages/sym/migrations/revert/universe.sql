-- Revert sym:universe from pg

BEGIN;

DROP TABLE IF EXISTS universe;

COMMIT;
