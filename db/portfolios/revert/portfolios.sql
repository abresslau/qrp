-- Revert portfolios:portfolios from pg

BEGIN;

DROP SCHEMA IF EXISTS portfolios CASCADE;

COMMIT;
