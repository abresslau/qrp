-- Verify qrp_core:qrp_core on pg

BEGIN;

SELECT portfolio_id, client, name, base_currency, created_at FROM qrp.portfolio WHERE FALSE;
SELECT portfolio_id, as_of_date, composite_figi, weight FROM qrp.portfolio_weight WHERE FALSE;
SELECT job_id, op, args, status, exit_code, output, error, created_at, started_at, finished_at
  FROM qrp.job WHERE FALSE;

ROLLBACK;
