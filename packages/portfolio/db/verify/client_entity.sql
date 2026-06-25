-- Verify portfolio:client_entity on pg

BEGIN;

SELECT client_id, name, created_at FROM portfolio.client WHERE FALSE;
SELECT client_id FROM portfolio.portfolio WHERE FALSE;  -- FK column present

ROLLBACK;
