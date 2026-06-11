-- Verify sym:index_levels on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

-- The amended B3 accepted variant-free storage; the variant column never shipped.
SELECT sym_id, session_date, level, source, created_at
  FROM index_levels
 WHERE FALSE;
