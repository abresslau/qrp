-- Verify sym:fundamentals_effective_date on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

-- This change renamed fundamentals.date -> effective_date; the canonical-date sweep
-- later renamed it again to as_of_date. The surviving fact: the dated column exists
-- under the canonical name and neither legacy name remains.
BEGIN;

SELECT as_of_date FROM fundamentals WHERE FALSE;
SELECT 1 / (CASE WHEN NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_name = 'fundamentals' AND column_name IN ('date', 'effective_date')
) THEN 1 ELSE 0 END);

ROLLBACK;
