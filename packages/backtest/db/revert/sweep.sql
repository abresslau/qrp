-- Revert backtest:sweep from pg

BEGIN;

ALTER TABLE backtest.run DROP COLUMN IF EXISTS sweep_id;
DROP TABLE IF EXISTS backtest.sweep;

COMMIT;
