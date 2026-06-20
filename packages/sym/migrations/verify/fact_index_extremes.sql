-- Verify sym:fact_index_extremes on pg

SELECT sym_id, as_of_date, high_52w, low_52w, high_52w_date, low_52w_date,
       pct_off_high, pct_off_low, input_hash, created_at, updated_at
  FROM fact_index_extremes
 WHERE FALSE;
