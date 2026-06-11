-- Verify sym:fact_returns on pg
-- (Reworked by QH.5's deploy-all run: later changes renamed columns this change
-- created; what survives is asserted at its CURRENT name.)

BEGIN;

SELECT composite_figi, window_id, as_of_date, pr, tr, input_hash, created_at, updated_at
  FROM fact_returns WHERE FALSE;

SELECT window_id, code, label, kind, annualized FROM return_window WHERE FALSE;

-- The core windows this change seeded survive BY CODE (a bare count would stay green
-- through retirements — the IPO precedent), and later changes only ever add.
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window WHERE code IN ('1D','1W','1M','1Y','YTD','QTD')
) = 6 AND (SELECT count(*) FROM return_window) >= 18 THEN 1 ELSE 0 END);

ROLLBACK;
