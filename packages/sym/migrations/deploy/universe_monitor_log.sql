-- Deploy sym:universe_monitor_log to pg
-- requires: universe

BEGIN;

-- Per-index daily-maintenance run log (Story U3.1, FR8/NFR2). One row per monitor
-- run with the changes it discovered + a status. last_successful_monitor for a
-- universe is max(run_at) where status='success'; a stale value drives the
-- liveness alarm (a frozen universe must never be mistaken for a stable one).
-- Append-only run record (akin to pipeline_run_log); no updated_at.
CREATE TABLE universe_monitor_log (
    monitor_run_id BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id    TEXT        NOT NULL,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source         TEXT,
    joiners        INTEGER     NOT NULL DEFAULT 0,
    leavers        INTEGER     NOT NULL DEFAULT 0,
    proposed       INTEGER     NOT NULL DEFAULT 0,
    applied        INTEGER     NOT NULL DEFAULT 0,
    status         TEXT        NOT NULL,
    detail         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_monitor_log_universe_fk FOREIGN KEY (universe_id)
        REFERENCES universe (universe_id),
    CONSTRAINT universe_monitor_log_status_chk CHECK (status IN ('success', 'gated', 'error')),
    CONSTRAINT universe_monitor_log_counts_chk
        CHECK (joiners >= 0 AND leavers >= 0 AND proposed >= 0 AND applied >= 0)
);

CREATE INDEX idx_universe_monitor_log_universe ON universe_monitor_log (universe_id, run_at DESC);

COMMENT ON TABLE  universe_monitor_log        IS 'Per-index maintenance run log (Story U3.1). last_successful_monitor = max(run_at) where status=success; drives the liveness alarm.';
COMMENT ON COLUMN universe_monitor_log.status IS 'success (discovered + recorded) | gated (changes routed to review) | error (empty/failed parse — never "no change").';
COMMENT ON COLUMN universe_monitor_log.applied  IS 'Change-events appended directly to the log this run.';
COMMENT ON COLUMN universe_monitor_log.proposed IS 'Changes staged to membership_proposal for review (U3.2), not yet appended.';

COMMIT;
