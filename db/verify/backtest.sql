-- Verify qrp:backtest on pg

BEGIN;

SELECT run_id, created_at, factor, universe_id, top_pct, rebalance, start_date, end_date,
       n_days, n_rebalances, summary
  FROM backtest.run WHERE FALSE;
SELECT run_id, obs_date, strat_cum, base_cum FROM backtest.point WHERE FALSE;

ROLLBACK;
