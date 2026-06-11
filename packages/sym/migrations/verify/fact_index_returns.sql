-- Verify sym:fact_index_returns on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

-- Variant-free per the amended B3 (see index_levels).
SELECT sym_id, window_id, as_of_date, ret, created_at, updated_at
  FROM fact_index_returns
 WHERE FALSE;
