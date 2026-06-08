-- Verify sym:fundamentals on pg

SELECT composite_figi, as_of, market_cap, shares_outstanding, currency_code,
       source, detail, created_at, updated_at
  FROM fundamentals
 WHERE FALSE;
