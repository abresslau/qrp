-- Revert sym:fundamentals from pg

BEGIN;

DROP TABLE IF EXISTS fundamentals;

COMMIT;
