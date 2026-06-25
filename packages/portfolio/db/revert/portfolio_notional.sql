-- Revert portfolio:portfolio_notional from pg

BEGIN;

ALTER TABLE portfolio.portfolio DROP COLUMN IF EXISTS notional;

COMMIT;
