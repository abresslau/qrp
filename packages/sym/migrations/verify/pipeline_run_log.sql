-- Verify sym:pipeline_run_log on pg

BEGIN;

SELECT run_id, mode, source, started_at, finished_at, attempted, loaded, skipped,
       errored, rows_written, anomaly_flags, gaps, status, detail, created_at
  FROM pipeline_run_log
 WHERE FALSE;

ROLLBACK;
