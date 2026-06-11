-- Deploy altdata:generic_series to pg
-- requires: altdata

BEGIN;

-- Q8.3: generalise the wiki-shaped schema (wiki_map + pageview) into a generic entity-keyed
-- series model so a second source archetype (SEC EDGAR filing activity) and later sources
-- land as rows, not new tables. A series is one metric from one source for one sym security
-- (value-only composite_figi key — no FK to sym, AR-R3). `detail` carries the source-native
-- key (wikipedia article title / zero-padded SEC CIK) — the source provenance record.
CREATE TABLE altdata.series (
    composite_figi CHAR(12) NOT NULL,
    source         TEXT NOT NULL,
    metric         TEXT NOT NULL,
    ticker         TEXT,
    name           TEXT,
    detail         TEXT,
    unit           TEXT,
    frequency      TEXT NOT NULL DEFAULT 'daily',
    PRIMARY KEY (composite_figi, source, metric)
);

COMMENT ON TABLE altdata.series IS
    'One alt-data series per (security, source, metric). detail = source-native key '
    '(wikipedia article / SEC CIK): the provenance record for the series.';

-- DOUBLE PRECISION holds the integer count/view metrics exactly (all far below 2^53) and
-- admits future non-integer metrics without another migration.
CREATE TABLE altdata.observation (
    composite_figi CHAR(12) NOT NULL,
    source         TEXT NOT NULL,
    metric         TEXT NOT NULL,
    obs_date       DATE NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (composite_figi, source, metric, obs_date),
    FOREIGN KEY (composite_figi, source, metric)
        REFERENCES altdata.series (composite_figi, source, metric) ON DELETE CASCADE
);

COMMENT ON COLUMN altdata.observation.obs_date IS
    'Time-series observation date (NOT an as-of/business date). For sparse count metrics '
    '(e.g. SEC filing counts) absent dates are true zeros, derivable, never stored.';

-- Migrate the existing Wikimedia data, then retire the wiki-shaped tables.
INSERT INTO altdata.series (composite_figi, source, metric, ticker, name, detail, unit, frequency)
SELECT composite_figi, 'wikipedia', 'pageviews', ticker, name, article, 'views', 'daily'
  FROM altdata.wiki_map;

INSERT INTO altdata.observation (composite_figi, source, metric, obs_date, value)
SELECT composite_figi, 'wikipedia', 'pageviews', obs_date, views
  FROM altdata.pageview;

DROP TABLE altdata.pageview;
DROP TABLE altdata.wiki_map;

COMMIT;
