-- Revert qrp:backtest from pg

BEGIN;

DROP SCHEMA IF EXISTS backtest CASCADE;

COMMIT;
