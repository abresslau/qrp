-- Verify sym:universe_accuracy_check on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

SELECT check_id, universe_id, checked_at, as_of_date, reference_source,
       maintained_count, reference_count, missing, extra, divergence, threshold,
       alarm, detail, created_at
  FROM universe_accuracy_check
 WHERE FALSE;
