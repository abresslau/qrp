-- Deploy qrp:jobs to pg
-- requires: portfolios

BEGIN;

-- QRP-owned job ledger for the Operate surface: triggering sym's OWN idempotent
-- ops as guarded background jobs (run out of the web process). NOT sym's schema.
-- sym's own pipeline_run_log/validation_run_log remain the system-of-record for what
-- the op did; this table tracks the QRP-side trigger/status/exit/output tail. Idempotent.
CREATE TABLE IF NOT EXISTS qrp.job (
    job_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    op          TEXT NOT NULL,                       -- allowlisted op key (e.g. 'validate')
    args        JSONB NOT NULL DEFAULT '[]'::jsonb,  -- op arguments (e.g. ["ibov"])
    status      TEXT NOT NULL DEFAULT 'queued',      -- queued|running|success|failed|rejected
    exit_code   INTEGER,
    output      TEXT,                                -- tail of combined stdout/stderr
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_created ON qrp.job (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_op_status ON qrp.job (op, status);

COMMIT;
