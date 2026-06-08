-- Revert altdata:altdata from pg

BEGIN;

DROP SCHEMA IF EXISTS altdata CASCADE;

COMMIT;
