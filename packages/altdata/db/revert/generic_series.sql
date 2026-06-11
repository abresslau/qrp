-- Revert altdata:generic_series from pg

BEGIN;

-- Restores the wiki-shaped v1 tables from the generic model. Only wikipedia/pageviews rows
-- survive a revert — series from other sources (e.g. sec_edgar) are dropped with the
-- generic tables; re-deploy + re-ingest recovers them from the sources.

-- Refuse rather than fabricate: the old `article` column is NOT NULL; a wikipedia series
-- with NULL `detail` has no truthful article value to restore (coalescing to '' would
-- invent one).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM altdata.series
         WHERE source = 'wikipedia' AND metric = 'pageviews' AND detail IS NULL
    ) THEN
        RAISE EXCEPTION 'wikipedia series with NULL detail: no truthful article to restore';
    END IF;
END
$$;

CREATE TABLE altdata.wiki_map (
    composite_figi CHAR(12) PRIMARY KEY,
    ticker         TEXT,
    name           TEXT,
    article        TEXT NOT NULL
);

CREATE TABLE altdata.pageview (
    composite_figi CHAR(12) NOT NULL REFERENCES altdata.wiki_map(composite_figi) ON DELETE CASCADE,
    obs_date       DATE NOT NULL,
    views          BIGINT NOT NULL,
    PRIMARY KEY (composite_figi, obs_date)
);

CREATE INDEX idx_altdata_pageview ON altdata.pageview (composite_figi, obs_date);

INSERT INTO altdata.wiki_map (composite_figi, ticker, name, article)
SELECT composite_figi, ticker, name, detail
  FROM altdata.series
 WHERE source = 'wikipedia' AND metric = 'pageviews';

INSERT INTO altdata.pageview (composite_figi, obs_date, views)
SELECT composite_figi, obs_date, value::BIGINT
  FROM altdata.observation
 WHERE source = 'wikipedia' AND metric = 'pageviews';

DROP TABLE altdata.observation;
DROP TABLE altdata.series;

COMMIT;
