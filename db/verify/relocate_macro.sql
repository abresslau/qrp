-- Verify qrp:relocate_macro on pg

BEGIN;

-- Assert the macro schema is ABSENT from the sym database (it lives in the `macro` database now).
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'macro') THEN
        RAISE EXCEPTION 'macro schema still present in this database (expected: relocated)';
    END IF;
END $$;

ROLLBACK;
