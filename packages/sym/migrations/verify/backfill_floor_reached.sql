-- Verify sym:backfill_floor_reached on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

SELECT floor_reached_date FROM pipeline_backfill_progress WHERE FALSE;
