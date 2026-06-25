-- Revert portfolio:client_entity from pg

BEGIN;

-- Restore the free-text client column, backfilling from the entity, then drop the entity.
ALTER TABLE portfolio.portfolio ADD COLUMN IF NOT EXISTS client TEXT NOT NULL DEFAULT '';
UPDATE portfolio.portfolio p
    SET client = coalesce(c.name, '')
    FROM portfolio.client c
    WHERE c.client_id = p.client_id;
DROP INDEX IF EXISTS portfolio.idx_portfolio_client;
ALTER TABLE portfolio.portfolio DROP COLUMN IF EXISTS client_id;
DROP TABLE IF EXISTS portfolio.client;

COMMIT;
