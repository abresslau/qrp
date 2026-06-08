-- Deploy qrp:signal to pg

BEGIN;

-- QRP-managed `signal` schema (NOT sym): derived cross-sectional factor scores computed
-- from sym data (fact_returns, fundamentals) per universe per as-of. Idempotent; scores
-- upserted. sym is read-only here — signal owns its own derived store.
CREATE SCHEMA IF NOT EXISTS signal;

CREATE TABLE IF NOT EXISTS signal.factor (
    factor_key  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    direction   TEXT NOT NULL DEFAULT 'high'  -- 'high' or 'low' = which end is the favourable signal
);

CREATE TABLE IF NOT EXISTS signal.score (
    universe_id    TEXT NOT NULL,
    as_of_date     DATE NOT NULL,
    factor_key     TEXT NOT NULL REFERENCES signal.factor(factor_key),
    composite_figi CHAR(12) NOT NULL,
    raw            DOUBLE PRECISION NOT NULL,
    zscore         DOUBLE PRECISION,
    rank           INTEGER,            -- 1 = most favourable per the factor's direction
    pctile         DOUBLE PRECISION,   -- 0..1, 1 = most favourable
    PRIMARY KEY (universe_id, as_of_date, factor_key, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_signal_score_lookup
    ON signal.score (universe_id, factor_key, as_of_date, rank);

COMMIT;
