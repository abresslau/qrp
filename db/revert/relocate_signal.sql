-- Revert qrp:relocate_signal from pg

BEGIN;

-- Structural inverse: restore the signal schema in the sym database (empty — data lives in
-- the `signal` database now).
CREATE SCHEMA IF NOT EXISTS signal;

CREATE TABLE IF NOT EXISTS signal.factor (
    factor_key  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    direction   TEXT NOT NULL DEFAULT 'high'
);

CREATE TABLE IF NOT EXISTS signal.score (
    universe_id    TEXT NOT NULL,
    as_of_date     DATE NOT NULL,
    factor_key     TEXT NOT NULL REFERENCES signal.factor(factor_key),
    composite_figi CHAR(12) NOT NULL,
    raw            DOUBLE PRECISION NOT NULL,
    zscore         DOUBLE PRECISION,
    rank           INTEGER,
    pctile         DOUBLE PRECISION,
    PRIMARY KEY (universe_id, as_of_date, factor_key, composite_figi)
);

CREATE INDEX IF NOT EXISTS idx_signal_score_lookup
    ON signal.score (universe_id, factor_key, as_of_date, rank);

COMMIT;
