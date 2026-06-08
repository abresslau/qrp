-- Verify portfolios:client_entity on pg

BEGIN;

SELECT client_id, name, created_at FROM portfolios.client WHERE FALSE;
SELECT client_id FROM portfolios.portfolio WHERE FALSE;  -- FK column present

ROLLBACK;
