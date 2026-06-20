-- Verify sym:fact_price_extremes on pg

SELECT composite_figi, as_of_date, high_52w, low_52w, high_52w_date, low_52w_date,
       pct_off_high, pct_off_low, input_hash, gated, created_at, updated_at
  FROM fact_price_extremes
 WHERE FALSE;
