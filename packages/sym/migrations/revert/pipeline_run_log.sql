-- Revert sym:pipeline_run_log from pg

BEGIN;

DROP TABLE IF EXISTS pipeline_run_log;

COMMIT;
