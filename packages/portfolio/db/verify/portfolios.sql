-- Verify portfolio:portfolios on pg

BEGIN;

-- The free-text `client` column this change created was migrated to a first-class
-- Client entity and dropped by the later `client_entity` change (whose verify asserts
-- the new shape). What survives of this change — and is verified here — is the rest.
SELECT portfolio_id, name, base_currency, created_at FROM portfolio.portfolio WHERE FALSE;
SELECT portfolio_id, as_of_date, composite_figi, weight
  FROM portfolio.portfolio_weight WHERE FALSE;

ROLLBACK;
