-- Revert sym:universe_monitor_log from pg

BEGIN;

DROP TABLE IF EXISTS universe_monitor_log;

COMMIT;
