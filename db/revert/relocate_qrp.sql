-- Revert qrp:relocate_qrp from pg

BEGIN;

-- Structural inverse: restore the qrp schema in the sym database (empty).
CREATE SCHEMA IF NOT EXISTS qrp;

CREATE TABLE IF NOT EXISTS qrp.portfolio (
    portfolio_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client        TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qrp.portfolio_weight (
    portfolio_id   BIGINT NOT NULL REFERENCES qrp.portfolio(portfolio_id) ON DELETE CASCADE,
    as_of_date     DATE   NOT NULL,
    composite_figi CHAR(12) NOT NULL,
    weight         NUMERIC NOT NULL,
    PRIMARY KEY (portfolio_id, as_of_date, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_weight_pd
    ON qrp.portfolio_weight (portfolio_id, as_of_date);

CREATE TABLE IF NOT EXISTS qrp.job (
    job_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    op          TEXT NOT NULL,
    args        JSONB NOT NULL DEFAULT '[]'::jsonb,
    status      TEXT NOT NULL DEFAULT 'queued',
    exit_code   INTEGER,
    output      TEXT,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_created ON qrp.job (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_op_status ON qrp.job (op, status);

COMMIT;
