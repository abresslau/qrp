-- Revert sym:backfill_floor_reached from pg

BEGIN;

ALTER TABLE pipeline_backfill_progress DROP COLUMN IF EXISTS floor_reached;

COMMIT;
