-- Revert sym:prices_raw_drop_retrieved_at from pg

BEGIN;

ALTER TABLE prices_raw ADD COLUMN retrieved_at TIMESTAMPTZ;

COMMIT;
