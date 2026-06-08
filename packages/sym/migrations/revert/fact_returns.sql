-- Revert sym:fact_returns from pg

BEGIN;

DROP TABLE IF EXISTS fact_returns;
DROP TABLE IF EXISTS return_window;

COMMIT;
