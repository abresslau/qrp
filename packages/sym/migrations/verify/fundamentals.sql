-- Verify sym:fundamentals on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

SELECT composite_figi, as_of_date, market_cap_lcy, market_cap_usd,
       shares_outstanding, currency_code, source, detail, created_at, updated_at
  FROM fundamentals
 WHERE FALSE;
