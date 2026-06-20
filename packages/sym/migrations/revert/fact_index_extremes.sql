-- Revert sym:fact_index_extremes from pg

BEGIN;

DROP TABLE IF EXISTS fact_index_extremes;

COMMIT;
