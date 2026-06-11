-- Revert backtest:strategy_spec from pg

BEGIN;

ALTER TABLE backtest.run DROP COLUMN IF EXISTS spec;

COMMIT;
