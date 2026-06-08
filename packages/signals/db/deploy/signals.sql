-- Deploy signals:signals to pg

BEGIN;

-- The `signals` package's own database: derived cross-sectional factor scores. The COMPUTE
-- reads sym READ-ONLY (fact_returns, fundamentals, universe_membership) over a separate
-- connection and writes only here; the read API serves these tables. No FK to sym
-- (value-only composite_figi keys; cross-DB reads via psycopg / DuckDB federation).
CREATE SCHEMA IF NOT EXISTS signals;

CREATE TABLE IF NOT EXISTS signals.factor (
    factor_key  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    direction   TEXT NOT NULL DEFAULT 'high'  -- 'high' or 'low' = which end is the favourable signal
);

CREATE TABLE IF NOT EXISTS signals.score (
    universe_id    TEXT NOT NULL,
    as_of_date     DATE NOT NULL,
    factor_key     TEXT NOT NULL REFERENCES signals.factor(factor_key),
    composite_figi CHAR(12) NOT NULL,
    raw            DOUBLE PRECISION NOT NULL,
    zscore         DOUBLE PRECISION,
    rank           INTEGER,            -- 1 = most favourable per the factor's direction
    pctile         DOUBLE PRECISION,   -- 0..1, 1 = most favourable
    PRIMARY KEY (universe_id, as_of_date, factor_key, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_signals_score_lookup
    ON signals.score (universe_id, factor_key, as_of_date, rank);

COMMIT;
