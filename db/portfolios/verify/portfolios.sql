-- Verify portfolios:portfolios on pg

BEGIN;

SELECT portfolio_id, client, name, base_currency, created_at FROM portfolios.portfolio WHERE FALSE;
SELECT portfolio_id, as_of_date, composite_figi, weight
  FROM portfolios.portfolio_weight WHERE FALSE;

ROLLBACK;
