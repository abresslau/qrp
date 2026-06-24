-- Revert commodities:price_daily from pg

BEGIN;

DROP TABLE IF EXISTS commodities.price_review;
DROP TABLE IF EXISTS commodities.price_daily;

COMMIT;
