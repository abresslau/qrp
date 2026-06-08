-- Revert portfolios:client_entity from pg

BEGIN;

-- Restore the free-text client column, backfilling from the entity, then drop the entity.
ALTER TABLE portfolios.portfolio ADD COLUMN IF NOT EXISTS client TEXT NOT NULL DEFAULT '';
UPDATE portfolios.portfolio p
    SET client = coalesce(c.name, '')
    FROM portfolios.client c
    WHERE c.client_id = p.client_id;
DROP INDEX IF EXISTS portfolios.idx_portfolio_client;
ALTER TABLE portfolios.portfolio DROP COLUMN IF EXISTS client_id;
DROP TABLE IF EXISTS portfolios.client;

COMMIT;
