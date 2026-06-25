-- Verify indices:seed_reference on pg
-- All 28 canonical return windows are present.

BEGIN;

DO $$
DECLARE
    n integer;
BEGIN
    SELECT count(*) INTO n FROM indices.return_window;
    IF n < 28 THEN
        RAISE EXCEPTION 'expected >= 28 return_window rows, found %', n;
    END IF;
END $$;

COMMIT;
