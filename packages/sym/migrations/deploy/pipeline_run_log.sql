-- Deploy sym:pipeline_run_log to pg
-- requires: securities

-- Run-level pipeline log (FR-8, NFR-7). One row per backfill/delta/dev run with
-- aggregate counts + status. OI-3 decision: this is deliberately SEPARATE from
-- pipeline_backfill_progress -- that table is per-figi resume state (cursor), this
-- is run-level monitoring. DBeaver is the v1 monitoring surface; no external infra.
-- Append-only: written once at run end, never updated (no updated_at).
BEGIN;

CREATE TABLE pipeline_run_log (
    run_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mode          TEXT        NOT NULL,
    source        TEXT        NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ NOT NULL,
    attempted     INTEGER     NOT NULL DEFAULT 0,
    loaded        INTEGER     NOT NULL DEFAULT 0,
    skipped       INTEGER     NOT NULL DEFAULT 0,
    errored       INTEGER     NOT NULL DEFAULT 0,
    rows_written  BIGINT      NOT NULL DEFAULT 0,
    anomaly_flags INTEGER     NOT NULL DEFAULT 0,
    gaps          INTEGER     NOT NULL DEFAULT 0,
    status        TEXT        NOT NULL,
    detail        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pipeline_run_log_status_chk CHECK (status IN ('success', 'partial')),
    -- success iff zero failures (FR-8).
    CONSTRAINT pipeline_run_log_status_consistency_chk CHECK ((errored = 0) = (status = 'success')),
    CONSTRAINT pipeline_run_log_counts_chk
        CHECK (attempted >= 0 AND loaded >= 0 AND skipped >= 0 AND errored >= 0),
    CONSTRAINT pipeline_run_log_range_chk CHECK (finished_at >= started_at)
);

CREATE INDEX idx_pipeline_run_log_started ON pipeline_run_log (started_at DESC);

COMMENT ON TABLE  pipeline_run_log IS 'Run-level pipeline log (FR-8, NFR-7). OI-3: run-level counts, deliberately separate from the per-figi pipeline_backfill_progress cursor. Append-only; DBeaver is the v1 monitoring surface.';
COMMENT ON COLUMN pipeline_run_log.status IS 'success (0 errors) | partial (>=1 figi errored).';

COMMIT;
