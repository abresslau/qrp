-- Revert sym:validation_logs from pg

BEGIN;

DROP TABLE IF EXISTS validation_run_log;
DROP TABLE IF EXISTS universe_member_completeness;

COMMIT;
