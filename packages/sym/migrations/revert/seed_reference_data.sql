-- Revert sym:seed_reference_data from pg

-- Unpopulate the reference tables. Exchanges first (FK to currency).
BEGIN;

DELETE FROM exchange;
DELETE FROM currency;

COMMIT;
