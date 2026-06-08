-- Verify qrp:portfolios on pg

BEGIN;

SELECT portfolio_id, client, name, base_currency, created_at
  FROM qrp.portfolio WHERE FALSE;
SELECT portfolio_id, as_of_date, composite_figi, weight
  FROM qrp.portfolio_weight WHERE FALSE;

ROLLBACK;
