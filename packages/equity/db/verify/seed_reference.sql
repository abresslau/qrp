-- Verify equity:seed_reference on pg

BEGIN;

-- USD must exist (the conversion base) and all 28 windows must be seeded.
SELECT 1/count(*) FROM currency WHERE code = 'USD';
SELECT 1/(count(*) / 28) FROM return_window;

COMMIT;
