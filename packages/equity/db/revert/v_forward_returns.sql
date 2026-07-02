-- Revert equity:v_forward_returns from pg

BEGIN;

DROP VIEW IF EXISTS equity.v_forward_returns;

COMMIT;
