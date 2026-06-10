-- Deploy sym:pipeline_run_log_triggered_by to pg
-- requires: pipeline_run_log

BEGIN;

-- WHO caused this run (Story O.2): populated from the SYM_TRIGGERED_BY env var
-- (e.g. 'qrp-job:42' set by the Operate executor); NULL for manual CLI runs.
-- Correlates the QRP job ledger with sym's system-of-record run log.
ALTER TABLE pipeline_run_log ADD COLUMN IF NOT EXISTS triggered_by TEXT;

COMMENT ON COLUMN pipeline_run_log.triggered_by IS
    'Provenance of the trigger (e.g. qrp-job:<id> from SYM_TRIGGERED_BY); NULL = manual CLI.';

COMMIT;
