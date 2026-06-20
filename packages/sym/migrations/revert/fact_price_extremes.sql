-- Revert sym:fact_price_extremes from pg

BEGIN;

DROP TABLE IF EXISTS fact_price_extremes;

COMMIT;
