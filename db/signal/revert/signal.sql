-- Revert signal:signal from pg

BEGIN;

DROP SCHEMA IF EXISTS signal CASCADE;

COMMIT;
