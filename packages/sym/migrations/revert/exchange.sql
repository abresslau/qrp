-- Revert sym:exchange from pg

BEGIN;

DROP TABLE IF EXISTS exchange;

COMMIT;
