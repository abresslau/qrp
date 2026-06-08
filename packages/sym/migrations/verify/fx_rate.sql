-- Verify sym:fx_rate on pg

BEGIN;

-- Column shape.
SELECT base_currency, quote_currency, as_of_date, rate, source, inserted_at
  FROM fx_rate WHERE FALSE;

-- The integrity constraints exist (errors if either is missing).
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM pg_constraint
     WHERE conrelid = 'fx_rate'::regclass
       AND conname IN ('fx_rate_canonical_direction', 'fx_rate_rate_positive')
) = 2 THEN 1 ELSE 0 END);

ROLLBACK;
