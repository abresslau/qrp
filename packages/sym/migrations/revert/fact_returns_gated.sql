-- Revert sym:fact_returns_gated from pg

BEGIN;

DROP INDEX IF EXISTS idx_fact_returns_published;
ALTER TABLE fact_returns DROP COLUMN gated;

COMMIT;
