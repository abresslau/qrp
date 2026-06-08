-- Deploy altdata:altdata to pg

BEGIN;

-- The `altdata` package's own database: alternative-data signals (v1 = Wikimedia pageviews
-- as a per-company attention proxy), mapped to sym securities by composite_figi. The read API
-- is standalone (wiki_map carries ticker + name); the ingest reads sym read-only to resolve
-- figis. No FK to sym (value-only composite_figi keys).
CREATE SCHEMA IF NOT EXISTS altdata;

CREATE TABLE IF NOT EXISTS altdata.wiki_map (
    composite_figi CHAR(12) PRIMARY KEY,
    ticker         TEXT,
    name           TEXT,
    article        TEXT NOT NULL          -- en.wikipedia article title
);

CREATE TABLE IF NOT EXISTS altdata.pageview (
    composite_figi CHAR(12) NOT NULL REFERENCES altdata.wiki_map(composite_figi) ON DELETE CASCADE,
    obs_date       DATE NOT NULL,
    views          BIGINT NOT NULL,
    PRIMARY KEY (composite_figi, obs_date)
);

CREATE INDEX IF NOT EXISTS idx_altdata_pageview ON altdata.pageview (composite_figi, obs_date);

COMMIT;
