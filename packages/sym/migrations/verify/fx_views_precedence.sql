-- Verify sym:fx_views_precedence on pg

BEGIN;

-- View still selectable with its contract columns (the precedence is in its LATERAL order-by).
SELECT quote_currency, weekday_date, observed_date, rate, is_filled, days_stale
  FROM v_fx_daily WHERE FALSE;

ROLLBACK;
