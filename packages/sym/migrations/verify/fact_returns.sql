-- Verify sym:fact_returns on pg

BEGIN;

SELECT composite_figi, window_id, asof, pr, tr, input_hash, created_at, updated_at
  FROM fact_returns WHERE FALSE;

SELECT window_id, code, label, kind, annualized FROM return_window WHERE FALSE;

-- All 18 windows are seeded (errors if not).
SELECT 1 / (CASE WHEN (SELECT count(*) FROM return_window) = 18 THEN 1 ELSE 0 END);

ROLLBACK;
