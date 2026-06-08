-- Verify qrp:optimiser on pg

BEGIN;

SELECT solution_id, created_at, universe_id, method, n_assets, lookback_days,
       exp_return, exp_vol, sharpe, ew_vol, summary
  FROM optimiser.solution WHERE FALSE;
SELECT solution_id, composite_figi, ticker, weight FROM optimiser.weight WHERE FALSE;

ROLLBACK;
