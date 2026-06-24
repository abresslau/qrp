-- Verify fx:fx_schema on pg

BEGIN;

SELECT 1/count(*) FROM pg_namespace WHERE nspname = 'fx';
SELECT code, name FROM fx.currency WHERE false;
SELECT base_currency, quote_currency, as_of_date, rate, source, inserted_at
  FROM fx.fx_rate WHERE false;
SELECT review_id, quote_currency, as_of_date, rate, prior_rate, relative_move,
       source, reason, reviewed, resolution, reviewed_at, created_at
  FROM fx.fx_rate_review WHERE false;
SELECT fx.fx_source_rank('frankfurter');
SELECT base_currency, quote_currency, as_of_date, rate, source FROM fx.v_fx WHERE false;
SELECT quote_currency, weekday_date, observed_date, rate, is_filled, days_stale
  FROM fx.v_fx_daily WHERE false;

ROLLBACK;
