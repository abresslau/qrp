-- Verify sym:fundamentals_column_order on pg

BEGIN;

-- Exact column order (errors unless it matches).
SELECT 1 / (CASE WHEN (
    SELECT string_agg(column_name, ',' ORDER BY ordinal_position)
      FROM information_schema.columns WHERE table_name = 'fundamentals'
) = 'composite_figi,as_of_date,market_cap_lcy,market_cap_usd,shares_outstanding,currency_code,source,detail,created_at,updated_at'
THEN 1 ELSE 0 END);

ROLLBACK;
