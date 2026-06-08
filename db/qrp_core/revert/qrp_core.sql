-- Revert qrp_core:qrp_core from pg

BEGIN;

DROP SCHEMA IF EXISTS qrp CASCADE;

COMMIT;
