-- Verify sym:v_prices_adjusted on pg

BEGIN;

-- View is present and exposes the expected columns.
SELECT composite_figi, session_date, currency_code, close_raw, split_factor, adj_close
  FROM v_prices_adjusted
 WHERE FALSE;

-- The product aggregate is EXACT: 2 * 3 * 4 = 24 (errors if not, e.g. float drift).
SELECT 1 / (CASE WHEN product(r) = 24 THEN 1 ELSE 0 END)
  FROM (VALUES (2::numeric), (3::numeric), (4::numeric)) AS v(r);

ROLLBACK;
