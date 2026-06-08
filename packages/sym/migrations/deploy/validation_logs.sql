-- Deploy sym:validation_logs to pg
-- requires: universe

BEGIN;

-- Cross-layer validation persistence (Epic V). Two append/refresh logs:
--   * universe_member_completeness (V1) -- per current universe member, which of
--     metadata/prices/fundamentals are present, an is_complete flag, the missing
--     dimensions, and a severity (ok/warn/fail) with a reason. Refreshed each run
--     (upsert), so it is a durable record of every incomplete tracked security.
--   * validation_run_log (V7) -- one row per `sym validate` run with per-status
--     check counts (akin to pipeline_run_log).

CREATE TABLE universe_member_completeness (
    universe_id      TEXT        NOT NULL,
    composite_figi   CHAR(12)    NOT NULL,
    has_name         BOOLEAN     NOT NULL,
    has_symbology    BOOLEAN     NOT NULL,
    has_gics         BOOLEAN     NOT NULL,
    has_prices       BOOLEAN     NOT NULL,
    has_fundamentals BOOLEAN     NOT NULL,
    is_complete      BOOLEAN     NOT NULL,
    missing          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    severity         TEXT        NOT NULL,
    reason           TEXT,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_member_completeness_pk PRIMARY KEY (universe_id, composite_figi),
    CONSTRAINT universe_member_completeness_universe_fk FOREIGN KEY (universe_id)
        REFERENCES universe (universe_id),
    CONSTRAINT universe_member_completeness_severity_chk
        CHECK (severity IN ('ok', 'warn', 'fail'))
);

CREATE INDEX idx_universe_member_completeness_incomplete
    ON universe_member_completeness (universe_id, severity) WHERE NOT is_complete;

CREATE TABLE validation_run_log (
    run_id      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    universe_id TEXT,
    checks      INTEGER     NOT NULL DEFAULT 0,
    passed      INTEGER     NOT NULL DEFAULT 0,
    warned      INTEGER     NOT NULL DEFAULT 0,
    failed      INTEGER     NOT NULL DEFAULT 0,
    status      TEXT        NOT NULL,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT validation_run_log_status_chk CHECK (status IN ('pass', 'warn', 'fail'))
);

CREATE INDEX idx_validation_run_log_run_at ON validation_run_log (run_at DESC);

COMMENT ON TABLE universe_member_completeness IS 'Per current universe member: metadata/prices/fundamentals presence + severity (Epic V, Story V1). Refreshed each validate run.';
COMMENT ON TABLE validation_run_log           IS 'One row per sym validate run with per-status check counts (Epic V, Story V7).';

COMMIT;
