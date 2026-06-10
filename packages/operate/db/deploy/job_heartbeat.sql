-- Deploy qrp_core:job_heartbeat to pg
-- requires: split_portfolios

BEGIN;

-- Heartbeat for running Operate jobs (Story O.2 / ADR-5's promised "QRP job
-- heartbeat"): the supervising worker stamps this while the child process runs,
-- so a job whose process died reads as ORPHANED (stale heartbeat) instead of
-- 'running' forever. NULL until the job starts.
ALTER TABLE qrp.job ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN qrp.job.heartbeat_at IS
    'Stamped ~10s by the supervising worker while the child runs; stale + status=running => orphaned.';

COMMIT;
