-- Revert signals:signals from pg

BEGIN;

DROP SCHEMA IF EXISTS signals CASCADE;

COMMIT;
