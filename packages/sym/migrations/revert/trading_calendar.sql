-- Revert sym:trading_calendar from pg

BEGIN;

DROP TABLE IF EXISTS trading_calendar;
DROP TABLE IF EXISTS trading_calendar_version;

COMMIT;
