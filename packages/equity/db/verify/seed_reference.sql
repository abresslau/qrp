-- Verify equity:seed_reference on pg

BEGIN;

-- USD must exist (the conversion base) and all 28 windows must be seeded.
SELECT 1/count(*) FROM public.currency WHERE code = 'USD';
SELECT 1/(count(*) / 28) FROM public.return_window;

COMMIT;
