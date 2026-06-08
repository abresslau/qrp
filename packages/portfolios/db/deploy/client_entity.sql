-- Deploy portfolios:client_entity to pg
-- requires: portfolios

BEGIN;

-- FR-13: promote the portfolio's `client` from a free-text column to a first-class entity, so
-- Clients can be created/listed and a Client→Portfolio context selected.
CREATE TABLE IF NOT EXISTS portfolios.client (
    client_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE portfolios.portfolio
    ADD COLUMN IF NOT EXISTS client_id BIGINT REFERENCES portfolios.client(client_id);

-- Backfill: one client per distinct non-empty legacy name, then link portfolios.
INSERT INTO portfolios.client (name)
    SELECT DISTINCT client FROM portfolios.portfolio WHERE client IS NOT NULL AND client <> ''
    ON CONFLICT (name) DO NOTHING;
UPDATE portfolios.portfolio p
    SET client_id = c.client_id
    FROM portfolios.client c
    WHERE c.name = p.client AND p.client <> '';

ALTER TABLE portfolios.portfolio DROP COLUMN IF EXISTS client;
CREATE INDEX IF NOT EXISTS idx_portfolio_client ON portfolios.portfolio (client_id);

COMMIT;
