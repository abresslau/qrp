-- Revert commodity:return_daily from pg

BEGIN;

DROP TABLE IF EXISTS commodity.return_daily;

COMMIT;
