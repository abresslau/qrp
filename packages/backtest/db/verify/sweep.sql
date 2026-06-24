-- Verify backtest:sweep on pg

BEGIN;

SELECT sweep_id, created_at, base_spec, grid, n_configs, best_run_id, summary
  FROM backtest.sweep WHERE FALSE;
SELECT sweep_id FROM backtest.run WHERE FALSE;

ROLLBACK;
