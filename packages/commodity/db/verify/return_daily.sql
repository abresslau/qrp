-- Verify commodity:return_daily on pg

BEGIN;

SELECT commodity_code, series_type, window_code, as_of_date, ret, computed_at
  FROM commodity.return_daily WHERE FALSE;

ROLLBACK;
