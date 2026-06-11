-- Verify altdata:altdata on pg

BEGIN;

-- The wiki-shaped tables this change created were migrated into the generic series model
-- and dropped by the later `generic_series` change (whose verify asserts the new shape).
-- What survives of this change — and what is verified here — is the schema itself.
DO $$
BEGIN
    IF to_regnamespace('altdata') IS NULL THEN
        RAISE EXCEPTION 'altdata schema missing';
    END IF;
END
$$;

ROLLBACK;
