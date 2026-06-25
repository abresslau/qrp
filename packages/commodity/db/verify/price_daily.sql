-- Verify commodity:price_daily on pg

BEGIN;

SELECT commodity_code, series_type, as_of_date, open, high, low, settle, volume,
       first_settle, source, first_published_at, last_changed_at
  FROM commodity.price_daily WHERE FALSE;

SELECT commodity_code, series_type, as_of_date, settle, prev_settle, reason, source, flagged_at
  FROM commodity.price_review WHERE FALSE;

ROLLBACK;
