-- Deploy portfolios:portfolios to pg

BEGIN;

-- The `portfolios` package's own database: portfolios are weights-first — a time series of
-- effective-dated weight vectors over sym_id (composite_figi). Split out from the `qrp`
-- database (which keeps only the Operate job ledger) so portfolio/client data is its own
-- module. No FK to sym (value-only composite_figi keys); sym labels/returns assembled in-app.
CREATE SCHEMA IF NOT EXISTS portfolios;

CREATE TABLE IF NOT EXISTS portfolios.portfolio (
    portfolio_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client        TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    base_currency CHAR(3) NOT NULL DEFAULT 'USD',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolios.portfolio_weight (
    portfolio_id   BIGINT NOT NULL REFERENCES portfolios.portfolio(portfolio_id) ON DELETE CASCADE,
    as_of_date     DATE   NOT NULL,
    composite_figi CHAR(12) NOT NULL,
    weight         NUMERIC NOT NULL,
    PRIMARY KEY (portfolio_id, as_of_date, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_weight_pd
    ON portfolios.portfolio_weight (portfolio_id, as_of_date);

COMMIT;
