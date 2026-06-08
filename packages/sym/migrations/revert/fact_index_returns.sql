-- Revert sym:fact_index_returns from pg

BEGIN;

DROP TABLE IF EXISTS fact_index_returns;

COMMIT;
