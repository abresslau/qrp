-- Revert sym:pipeline_run_log_triggered_by from pg

BEGIN;

ALTER TABLE pipeline_run_log DROP COLUMN IF EXISTS triggered_by;

COMMIT;
