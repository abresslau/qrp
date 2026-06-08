-- Revert sym:index_levels from pg

BEGIN;

DROP TABLE IF EXISTS index_levels;

COMMIT;
