-- Verify qrp:jobs on pg

BEGIN;

SELECT job_id, op, args, status, exit_code, output, error, created_at, started_at, finished_at
  FROM qrp.job WHERE FALSE;

ROLLBACK;
