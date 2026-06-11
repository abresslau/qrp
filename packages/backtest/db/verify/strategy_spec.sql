-- Verify backtest:strategy_spec on pg

BEGIN;

SELECT spec FROM backtest.run WHERE FALSE;

ROLLBACK;
