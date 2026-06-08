-- Revert qrp:macro from pg

BEGIN;

DROP SCHEMA IF EXISTS macro CASCADE;

COMMIT;
