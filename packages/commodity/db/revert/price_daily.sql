-- Revert commodity:price_daily from pg

BEGIN;

DROP TABLE IF EXISTS commodity.price_review;
DROP TABLE IF EXISTS commodity.price_daily;

COMMIT;
