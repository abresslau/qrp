-- Verify qrp:altdata on pg

BEGIN;

SELECT composite_figi, ticker, name, article FROM altdata.wiki_map WHERE FALSE;
SELECT composite_figi, obs_date, views FROM altdata.pageview WHERE FALSE;

ROLLBACK;
