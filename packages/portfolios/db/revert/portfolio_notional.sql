-- Revert portfolios:portfolio_notional from pg

BEGIN;

ALTER TABLE portfolios.portfolio DROP COLUMN IF EXISTS notional;

COMMIT;
