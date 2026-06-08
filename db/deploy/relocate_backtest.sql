-- Deploy qrp:relocate_backtest to pg
-- requires: backtest

BEGIN;

-- backtest relocated to its own database + Sqitch project `backtest` (db/backtest/). Data
-- copied there first; drop the redundant schema from the sym database.
DROP SCHEMA IF EXISTS backtest CASCADE;

COMMIT;
