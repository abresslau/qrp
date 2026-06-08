-- Revert sym:universe_benchmark from pg

BEGIN;

DROP TABLE IF EXISTS universe_benchmark;

COMMIT;
