-- Verify sym:fx_rate_review on pg

SELECT review_id, quote_currency, as_of_date, rate, reason, reviewed
  FROM fx_rate_review WHERE FALSE;

SELECT 1/count(*) FROM pg_indexes
 WHERE tablename = 'fx_rate_review' AND indexname = 'uq_fx_rate_review_open';
