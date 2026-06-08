-- Verify sym:fact_returns_gated on pg

BEGIN;

SELECT gated FROM fact_returns WHERE FALSE;

ROLLBACK;
