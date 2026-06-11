-- Verify signals:factor_traceability on pg

BEGIN;

SELECT inputs, method FROM signals.factor WHERE FALSE;

ROLLBACK;
