-- Verify sym:cumulative_multiyear_windows on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

BEGIN;

-- The 6 cumulative multi-year windows are seeded (the IPO window this change also
-- seeded was retired by the 3.1-ext window expansion; SI/SI_ANN superseded it).
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window
     WHERE code IN ('2Y','3Y','5Y','10Y','20Y','30Y') AND annualized = false
) = 6 THEN 1 ELSE 0 END);

ROLLBACK;
