-- Revert equity:seed_reference from pg

BEGIN;

-- Reference seed; clearing it would break the equity_schema FKs only if facts exist. The schema
-- revert drops the tables wholesale, so this revert just empties the seeded reference rows.
DELETE FROM public.return_window;
DELETE FROM public.currency;

COMMIT;
