-- Deploy macro:macro to pg

BEGIN;

-- The `macro` package's own database (NOT sym, NOT the qrp database): central-bank /
-- macroeconomic series ingested from public sources (World Bank, ECB Data Portal). Two
-- tables: a series catalog and its observations. Idempotent; observations upserted. sym is
-- never touched — macro is independent reference data the platform owns, keyed by its own ids.
CREATE SCHEMA IF NOT EXISTS macro;

CREATE TABLE IF NOT EXISTS macro.series (
    series_id   TEXT PRIMARY KEY,           -- e.g. 'WB:FP.CPI.TOTL.ZG:BRA'
    source      TEXT NOT NULL,              -- 'worldbank' | 'ecb'
    name        TEXT NOT NULL,
    geo         TEXT,                        -- country / area label
    unit        TEXT,
    frequency   TEXT,                        -- 'annual' | 'monthly' | 'daily'
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
