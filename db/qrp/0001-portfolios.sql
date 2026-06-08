-- QRP-owned schema (NOT sym). Portfolios are weights-first: a time series of
-- effective-dated weight vectors over sym_id (composite_figi). Idempotent.
-- (A Sqitch migration can formalize this later; applied directly for the v1 slice.)

CREATE SCHEMA IF NOT EXISTS qrp;

CREATE TABLE IF NOT EXISTS qrp.portfolio (
    portfolio_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client        TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per (portfolio, effective date, constituent). Weight is a fraction (~sum to 1).
-- composite_figi is sym's identity; resolution happens at upload (unresolved are reported,
-- never fabricated). No FK to sym (consumer boundary) — validated on insert by the app.
CREATE TABLE IF NOT EXISTS qrp.portfolio_weight (
    portfolio_id   BIGINT NOT NULL REFERENCES qrp.portfolio(portfolio_id) ON DELETE CASCADE,
    as_of_date     DATE   NOT NULL,
    composite_figi CHAR(12) NOT NULL,
    weight         NUMERIC NOT NULL,
    PRIMARY KEY (portfolio_id, as_of_date, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_weight_pd
    ON qrp.portfolio_weight (portfolio_id, as_of_date);
