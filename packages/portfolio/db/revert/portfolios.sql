-- Revert portfolio:portfolios from pg

BEGIN;

DROP SCHEMA IF EXISTS portfolio CASCADE;

COMMIT;
