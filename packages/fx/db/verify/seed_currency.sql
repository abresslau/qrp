-- Verify fx:seed_currency on pg
-- The currency reference must be populated (a non-empty seed; USD must be present).

BEGIN;

DO $$
BEGIN
    IF (SELECT count(*) FROM fx.currency) = 0 THEN
        RAISE EXCEPTION 'fx.currency is empty — seed_currency did not populate the reference table';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM fx.currency WHERE code = 'USD') THEN
        RAISE EXCEPTION 'fx.currency is missing USD (the star base)';
    END IF;
END $$;

ROLLBACK;
