-- Revert qrp:relocate_macro from pg

BEGIN;

-- Structural inverse: restore the macro schema in the sym database (empty — data lives in the
-- `macro` database now). Returns the project to its pre-relocate structure.
CREATE SCHEMA IF NOT EXISTS macro;

CREATE TABLE IF NOT EXISTS macro.series (
    series_id   TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    name        TEXT NOT NULL,
    geo         TEXT,
    unit        TEXT,
    frequency   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS macro.observation (
    series_id   TEXT NOT NULL REFERENCES macro.series(series_id) ON DELETE CASCADE,
    obs_date    DATE NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (series_id, obs_date)
);

CREATE INDEX IF NOT EXISTS idx_macro_obs_series_date
    ON macro.observation (series_id, obs_date);

COMMIT;
