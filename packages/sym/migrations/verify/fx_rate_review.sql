-- Verify sym:fx_rate_review on pg

SELECT review_id, quote_currency, as_of_date, rate, reason, reviewed
  FROM fx_rate_review WHERE FALSE;
