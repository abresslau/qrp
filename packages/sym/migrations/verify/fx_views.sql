-- Verify sym:fx_views on pg

BEGIN;

SELECT base_currency, quote_currency, as_of_date, rate, source FROM v_fx WHERE FALSE;
SELECT quote_currency, weekday_date, observed_date, rate, is_filled, days_stale
  FROM v_fx_daily WHERE FALSE;

ROLLBACK;
