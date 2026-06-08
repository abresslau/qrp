-- Revert qrp:signal from pg

BEGIN;

DROP SCHEMA IF EXISTS signal CASCADE;

COMMIT;
