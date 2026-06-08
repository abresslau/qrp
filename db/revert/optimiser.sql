-- Revert qrp:optimiser from pg

BEGIN;

DROP SCHEMA IF EXISTS optimiser CASCADE;

COMMIT;
