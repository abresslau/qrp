-- Revert qrp:altdata from pg

BEGIN;

DROP SCHEMA IF EXISTS altdata CASCADE;

COMMIT;
