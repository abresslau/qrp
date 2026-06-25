-- Deploy portfolio:client_entity to pg
-- requires: portfolios

BEGIN;

-- FR-13: promote the portfolio's `client` from a free-text column to a first-class entity, so
-- Clients can be created/listed and a Client→Portfolio context selected.
CREATE TABLE IF NOT EXISTS portfolio.client (
    client_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE portfolio.portfolio
    ADD COLUMN IF NOT EXISTS client_id BIGINT REFERENCES portfolio.client(client_id);

-- Backfill: one client per distinct non-empty legacy name, then link portfolio.
INSERT INTO portfolio.client (name)
    SELECT DISTINCT client FROM portfolio.portfolio WHERE client IS NOT NULL AND client <> ''
    ON CONFLICT (name) DO NOTHING;
UPDATE portfolio.portfolio p
    SET client_id = c.client_id
    FROM portfolio.client c
    WHERE c.name = p.client AND p.client <> '';

ALTER TABLE portfolio.portfolio DROP COLUMN IF EXISTS client;
CREATE INDEX IF NOT EXISTS idx_portfolio_client ON portfolio.portfolio (client_id);

COMMIT;
