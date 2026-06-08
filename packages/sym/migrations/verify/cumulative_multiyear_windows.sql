-- Verify sym:cumulative_multiyear_windows on pg

BEGIN;

-- All 7 cumulative multi-year/IPO windows seeded (errors if not exactly 7).
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window
     WHERE code IN ('2Y','3Y','5Y','10Y','20Y','30Y','IPO') AND annualized = false
) = 7 THEN 1 ELSE 0 END);

ROLLBACK;
