-- Revert qrp:portfolios from pg

BEGIN;

-- Reverted after jobs (reverse plan order), so qrp.job is already gone; drop the
-- portfolio tables then the now-empty qrp schema.
DROP TABLE IF EXISTS qrp.portfolio_weight;
DROP TABLE IF EXISTS qrp.portfolio;
DROP SCHEMA IF EXISTS qrp;

COMMIT;
