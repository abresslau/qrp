-- Revert qrp:relocate_altdata from pg

BEGIN;

-- Structural inverse: restore the altdata schema in the sym database (empty).
CREATE SCHEMA IF NOT EXISTS altdata;

CREATE TABLE IF NOT EXISTS altdata.wiki_map (
    composite_figi CHAR(12) PRIMARY KEY,
    ticker         TEXT,
    name           TEXT,
    article        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS altdata.pageview (
    composite_figi CHAR(12) NOT NULL REFERENCES altdata.wiki_map(composite_figi) ON DELETE CASCADE,
    obs_date       DATE NOT NULL,
    views          BIGINT NOT NULL,
    PRIMARY KEY (composite_figi, obs_date)
);

CREATE INDEX IF NOT EXISTS idx_altdata_pageview ON altdata.pageview (composite_figi, obs_date);

COMMIT;
