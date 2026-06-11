-- Verify sym:fundamentals_date_column on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

-- The column this change added was renamed twice (date -> effective_date -> as_of_date).
SELECT as_of_date FROM fundamentals WHERE FALSE;
