-- Revert sym:price_storage from pg

BEGIN;

DROP TABLE IF EXISTS price_gaps;
DROP TABLE IF EXISTS pipeline_backfill_progress;
DROP TABLE IF EXISTS corporate_actions;
DROP TABLE IF EXISTS prices_raw;

COMMIT;
