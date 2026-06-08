-- Deploy qrp_core:split_portfolios to pg
-- requires: qrp_core

BEGIN;

-- Portfolio data was relocated to its own `portfolios` database + Sqitch project
-- (db/portfolios/). Drop those tables from the qrp database, which now keeps only the
-- Operate job ledger (qrp.job).
DROP TABLE IF EXISTS qrp.portfolio_weight;
DROP TABLE IF EXISTS qrp.portfolio;

COMMIT;
